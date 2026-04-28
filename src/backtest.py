"""Backtest the EMA crossover with HTF trend filter + SL/TP/trailing exits.

Run: python -m src.backtest --symbol BTC/USDT --timeframe 5m --days 14
"""

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
    avg_win: float
    avg_loss: float
    max_drawdown_pct: float
    exit_reasons: dict
    trades: pd.DataFrame
    equity_curve: pd.Series


def _check_exit(price_low: float, price_high: float, entry_price: float, peak_price: float,
                stop_loss_pct: float, take_profit_pct: float, trailing_stop_pct: float,
                ema_sell: bool, close_price: float) -> tuple[float, str] | None:
    """Return (exit_price, reason) or None. Priority: SL > TP > trailing > EMA cross."""
    if stop_loss_pct:
        sl_price = entry_price * (1 - stop_loss_pct)
        if price_low <= sl_price:
            return sl_price, "STOP_LOSS"
    if take_profit_pct:
        tp_price = entry_price * (1 + take_profit_pct)
        if price_high >= tp_price:
            return tp_price, "TAKE_PROFIT"
    if trailing_stop_pct:
        ts_price = peak_price * (1 - trailing_stop_pct)
        if price_low <= ts_price and peak_price > entry_price:
            return ts_price, "TRAILING_STOP"
    if ema_sell:
        return close_price, "EMA_CROSS"
    return None


def run(df: pd.DataFrame, strategy: EmaCrossover | None = None,
        starting_cash: float = 10_000.0) -> BacktestResult:
    if strategy is None:
        strategy = EmaCrossover()
    sig = strategy.compute(df)

    cash = starting_cash
    position = 0.0
    entry_price = 0.0
    peak_price = 0.0
    trades = []
    equity = []

    for ts, row in sig.iterrows():
        close = row["close"]
        high = row["high"]
        low = row["low"]

        if position > 0:
            peak_price = max(peak_price, high)
            exit_info = _check_exit(
                price_low=low, price_high=high,
                entry_price=entry_price, peak_price=peak_price,
                stop_loss_pct=strategy.stop_loss_pct,
                take_profit_pct=strategy.take_profit_pct,
                trailing_stop_pct=strategy.trailing_stop_pct,
                ema_sell=(row["signal"] == SELL),
                close_price=close,
            )
            if exit_info is not None:
                exit_price, reason = exit_info
                cash = position * exit_price * (1 - FEE_RATE)
                pnl = (exit_price - entry_price) / entry_price
                trades.append({"timestamp": ts, "side": "SELL", "price": exit_price,
                               "pnl": pnl, "reason": reason})
                position = 0.0
                entry_price = 0.0
                peak_price = 0.0

        elif row["signal"] == BUY and position == 0:
            position = (cash * (1 - FEE_RATE)) / close
            entry_price = close
            peak_price = close
            cash = 0.0
            trades.append({"timestamp": ts, "side": "BUY", "price": close,
                           "pnl": None, "reason": "ENTRY"})

        equity.append(cash + position * close)

    equity_curve = pd.Series(equity, index=sig.index, name="equity")
    trades_df = pd.DataFrame(trades)

    closed = trades_df[trades_df["side"] == "SELL"] if len(trades_df) else trades_df
    wins = closed[closed["pnl"] > 0] if len(closed) else closed
    losses = closed[closed["pnl"] <= 0] if len(closed) else closed
    win_rate = len(wins) / len(closed) if len(closed) else 0.0
    avg_win = wins["pnl"].mean() if len(wins) else 0.0
    avg_loss = losses["pnl"].mean() if len(losses) else 0.0

    rolling_max = equity_curve.cummax()
    drawdown = (equity_curve - rolling_max) / rolling_max
    max_dd = drawdown.min() * 100 if len(drawdown) else 0.0

    exit_reasons = closed["reason"].value_counts().to_dict() if len(closed) else {}

    final_equity = equity_curve.iloc[-1]
    return BacktestResult(
        final_equity=final_equity,
        return_pct=(final_equity / starting_cash - 1) * 100,
        n_trades=len(closed),
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        max_drawdown_pct=max_dd,
        exit_reasons=exit_reasons,
        trades=trades_df,
        equity_curve=equity_curve,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--fast", type=int, default=9)
    parser.add_argument("--slow", type=int, default=21)
    parser.add_argument("--htf-minutes", type=int, default=60,
                        help="Higher timeframe in minutes for trend filter (0 to disable)")
    parser.add_argument("--htf-fast", type=int, default=50)
    parser.add_argument("--htf-slow", type=int, default=200)
    parser.add_argument("--sl", type=float, default=0.02, help="Stop-loss pct (0 to disable)")
    parser.add_argument("--tp", type=float, default=0.04, help="Take-profit pct (0 to disable)")
    parser.add_argument("--trail", type=float, default=0.0, help="Trailing-stop pct (0 to disable)")
    parser.add_argument("--cash", type=float, default=10_000.0)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    df = None if args.refresh else load(args.symbol, args.timeframe)
    if df is None or len(df) == 0:
        print(f"Fetching {args.days}d of {args.symbol} {args.timeframe} candles...")
        ex = get_exchange()
        df = fetch_history(ex, symbol=args.symbol, timeframe=args.timeframe, days=args.days)
        save(df, args.symbol, args.timeframe)
    print(f"Data: {len(df)} candles, {df.index[0]} → {df.index[-1]}")

    strategy = EmaCrossover(
        fast=args.fast, slow=args.slow,
        htf_minutes=args.htf_minutes if args.htf_minutes > 0 else None,
        htf_fast=args.htf_fast, htf_slow=args.htf_slow,
        stop_loss_pct=args.sl, take_profit_pct=args.tp, trailing_stop_pct=args.trail,
    )

    result = run(df, strategy=strategy, starting_cash=args.cash)

    print()
    print(f"Strategy:     EMA({args.fast}/{args.slow})  HTF({args.htf_minutes}m: {args.htf_fast}/{args.htf_slow})")
    print(f"Risk:         SL={args.sl*100:.1f}%  TP={args.tp*100:.1f}%  Trail={args.trail*100:.1f}%")
    print(f"Starting:     ${args.cash:,.2f}")
    print(f"Final equity: ${result.final_equity:,.2f}")
    print(f"Return:       {result.return_pct:+.2f}%")
    print(f"Max drawdown: {result.max_drawdown_pct:.2f}%")
    print(f"Trades:       {result.n_trades}")
    print(f"Win rate:     {result.win_rate * 100:.1f}%")
    print(f"Avg win/loss: {result.avg_win*100:+.2f}% / {result.avg_loss*100:+.2f}%")
    print(f"Exit reasons: {result.exit_reasons}")

    buy_hold = (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100
    print(f"Buy & hold:   {buy_hold:+.2f}%   (benchmark)")


if __name__ == "__main__":
    main()
