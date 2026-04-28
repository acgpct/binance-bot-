"""DCA bot with tactical multiplier — buys $X of an ETF on a weekly schedule.

Three modes:
  simulation: no broker connection. Pretends to buy at yfinance prices and
              logs to data/dca_history.csv. Lets you validate scheduling
              and the multiplier logic without an IBKR account.
  paper:      uses Interactive Brokers paper-trading account (port 7497).
              Real connection but fake money. Requires IB Gateway running.
  live:       real money on IBKR (port 7496). Requires IB Gateway and
              explicit confirmation.

Tactical multiplier: buys MORE when the broad market (S&P 500) is down,
LESS when it's pumping. Empirically improves DCA returns slightly without
adding much risk.

Run:
  python -m src.dca_bot --dry-run                         # show what it would do
  python -m src.dca_bot                                   # buy in simulation mode
  python -m src.dca_bot --mode paper --ticker VWCE.AS     # IBKR paper
  python -m src.dca_bot --mode live --ticker VWCE.AS      # IBKR real money
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DCA_HISTORY = ROOT / "data" / "dca_history.csv"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("dca")


# ----------------------------------------------------------------------
# Tactical multiplier — buy more when market is down, less when up
# ----------------------------------------------------------------------
def compute_weekly_return(benchmark: str = "SPY", lookback_days: int = 5) -> float:
    """Returns the % change of `benchmark` over the trailing N trading days."""
    import yfinance as yf

    hist = yf.Ticker(benchmark).history(period=f"{max(lookback_days * 3, 14)}d")
    if len(hist) < lookback_days + 1:
        return 0.0
    recent = float(hist["Close"].iloc[-1])
    prior = float(hist["Close"].iloc[-lookback_days - 1])
    return (recent / prior - 1) * 100


def tactical_multiplier(weekly_return_pct: float) -> tuple[float, str]:
    """Maps last-week's S&P 500 return to a multiplier on the base DCA amount.

    Heuristic (gentle, not aggressive):
      ≤ -7%  → 2.0x  (big drop, buy double)
      ≤ -3%  → 1.5x  (medium drop, buy 50% more)
      ≤  +3% → 1.0x  (normal week)
      ≤  +7% → 0.7x  (rally, slow down)
      >  +7% → 0.5x  (big pump, half allocation)
    """
    if weekly_return_pct <= -7:
        return 2.0, "big drop — doubling allocation"
    if weekly_return_pct <= -3:
        return 1.5, "moderate drop — +50% allocation"
    if weekly_return_pct <= 3:
        return 1.0, "normal week — base allocation"
    if weekly_return_pct <= 7:
        return 0.7, "rally — 70% allocation"
    return 0.5, "big pump — half allocation (saving cash for the dip)"


# ----------------------------------------------------------------------
# Buy execution — three modes
# ----------------------------------------------------------------------
def get_yf_price(ticker: str) -> float:
    """Fetch a current-ish price via yfinance (free, no auth)."""
    import yfinance as yf

    t = yf.Ticker(ticker)
    info = t.fast_info
    px = (info.get("last_price") if hasattr(info, "get") else getattr(info, "last_price", None))
    if not px:
        hist = t.history(period="2d")
        if len(hist):
            px = float(hist["Close"].iloc[-1])
    if not px:
        raise RuntimeError(f"could not get a price for {ticker}")
    return float(px)


def buy_simulation(ticker: str, quote_amount: float) -> dict:
    """Pretend to buy at yfinance's last price. No real order."""
    price = get_yf_price(ticker)
    shares = quote_amount / price
    return {
        "ticker": ticker, "mode": "simulation",
        "shares": shares, "price": price, "cost": quote_amount,
    }


def buy_ibkr(ticker: str, quote_amount: float, mode: str,
             host: str, port: int, client_id: int,
             exchange: str = "SMART", currency: str = "USD") -> dict:
    """Place a real (paper or live) market BUY via Interactive Brokers."""
    from ib_insync import IB, Stock, MarketOrder

    ib = IB()
    log.info(f"  Connecting to IB Gateway at {host}:{port} (clientId={client_id})...")
    try:
        ib.connect(host, port, clientId=client_id)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"could not connect to IB Gateway at {host}:{port} — is it running?\n  {e}"
        ) from e

    contract = Stock(ticker, exchange, currency)
    ib.qualifyContracts(contract)

    md = ib.reqMktData(contract, "", False, False)
    ib.sleep(2)
    price = md.marketPrice()
    if not price or price != price:  # NaN guard
        price = md.last or md.close
    if not price:
        ib.disconnect()
        raise RuntimeError(f"could not get a market price for {ticker} on {exchange}")

    shares = max(int(quote_amount / price), 1)
    if shares * price > quote_amount * 1.05:
        log.warning(f"  rounding makes {shares} shares cost more than {quote_amount} — skipping")
        ib.disconnect()
        return {"ticker": ticker, "mode": mode, "shares": 0, "price": price, "cost": 0}

    order = MarketOrder("BUY", shares)
    trade = ib.placeOrder(contract, order)
    ib.sleep(3)
    fill_price = (trade.orderStatus.avgFillPrice if trade.orderStatus.avgFillPrice else price)
    ib.disconnect()

    return {
        "ticker": ticker, "mode": mode,
        "shares": shares, "price": float(fill_price), "cost": shares * float(fill_price),
    }


# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
def append_history(record: dict, base_amount: float, multiplier: float,
                   weekly_return: float) -> None:
    DCA_HISTORY.parent.mkdir(exist_ok=True)
    is_new = not DCA_HISTORY.exists()
    with DCA_HISTORY.open("a", newline="") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["timestamp", "ticker", "mode", "base_amount",
                        "multiplier", "actual_amount", "shares",
                        "price", "weekly_return_pct"])
        w.writerow([
            datetime.now(timezone.utc).isoformat(),
            record["ticker"], record["mode"],
            f"{base_amount:.2f}", f"{multiplier:.2f}",
            f"{record['cost']:.2f}", f"{record['shares']:.6f}",
            f"{record['price']:.4f}", f"{weekly_return:.2f}",
        ])


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", default=os.getenv("DCA_TICKER", "VT"),
                        help="ETF symbol. Defaults to VT (Vanguard Total World, USD). "
                             "Use VWCE.AS for the EUR-denominated UCITS version on Amsterdam.")
    parser.add_argument("--amount", type=float, default=float(os.getenv("DCA_BASE_AMOUNT", "500")),
                        help="Base amount to invest each cycle, in the ETF's quote currency.")
    parser.add_argument("--mode",
                        default=os.getenv("DCA_MODE", "simulation"),
                        choices=["simulation", "paper", "live"])
    parser.add_argument("--no-tactical", action="store_true",
                        help="Disable the tactical multiplier (pure boring DCA).")
    parser.add_argument("--benchmark", default="SPY",
                        help="Ticker used for the tactical multiplier. Default SPY.")
    parser.add_argument("--exchange", default=os.getenv("DCA_EXCHANGE", "SMART"),
                        help="IBKR exchange routing (SMART, AEB, NYSE, etc.). Ignored in sim.")
    parser.add_argument("--currency", default=os.getenv("DCA_CURRENCY", "USD"),
                        help="Currency the ETF is denominated in. Ignored in sim.")
    parser.add_argument("--ib-host", default=os.getenv("IBKR_HOST", "127.0.0.1"))
    parser.add_argument("--ib-port", type=int,
                        default=int(os.getenv("IBKR_PORT", "0")) or None)
    parser.add_argument("--ib-client-id", type=int,
                        default=int(os.getenv("IBKR_CLIENT_ID", "2")))
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute multiplier and log what it would do, but place no order.")
    args = parser.parse_args()

    # Compute the tactical multiplier
    if args.no_tactical:
        multiplier, reason = 1.0, "tactical disabled — pure DCA"
        weekly = 0.0
    else:
        try:
            weekly = compute_weekly_return(args.benchmark)
            multiplier, reason = tactical_multiplier(weekly)
        except Exception as e:  # noqa: BLE001
            log.warning(f"  could not compute tactical multiplier ({e}); defaulting to 1.0")
            weekly, multiplier, reason = 0.0, 1.0, "fallback (no benchmark data)"

    actual = round(args.amount * multiplier, 2)

    log.info("=" * 70)
    log.info(f"DCA cycle — ticker={args.ticker} mode={args.mode}")
    log.info(f"  Benchmark ({args.benchmark}) trailing-week return: {weekly:+.2f}%")
    log.info(f"  Multiplier:        {multiplier:.2f}x  ({reason})")
    log.info(f"  Base amount:       {args.amount:.2f} {args.currency}")
    log.info(f"  Actual amount:     {actual:.2f} {args.currency}")

    if args.dry_run:
        log.info("  [dry-run] no order placed")
        return 0

    if args.mode == "live":
        log.warning("  ⚠️  LIVE MODE — real money. Ctrl+C in 5s to abort.")
        import time
        time.sleep(5)

    try:
        if args.mode == "simulation":
            record = buy_simulation(args.ticker, actual)
        else:
            port = args.ib_port or (7497 if args.mode == "paper" else 7496)
            record = buy_ibkr(
                args.ticker, actual, args.mode,
                host=args.ib_host, port=port, client_id=args.ib_client_id,
                exchange=args.exchange, currency=args.currency,
            )
    except Exception as e:  # noqa: BLE001
        log.error(f"  buy failed: {e}")
        return 1

    if record["shares"] == 0:
        log.warning("  No shares purchased — nothing to log.")
        return 0

    log.info(f"  ✓ Bought {record['shares']:.4f} {args.ticker} @ {record['price']:.4f} "
             f"= {record['cost']:.2f} {args.currency}")
    append_history(record, args.amount, multiplier, weekly)
    log.info(f"  Logged to {DCA_HISTORY.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
