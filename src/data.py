"""Fetch and cache OHLCV candles from Binance."""

from pathlib import Path

import ccxt
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def fetch_ohlcv(
    exchange: ccxt.Exchange,
    symbol: str = "BTC/USDT",
    timeframe: str = "1m",
    limit: int = 1000,
    since: int | None = None,
) -> pd.DataFrame:
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit, since=since)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df.set_index("timestamp")


def fetch_history(
    exchange: ccxt.Exchange,
    symbol: str = "BTC/USDT",
    timeframe: str = "1m",
    days: int = 7,
) -> pd.DataFrame:
    """Page backward through the API to assemble a multi-day history."""
    ms_per_candle = exchange.parse_timeframe(timeframe) * 1000
    end = exchange.milliseconds()
    start = end - days * 24 * 60 * 60 * 1000

    all_rows = []
    cursor = start
    while cursor < end:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=1000)
        if not batch:
            break
        all_rows.extend(batch)
        cursor = batch[-1][0] + ms_per_candle
        if len(batch) < 1000:
            break

    df = pd.DataFrame(all_rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.drop_duplicates("timestamp").set_index("timestamp").sort_index()
    return df


def cache_path(symbol: str, timeframe: str) -> Path:
    safe = symbol.replace("/", "-")
    return DATA_DIR / f"{safe}_{timeframe}.parquet"


def save(df: pd.DataFrame, symbol: str, timeframe: str) -> Path:
    path = cache_path(symbol, timeframe)
    df.to_parquet(path)
    return path


def load(symbol: str, timeframe: str) -> pd.DataFrame | None:
    path = cache_path(symbol, timeframe)
    if not path.exists():
        return None
    return pd.read_parquet(path)
