"""Live rotational momentum bot.

Each rebalance cycle:
  1. Scan mainnet top-N USDT pairs (data only, no auth)
  2. Score & rank by momentum + trend filter
  3. Filter to symbols actually tradeable on the configured exchange (testnet by default)
  4. Sell holdings that fall out of top-K
  5. Buy new picks with available USDT (equal-weight)
  6. Persist state, sleep until next rebalance

Defaults to the best risk-adjusted config from stress_test.py:
  top_k=5, momentum_lookback=60 bars, rebalance every 6 bars (= daily on 4h)

Run:
  python -m src.rotation_bot --show-picks            # see what it would pick, no orders
  python -m src.rotation_bot --dry-run --once        # run one full cycle, log only
  python -m src.rotation_bot --once                  # one cycle, place orders
  python -m src.rotation_bot                         # continuous loop
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import ccxt

from src.exchange import get_data_exchange, get_exchange, is_live
from src.scanner import get_universe, scan

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("rotation")

STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "rotation_state.json"
EQUITY_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "equity_history.csv"


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"holdings": {}, "last_rebalance": None}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def usdt_value(exchange: ccxt.Exchange, symbol: str, units: float) -> float:
    try:
        ticker = exchange.fetch_ticker(symbol)
        return float(units) * float(ticker["last"])
    except Exception:  # noqa: BLE001
        return 0.0


def market_sell(exchange: ccxt.Exchange, symbol: str, units: float) -> dict | None:
    """Sell `units` of `symbol` — but never more than the actual exchange balance.

    Prevents 'insufficient balance' errors when our state file drifts from reality
    (e.g. testnet quirks, partial fills, or rounding). This is the defensive
    pattern: trust the exchange's view of your balance, not your local state.
    """
    try:
        base = symbol.split("/")[0]
        actual_free = float(exchange.fetch_balance().get(base, {}).get("free", 0))
        if actual_free <= 0:
            log.warning(f"  SELL {symbol} skipped: no {base} on the exchange")
            return None
        if actual_free < units:
            log.warning(f"  SELL {symbol}: state has {units} {base} but exchange shows "
                        f"only {actual_free}; selling what we actually have")
            units = actual_free

        units = float(exchange.amount_to_precision(symbol, units))
        market = exchange.market(symbol)
        min_amount = (market.get("limits", {}).get("amount", {}) or {}).get("min")
        if min_amount and units < min_amount:
            log.warning(f"  SELL {symbol} skipped: {units} below min {min_amount}")
            return None
        order = exchange.create_market_sell_order(symbol, units)
        log.info(f"  SOLD {symbol}: {units} @ ~{order.get('average')}")
        return order
    except Exception as e:  # noqa: BLE001
        log.error(f"  SELL {symbol} failed: {e}")
        return None


def market_buy_quote(exchange: ccxt.Exchange, symbol: str, quote_amount: float) -> dict | None:
    """Spend `quote_amount` USDT (or whatever quote) to buy the base asset."""
    try:
        # Binance: pass quoteOrderQty to spend an exact USDT amount.
        order = exchange.create_order(
            symbol, "MARKET", "BUY", None, None,
            params={"quoteOrderQty": round(quote_amount, 2)},
        )
        log.info(f"  BOUGHT {symbol}: spent ~${quote_amount:.2f}, "
                 f"got {order.get('amount')} @ ~{order.get('average')}")
        return order
    except Exception as e:  # noqa: BLE001
        log.error(f"  BUY {symbol} (${quote_amount:.2f}) failed: {e}")
        return None


def equity_usdt(exchange: ccxt.Exchange, holdings: dict, quote: str = "USDT") -> tuple[float, float]:
    """Return (cash_usdt, total_usdt_equity) for our managed holdings + USDT balance."""
    bal = exchange.fetch_balance()
    cash = float(bal.get(quote, {}).get("free", 0.0))
    pos_value = 0.0
    for sym in holdings.keys():
        units = holdings[sym].get("units", 0)
        pos_value += usdt_value(exchange, sym, units)
    return cash, cash + pos_value


def reconcile_state_with_exchange(exchange: ccxt.Exchange, state: dict) -> dict:
    """Sync state's tracked unit counts with what's actually on the exchange.

    Why this matters:
      * Testnet quirks (capped fills, seeded balances) cause state to drift from reality
      * Bot restarts can miss positions opened by a previous run on the same account
      * Partial fills, rounding, and dust accumulate over time

    Behaviour for each symbol already in state:
      * actual > 0          → set state.units = actual (use the truth)
      * actual == 0         → drop the symbol from state (we've effectively sold it elsewhere)

    Does NOT auto-adopt symbols that aren't in state — we only manage what we
    explicitly bought. This avoids the bot trying to manage random testnet seed
    coins or pre-existing balances the user wants to keep separate.
    """
    holdings = state.get("holdings", {})
    if not holdings:
        return state

    bal = exchange.fetch_balance()
    cleaned = {}
    changed = []
    for sym, info in holdings.items():
        base = sym.split("/")[0]
        actual = float(bal.get(base, {}).get("free", 0))
        old_units = float(info.get("units", 0))
        if actual <= 0:
            changed.append(f"{sym} dropped (actual=0)")
            continue
        if abs(actual - old_units) > old_units * 0.001:
            changed.append(f"{sym}: {old_units:.4f} → {actual:.4f}")
        info["units"] = actual
        cleaned[sym] = info

    state["holdings"] = cleaned
    if changed:
        log.info(f"Reconciled state with exchange: {'; '.join(changed)}")
    return state


def log_equity_snapshot(exchange: ccxt.Exchange, holdings: dict, cash: float,
                        equity: float, btc_price: float | None = None) -> None:
    """Append a row to the equity history CSV (for the dashboard)."""
    if btc_price is None:
        try:
            btc_price = float(exchange.fetch_ticker("BTC/USDT")["last"])
        except Exception:  # noqa: BLE001
            btc_price = 0.0

    EQUITY_LOG_PATH.parent.mkdir(exist_ok=True)
    is_new = not EQUITY_LOG_PATH.exists()
    with EQUITY_LOG_PATH.open("a") as f:
        if is_new:
            f.write("timestamp,equity,cash,btc_price,n_positions,holdings\n")
        ts = datetime.now(timezone.utc).isoformat()
        symbols = "|".join(holdings.keys())
        f.write(f"{ts},{equity:.4f},{cash:.4f},{btc_price:.4f},{len(holdings)},{symbols}\n")


def pick_targets(data_exchange: ccxt.Exchange, trade_exchange: ccxt.Exchange,
                 universe_size: int, timeframe: str, days: int,
                 momentum_lookback: int, top_k: int, min_volume_usd: float) -> list[dict]:
    universe = get_universe(data_exchange, top_n=universe_size, min_volume_usd=min_volume_usd)
    log.info(f"Universe: {len(universe)} coins (top by volume)")

    df = scan(data_exchange, universe, timeframe=timeframe, days=days,
              momentum_lookback=momentum_lookback)
    if len(df) == 0:
        log.warning("No coins passed the trend filter.")
        return []

    # Filter to symbols tradeable on the trade exchange (testnet has fewer)
    trade_exchange.load_markets()
    tradeable = set(trade_exchange.symbols)
    df = df[df["symbol"].isin(tradeable)]

    picks = df.head(top_k).to_dict("records")
    log.info(f"Top {top_k} tradeable picks (of {len(df)} uptrending tradeable):")
    for i, p in enumerate(picks, 1):
        log.info(f"  {i}. {p['symbol']:<14} momentum={p['momentum_pct']:+6.2f}%  "
                 f"above_long={p['above_long_pct']:+5.2f}%  "
                 f"atr={p['atr_pct']:.2f}%  vol=${p['quote_volume_m']:.0f}M")
    return picks


def rebalance(data_exchange: ccxt.Exchange, trade_exchange: ccxt.Exchange,
              state: dict, args: argparse.Namespace) -> None:
    log.info("=" * 70)
    log.info(f"REBALANCE CYCLE — mode={'LIVE' if is_live() else 'TESTNET'} "
             f"dry_run={args.dry_run}")

    # Self-heal state before any decisions: trust the exchange, not the local file.
    reconcile_state_with_exchange(trade_exchange, state)
    if not args.dry_run:
        save_state(state)

    picks = pick_targets(data_exchange, trade_exchange,
                         universe_size=args.universe, timeframe=args.timeframe,
                         days=args.days, momentum_lookback=args.momentum_lookback,
                         top_k=args.top_k, min_volume_usd=args.min_volume)
    if not picks:
        log.warning("No picks — skipping rebalance")
        return

    pick_symbols = {p["symbol"] for p in picks}
    holdings: dict = state.get("holdings", {})

    cash_before, equity_before = equity_usdt(trade_exchange, holdings)
    log.info(f"Pre-rebalance: cash=${cash_before:.2f}  equity=${equity_before:.2f}  "
             f"holdings={list(holdings.keys())}")

    if args.show_picks:
        log.info("(--show-picks mode: no further action)")
        return

    # 1. SELL holdings that fell out of the top-K
    to_sell = [sym for sym in holdings if sym not in pick_symbols]
    for sym in to_sell:
        units = holdings[sym].get("units", 0)
        if units <= 0:
            holdings.pop(sym, None)
            continue
        if args.dry_run:
            log.info(f"  [dry-run] would SELL {sym}: {units} units")
            holdings.pop(sym, None)
        else:
            order = market_sell(trade_exchange, sym, units)
            if order is not None:
                holdings.pop(sym, None)

    # Persist sells before buying (real runs only — dry-runs never touch state)
    if not args.dry_run:
        state["holdings"] = holdings
        save_state(state)
        if to_sell:
            time.sleep(2)  # let balance reflect sells

    # 2. BUY new picks (those not already held)
    new_picks = [p for p in picks if p["symbol"] not in holdings]
    if not new_picks:
        log.info("No new picks to buy.")
    else:
        cash_after_sells, _ = equity_usdt(trade_exchange, holdings)
        # Reserve a tiny buffer for fees & rounding
        deployable = max(cash_after_sells * 0.995, 0)
        cash_per_pick = deployable / len(new_picks)
        log.info(f"Deploying ${deployable:.2f} across {len(new_picks)} new picks "
                 f"(${cash_per_pick:.2f} each)")

        for p in new_picks:
            sym = p["symbol"]
            if cash_per_pick < 6.0:  # Binance min notional is typically $5
                log.warning(f"  SKIP {sym}: ${cash_per_pick:.2f} below safe minimum")
                continue
            if args.dry_run:
                log.info(f"  [dry-run] would BUY {sym} for ${cash_per_pick:.2f}")
                holdings[sym] = {
                    "units": cash_per_pick / float(p["last_price"]),
                    "entry_price": float(p["last_price"]),
                    "entered_at": datetime.now(timezone.utc).isoformat(),
                }
            else:
                order = market_buy_quote(trade_exchange, sym, cash_per_pick)
                if order is not None:
                    units = float(order.get("amount") or 0)
                    avg = float(order.get("average") or p["last_price"])
                    holdings[sym] = {
                        "units": units, "entry_price": avg,
                        "entered_at": datetime.now(timezone.utc).isoformat(),
                    }

    if not args.dry_run:
        state["holdings"] = holdings
        state["last_rebalance"] = datetime.now(timezone.utc).isoformat()
        save_state(state)

        cash_after, equity_after = equity_usdt(trade_exchange, holdings)
        log_equity_snapshot(trade_exchange, holdings, cash_after, equity_after)
        log.info(f"Post-rebalance: cash=${cash_after:.2f}  equity=${equity_after:.2f}  "
                 f"holdings={list(holdings.keys())}")
        if equity_before > 0:
            log.info(f"Equity change this cycle: {(equity_after/equity_before - 1)*100:+.2f}%")
    else:
        log.info(f"[dry-run] Would hold: {list(holdings.keys())}  (state NOT persisted)")


def seconds_until_next_rebalance(state: dict, rebalance_bars: int,
                                 timeframe_seconds: int) -> float:
    interval = rebalance_bars * timeframe_seconds
    last = state.get("last_rebalance")
    if not last:
        return 0
    last_ts = datetime.fromisoformat(last).timestamp()
    next_ts = last_ts + interval
    return max(0, next_ts - datetime.now(timezone.utc).timestamp())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--universe", type=int, default=25)
    parser.add_argument("--timeframe", default="4h")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--momentum-lookback", type=int, default=60)
    parser.add_argument("--rebalance-bars", type=int, default=6,
                        help="Rebalance every N bars (6 on 4h = daily)")
    parser.add_argument("--min-volume", type=float, default=5_000_000)
    parser.add_argument("--show-picks", action="store_true",
                        help="Print picks and current state, then exit. No orders.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simulate the full rebalance, persist state, but place no orders.")
    parser.add_argument("--once", action="store_true",
                        help="Run a single rebalance cycle then exit.")
    args = parser.parse_args()

    data_exchange = get_data_exchange()
    trade_exchange = get_exchange()
    state = load_state()

    log.info(f"rotation_bot starting — mode={'LIVE' if is_live() else 'TESTNET'} "
             f"top_k={args.top_k} universe={args.universe} timeframe={args.timeframe} "
             f"momentum_lookback={args.momentum_lookback} rebalance_bars={args.rebalance_bars}")

    if is_live() and not args.dry_run and not args.show_picks:
        log.warning("LIVE MODE — orders will use REAL money. Ctrl+C in 5s to abort.")
        time.sleep(5)

    while True:
        try:
            rebalance(data_exchange, trade_exchange, state, args)
            if args.once or args.show_picks:
                break

            tf_seconds = data_exchange.parse_timeframe(args.timeframe)
            wait = seconds_until_next_rebalance(state, args.rebalance_bars, tf_seconds)
            if wait <= 0:
                wait = args.rebalance_bars * tf_seconds
            next_at = datetime.now(timezone.utc).timestamp() + wait
            log.info(f"Sleeping {wait:.0f}s until next rebalance "
                     f"(~{datetime.fromtimestamp(next_at, tz=timezone.utc).isoformat()})")
            time.sleep(wait)

        except KeyboardInterrupt:
            log.info("Stopped by user.")
            break
        except Exception as e:  # noqa: BLE001
            log.exception(f"Cycle failed: {e}; sleeping 60s")
            time.sleep(60)


if __name__ == "__main__":
    main()
