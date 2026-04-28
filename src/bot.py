"""Live trading loop with HTF trend filter + SL/TP/trailing exits.
State is persisted to data/bot_state.json so the bot survives restarts mid-position.

Run: python -m src.bot --symbol BTC/USDT --timeframe 5m --quote-size 100 --dry-run
"""

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from src.data import fetch_ohlcv
from src.exchange import get_exchange, is_live
from src.strategy import BUY, HOLD, SELL, EmaCrossover

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("bot")

STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "bot_state.json"


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def seconds_until_next_candle(timeframe_seconds: int) -> float:
    now = datetime.now(timezone.utc).timestamp()
    return timeframe_seconds - (now % timeframe_seconds) + 2


def get_position(exchange, base: str) -> float:
    balance = exchange.fetch_balance()
    return float(balance.get(base, {}).get("free", 0.0))


def place_market_buy(exchange, symbol: str, quote_amount: float) -> dict:
    log.info(f"PLACING BUY: spend ~{quote_amount} quote on {symbol}")
    ticker = exchange.fetch_ticker(symbol)
    price = ticker["last"]
    base_amount = float(exchange.amount_to_precision(symbol, quote_amount / price))
    market = exchange.market(symbol)
    min_amount = (market.get("limits", {}).get("amount", {}) or {}).get("min")
    if min_amount and base_amount < min_amount:
        log.warning(f"Computed size {base_amount} below min {min_amount} — skipping")
        return {}
    order = exchange.create_market_buy_order(symbol, base_amount)
    fill = order.get("average") or price
    log.info(f"BUY filled: {order.get('amount')} @ ~{fill}")
    return order


def place_market_sell(exchange, symbol: str, base_amount: float, reason: str) -> dict:
    log.info(f"PLACING SELL ({reason}): {base_amount} of {symbol}")
    base_amount = float(exchange.amount_to_precision(symbol, base_amount))
    order = exchange.create_market_sell_order(symbol, base_amount)
    log.info(f"SELL filled: {order.get('amount')} @ ~{order.get('average')}")
    return order


def check_exit_reason(price: float, entry: float, peak: float,
                      sl: float, tp: float, trail: float, ema_sell: bool) -> str | None:
    """Check exits in priority order. Returns reason string or None."""
    if sl and price <= entry * (1 - sl):
        return "STOP_LOSS"
    if tp and price >= entry * (1 + tp):
        return "TAKE_PROFIT"
    if trail and peak > entry and price <= peak * (1 - trail):
        return "TRAILING_STOP"
    if ema_sell:
        return "EMA_CROSS"
    return None


def run(symbol: str, timeframe: str, strategy: EmaCrossover,
        quote_size: float, dry_run: bool) -> None:
    exchange = get_exchange()
    exchange.load_markets()
    if symbol not in exchange.markets:
        raise SystemExit(f"Symbol {symbol} not available on exchange.")

    base = exchange.market(symbol)["base"]
    tf_seconds = exchange.parse_timeframe(timeframe)
    min_bars = max(strategy.slow, strategy.htf_slow if strategy.htf_minutes else 0) + 5

    state = load_state()
    sym_state = state.get(symbol, {})

    mode = "LIVE (REAL FUNDS)" if is_live() else "TESTNET"
    log.info(f"Starting bot — {mode} — {symbol} {timeframe} EMA({strategy.fast}/{strategy.slow})"
             f" HTF({strategy.htf_minutes}m) SL={strategy.stop_loss_pct*100:.1f}%"
             f" TP={strategy.take_profit_pct*100:.1f}% Trail={strategy.trailing_stop_pct*100:.1f}%"
             f" quote_size=${quote_size} dry_run={dry_run}")

    if is_live() and not dry_run:
        log.warning("LIVE MODE — orders will use REAL money. Ctrl+C in 5s to abort.")
        time.sleep(5)

    position_on_exchange = get_position(exchange, base)
    if position_on_exchange > 0 and not sym_state.get("entry_price"):
        log.warning(f"Found {position_on_exchange} {base} on exchange but no saved entry price."
                    f" Using current price as entry (SL/TP will be approximate).")

    while True:
        try:
            df = fetch_ohlcv(exchange, symbol=symbol, timeframe=timeframe, limit=max(300, min_bars))
            if len(df) < min_bars:
                log.warning(f"Only {len(df)} candles, need {min_bars}; sleeping")
                time.sleep(tf_seconds)
                continue

            closed = df.iloc[:-1]
            sig_df = strategy.compute(closed)
            signal = int(sig_df["signal"].iloc[-1])
            htf_up = bool(sig_df["htf_uptrend"].iloc[-1])
            last_price = float(closed["close"].iloc[-1])
            position = get_position(exchange, base)

            sig_name = {BUY: "BUY", SELL: "SELL", HOLD: "HOLD"}[signal]
            log.info(f"signal={sig_name} htf_up={htf_up} price={last_price:.2f} {base}_balance={position:.6f}")

            sym_state = state.get(symbol, {})

            if position > 0:
                entry = sym_state.get("entry_price", last_price)
                peak = max(sym_state.get("peak_price", entry), last_price)
                sym_state["peak_price"] = peak
                state[symbol] = sym_state
                save_state(state)

                exit_reason = check_exit_reason(
                    price=last_price, entry=entry, peak=peak,
                    sl=strategy.stop_loss_pct, tp=strategy.take_profit_pct,
                    trail=strategy.trailing_stop_pct, ema_sell=(signal == SELL),
                )
                if exit_reason:
                    pnl_pct = (last_price - entry) / entry * 100
                    log.info(f"EXIT triggered: {exit_reason} (entry={entry:.2f} now={last_price:.2f} pnl={pnl_pct:+.2f}%)")
                    if not dry_run:
                        place_market_sell(exchange, symbol, position, exit_reason)
                        state.pop(symbol, None)
                        save_state(state)

            elif position == 0 and signal == BUY:
                log.info(f"ENTRY signal at {last_price:.2f}")
                if not dry_run:
                    order = place_market_buy(exchange, symbol, quote_size)
                    if order:
                        fill_price = float(order.get("average") or last_price)
                        state[symbol] = {
                            "entry_price": fill_price,
                            "peak_price": fill_price,
                            "entered_at": datetime.now(timezone.utc).isoformat(),
                        }
                        save_state(state)

            wait = seconds_until_next_candle(tf_seconds)
            log.debug(f"Sleeping {wait:.0f}s until next candle")
            time.sleep(wait)

        except KeyboardInterrupt:
            log.info("Stopped by user.")
            break
        except Exception as e:  # noqa: BLE001
            log.exception(f"Loop error: {e}; sleeping 30s")
            time.sleep(30)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--fast", type=int, default=9)
    parser.add_argument("--slow", type=int, default=21)
    parser.add_argument("--htf-minutes", type=int, default=60)
    parser.add_argument("--htf-fast", type=int, default=50)
    parser.add_argument("--htf-slow", type=int, default=200)
    parser.add_argument("--sl", type=float, default=0.02)
    parser.add_argument("--tp", type=float, default=0.04)
    parser.add_argument("--trail", type=float, default=0.0)
    parser.add_argument("--quote-size", type=float, default=100.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    strategy = EmaCrossover(
        fast=args.fast, slow=args.slow,
        htf_minutes=args.htf_minutes if args.htf_minutes > 0 else None,
        htf_fast=args.htf_fast, htf_slow=args.htf_slow,
        stop_loss_pct=args.sl, take_profit_pct=args.tp, trailing_stop_pct=args.trail,
    )

    run(symbol=args.symbol, timeframe=args.timeframe, strategy=strategy,
        quote_size=args.quote_size, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
