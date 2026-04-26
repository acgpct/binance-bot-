"""Backtest the EMA crossover on historical data. Run: python -m src.backtest"""

import argparse
from dataclasses import dataclass

import pandas as pd

from src.data import fetch_history, load, save
from src.exchange import get_exchange
from src.strategy import BUY, SELL, EmaCrossover

FEE_RATE = 0.001  # Binance Spot: 0.1% per trade


@dataclass
class BacktestResult:
    final_equity: float
    return_pct: float
    n_trades: int
    win_rate: float
    trades: pd.DataFrame
    equity_curve: pd.Series


def run(df: pd.DataFrame, fast: int = 9, slow: int = 21, starting_cash: float = 10_000.0) -> BacktestResult:
    strat = EmaCrossover(fast=fast, slow=slow)
    sig = strat.compute(df)

    cash = starting_cash
    position = 0.0  # base asset units held
    entry_price = 0.0
    trades = []
    equity = []

    for ts, row in sig.iterrows():
        price = row["close"]

        if row["signal"] == BUY and position == 0:
            position = (cash * (1 - FEE_RATE)) / price
            entry_price = price
            cash = 0.0
            trades.append({"timestamp": ts, "side": "BUY", "price": price, "pnl": None})
        elif row["signal"] == SELL and position > 0:
            cash = position * price * (1 - FEE_RATE)
            pnl = (price - entry_price) / entry_price
            trades.append({"timestamp": ts, "side": "SELL", "price": price, "pnl": pnl})
            position = 0.0

        equity.append(cash + position * price)

    equity_curve = pd.Series(equity, index=sig.index, name="equity")
    trades_df = pd.DataFrame(trades)

    closed = trades_df[trades_df["side"] == "SELL"]
    win_rate = (closed["pnl"] > 0).mean() if len(closed) else 0.0

    final_equity = equity_curve.iloc[-1]
    return BacktestResult(
        final_equity=final_equity,
        return_pct=(final_equity / starting_cash - 1) * 100,
        n_trades=len(closed),
        win_rate=win_rate,
        trades=trades_df,
        equity_curve=equity_curve,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--fast", type=int, default=9)
    parser.add_argument("--slow", type=int, default=21)
    parser.add_argument("--cash", type=float, default=10_000.0)
    parser.add_argument("--refresh", action="store_true", help="Refetch data instead of using cache")
    args = parser.parse_args()

    df = None if args.refresh else load(args.symbol, args.timeframe)
    if df is None or len(df) == 0:
        print(f"Fetching {args.days}d of {args.symbol} {args.timeframe} candles...")
        ex = get_exchange()
        df = fetch_history(ex, symbol=args.symbol, timeframe=args.timeframe, days=args.days)
        save(df, args.symbol, args.timeframe)
        print(f"Cached {len(df)} candles to {args.symbol.replace('/', '-')}_{args.timeframe}.parquet")
    else:
        print(f"Loaded {len(df)} cached candles for {args.symbol} {args.timeframe}")

    result = run(df, fast=args.fast, slow=args.slow, starting_cash=args.cash)

    print()
    print(f"Symbol:       {args.symbol} {args.timeframe} ({args.days}d)")
    print(f"Strategy:     EMA({args.fast})/EMA({args.slow})")
    print(f"Starting:     ${args.cash:,.2f}")
    print(f"Final equity: ${result.final_equity:,.2f}")
    print(f"Return:       {result.return_pct:+.2f}%")
    print(f"Trades:       {result.n_trades}")
    print(f"Win rate:     {result.win_rate * 100:.1f}%")

    buy_hold = (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100
    print(f"Buy & hold:   {buy_hold:+.2f}%   (benchmark)")


if __name__ == "__main__":
    main()
