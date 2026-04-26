"""Live trading loop. Defaults to testnet — set BINANCE_LIVE=true in .env to use real funds.

Run: python -m src.bot --symbol BTC/USDT --timeframe 1m --quote-size 100
"""

import argparse
import logging
import time
from datetime import datetime, timezone

from src.data import fetch_ohlcv
from src.exchange import get_exchange, is_live
from src.strategy import BUY, HOLD, SELL, EmaCrossover

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("bot")


def seconds_until_next_candle(timeframe_seconds: int) -> float:
    now = datetime.now(timezone.utc).timestamp()
    return timeframe_seconds - (now % timeframe_seconds) + 2  # +2s buffer for candle to close


def get_position(exchange, base: str) -> float:
    balance = exchange.fetch_balance()
    return float(balance.get(base, {}).get("free", 0.0))


def place_market_buy(exchange, symbol: str, quote_amount: float) -> dict:
    log.info(f"PLACING BUY: spend ~{quote_amount} quote on {symbol}")
    ticker = exchange.fetch_ticker(symbol)
    price = ticker["last"]
    base_amount = quote_amount / price
    market = exchange.market(symbol)
    base_amount = float(exchange.amount_to_precision(symbol, base_amount))
    min_amount = (market.get("limits", {}).get("amount", {}) or {}).get("min")
    if min_amount and base_amount < min_amount:
        log.warning(f"Computed size {base_amount} below min {min_amount} — skipping")
        return {}
    order = exchange.create_market_buy_order(symbol, base_amount)
    log.info(f"BUY filled: {order.get('amount')} @ ~{order.get('average') or price}")
    return order


def place_market_sell(exchange, symbol: str, base_amount: float) -> dict:
    log.info(f"PLACING SELL: {base_amount} of {symbol}")
    base_amount = float(exchange.amount_to_precision(symbol, base_amount))
    order = exchange.create_market_sell_order(symbol, base_amount)
    log.info(f"SELL filled: {order.get('amount')} @ ~{order.get('average')}")
    return order


def run(symbol: str, timeframe: str, fast: int, slow: int, quote_size: float, dry_run: bool) -> None:
    exchange = get_exchange()
    exchange.load_markets()
    if symbol not in exchange.markets:
        raise SystemExit(f"Symbol {symbol} not available on exchange.")

    base = exchange.market(symbol)["base"]
    strat = EmaCrossover(fast=fast, slow=slow)
    tf_seconds = exchange.parse_timeframe(timeframe)
    min_bars = slow + 5

    mode = "LIVE (REAL FUNDS)" if is_live() else "TESTNET"
    log.info(f"Starting bot — {mode} — {symbol} {timeframe} EMA({fast}/{slow}) quote_size=${quote_size} dry_run={dry_run}")

    if is_live() and not dry_run:
        log.warning("LIVE MODE — orders will use REAL money. Ctrl+C in 5s to abort.")
        time.sleep(5)

    while True:
        try:
            df = fetch_ohlcv(exchange, symbol=symbol, timeframe=timeframe, limit=max(200, min_bars))
            if len(df) < min_bars:
                log.warning(f"Only {len(df)} candles, need {min_bars}; sleeping")
                time.sleep(tf_seconds)
                continue

            # Use the last *closed* candle (drop the in-progress one)
            closed = df.iloc[:-1]
            signal = strat.latest_signal(closed)
            last_price = closed["close"].iloc[-1]
            position = get_position(exchange, base)

            sig_name = {BUY: "BUY", SELL: "SELL", HOLD: "HOLD"}[signal]
            log.info(f"signal={sig_name} price={last_price:.2f} {base}_balance={position:.6f}")

            if dry_run:
                pass
            elif signal == BUY and position == 0:
                place_market_buy(exchange, symbol, quote_size)
            elif signal == SELL and position > 0:
                place_market_sell(exchange, symbol, position)

            wait = seconds_until_next_candle(tf_seconds)
            log.debug(f"Sleeping {wait:.0f}s until next candle close")
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
    parser.add_argument("--timeframe", default="1m")
    parser.add_argument("--fast", type=int, default=9)
    parser.add_argument("--slow", type=int, default=21)
    parser.add_argument("--quote-size", type=float, default=100.0,
                        help="Quote currency (USDT) to spend per BUY")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print signals but place no orders")
    args = parser.parse_args()

    run(
        symbol=args.symbol,
        timeframe=args.timeframe,
        fast=args.fast,
        slow=args.slow,
        quote_size=args.quote_size,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
