"""Scan Binance USDT pairs and rank them by trend health + momentum.

The scanner answers: "which coins are in tradeable shape RIGHT NOW?"
- Liquidity filter: 24h quote volume above a threshold
- Trend filter: price above long EMA AND short EMA above long EMA
- Ranking: recent % return (momentum)

Run: python -m src.scanner --top 20 --timeframe 4h
"""

from __future__ import annotations

import argparse
import time

import ccxt
import pandas as pd

from src.data import fetch_history
from src.exchange import get_data_exchange

# Skip Binance's leveraged tokens, fiat-stables, and other things we don't want to scan
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")
STABLE_BASES = {"USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDP", "EUR", "GBP", "TRY",
                "AEUR", "EURI", "USD1", "USDE", "BFUSD", "PAX", "RLUSD", "XAUT"}


def get_universe(exchange: ccxt.Exchange, quote: str = "USDT", top_n: int = 30,
                 min_volume_usd: float = 5_000_000) -> list[dict]:
    """Top N {quote} pairs by 24h quote volume on Binance Spot."""
    tickers = exchange.fetch_tickers()
    pairs = []
    for sym, t in tickers.items():
        if not sym.endswith(f"/{quote}"):
            continue
        base = sym.split("/")[0]
        if base in STABLE_BASES:
            continue
        if any(base.endswith(s) for s in LEVERAGED_SUFFIXES):
            continue
        vol = t.get("quoteVolume") or 0
        if vol < min_volume_usd:
            continue
        pairs.append({"symbol": sym, "quote_volume": float(vol),
                      "last": float(t.get("last") or 0),
                      "change_24h_pct": float(t.get("percentage") or 0)})
    return sorted(pairs, key=lambda x: x["quote_volume"], reverse=True)[:top_n]


def score(df: pd.DataFrame, momentum_lookback: int = 20,
          ema_short: int = 20, ema_long: int = 50) -> dict | None:
    """Per-coin scoring on a single OHLCV frame."""
    if len(df) < max(ema_long, momentum_lookback) + 5:
        return None

    close = df["close"]
    high = df["high"]
    low = df["low"]

    es = close.ewm(span=ema_short, adjust=False).mean()
    el = close.ewm(span=ema_long, adjust=False).mean()

    # ATR(14) as % of price = volatility proxy
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().iloc[-1]
    atr_pct = float(atr / close.iloc[-1] * 100) if close.iloc[-1] else 0.0

    in_uptrend = bool(es.iloc[-1] > el.iloc[-1] and close.iloc[-1] > el.iloc[-1])
    above_long_pct = float((close.iloc[-1] / el.iloc[-1] - 1) * 100)
    momentum_pct = float((close.iloc[-1] / close.iloc[-momentum_lookback] - 1) * 100)

    return {
        "in_uptrend": in_uptrend,
        "momentum_pct": momentum_pct,
        "above_long_pct": above_long_pct,
        "atr_pct": atr_pct,
        "last_price": float(close.iloc[-1]),
    }


def scan(exchange: ccxt.Exchange, universe: list[dict], timeframe: str = "4h",
         days: int = 14, momentum_lookback: int = 20, ema_short: int = 20,
         ema_long: int = 50, throttle_ms: int = 50) -> pd.DataFrame:
    """Score every coin in the universe; return uptrending coins ranked by momentum."""
    rows = []
    for entry in universe:
        sym = entry["symbol"]
        try:
            df = fetch_history(exchange, sym, timeframe, days=days)
            s = score(df, momentum_lookback=momentum_lookback,
                      ema_short=ema_short, ema_long=ema_long)
            if s is None:
                continue
            s["symbol"] = sym
            s["quote_volume_m"] = entry["quote_volume"] / 1_000_000
            s["change_24h_pct"] = entry["change_24h_pct"]
            rows.append(s)
            time.sleep(throttle_ms / 1000)
        except Exception as e:  # noqa: BLE001
            print(f"  [skip {sym}: {e}]")
            continue

    df = pd.DataFrame(rows)
    if len(df) == 0:
        return df

    cols = ["symbol", "in_uptrend", "momentum_pct", "above_long_pct", "atr_pct",
            "change_24h_pct", "quote_volume_m", "last_price"]
    df = df[cols]
    df = df[df["in_uptrend"]].sort_values("momentum_pct", ascending=False).reset_index(drop=True)
    return df


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=20, help="Universe size (top N by volume)")
    parser.add_argument("--timeframe", default="4h")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--momentum-lookback", type=int, default=20,
                        help="Bars used for momentum % return")
    parser.add_argument("--ema-short", type=int, default=20)
    parser.add_argument("--ema-long", type=int, default=50)
    parser.add_argument("--min-volume", type=float, default=5_000_000,
                        help="Minimum 24h USDT volume")
    args = parser.parse_args()

    ex = get_data_exchange()
    print(f"Fetching universe: top {args.top} USDT pairs by volume...")
    universe = get_universe(ex, top_n=args.top, min_volume_usd=args.min_volume)
    print(f"Universe ({len(universe)}): {', '.join(p['symbol'] for p in universe[:10])}"
          f"{'...' if len(universe) > 10 else ''}")
    print()
    print(f"Scanning on {args.timeframe} bars ({args.days}d, momentum_lookback={args.momentum_lookback})...")
    print()

    df = scan(ex, universe, timeframe=args.timeframe, days=args.days,
              momentum_lookback=args.momentum_lookback,
              ema_short=args.ema_short, ema_long=args.ema_long)

    if len(df) == 0:
        print("No coins passed the trend filter.")
        return

    pretty = df.copy()
    pretty["momentum_pct"] = pretty["momentum_pct"].round(2)
    pretty["above_long_pct"] = pretty["above_long_pct"].round(2)
    pretty["atr_pct"] = pretty["atr_pct"].round(2)
    pretty["change_24h_pct"] = pretty["change_24h_pct"].round(2)
    pretty["quote_volume_m"] = pretty["quote_volume_m"].round(0)
    pretty["last_price"] = pretty["last_price"].round(4)
    print(f"Top picks ({len(df)} coins passing trend filter):")
    print(pretty.to_string(index=False))


if __name__ == "__main__":
    main()
