"""Stress-test the rotational momentum strategy.

Three tests:
  1. Robustness sweep — scan a grid of (top_k × momentum_lookback × rebalance) and
     see if good results cluster (real edge) or are isolated (overfit to one combo).
  2. Walk-forward — run the same config on every overlapping 90-day window in our
     1-year history. Reports distribution of returns + worst window.
  3. Fee sensitivity — run best config at 0.05% / 0.1% / 0.2% / 0.5% fees.

Run: python -m src.stress_test --top 25 --timeframe 4h --days 365
"""

from __future__ import annotations

import argparse
from copy import copy

import pandas as pd

from src.exchange import get_data_exchange
from src.rotation_backtest import _ensure_data, run as run_rotation
from src.scanner import get_universe
import src.rotation_backtest as rb


def slice_data(data: dict, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    out = {}
    for sym, df in data.items():
        s = df.loc[start:end]
        if len(s) > 50:
            out[sym] = s
    return out


def robustness_sweep(data: dict) -> pd.DataFrame:
    """Grid search over (top_k, momentum_lookback, rebalance_bars). One year of data."""
    rows = []
    for top_k in [1, 3, 5, 7, 10]:
        for mom in [10, 20, 40, 60]:
            for reb_label, reb_bars in [("daily", 6), ("weekly", 42), ("biweekly", 84)]:
                r = run_rotation(data, rebalance_bars=reb_bars, momentum_lookback=mom, top_k=top_k)
                rows.append({
                    "top_k": top_k, "lookback": mom, "rebalance": reb_label,
                    "return%": round(r["return_pct"], 1),
                    "max_dd%": round(r["max_drawdown_pct"], 1),
                    "switches": r["n_switches"],
                })
    return pd.DataFrame(rows)


def walk_forward(data: dict, top_k: int, momentum_lookback: int,
                 rebalance_bars: int, window_days: int = 90,
                 step_days: int = 30) -> pd.DataFrame:
    """Run the strategy on overlapping rolling windows."""
    closes = pd.concat([df["close"].rename(sym) for sym, df in data.items()], axis=1).sort_index()
    start = closes.index.min()
    end = closes.index.max()

    rows = []
    cursor = start
    while cursor + pd.Timedelta(days=window_days) <= end:
        wstart = cursor
        wend = cursor + pd.Timedelta(days=window_days)
        wdata = slice_data(data, wstart, wend)
        if len(wdata) < 5:
            cursor += pd.Timedelta(days=step_days)
            continue

        r = run_rotation(wdata, rebalance_bars=rebalance_bars,
                         momentum_lookback=momentum_lookback, top_k=top_k)

        # BTC benchmark for the same window
        btc = wdata.get("BTC/USDT")
        btc_ret = ((btc["close"].iloc[-1] / btc["close"].iloc[0]) - 1) * 100 if btc is not None else float("nan")

        rows.append({
            "window_start": wstart.date(),
            "window_end": wend.date(),
            "strategy_return%": round(r["return_pct"], 1),
            "btc_return%": round(btc_ret, 1),
            "edge%": round(r["return_pct"] - btc_ret, 1),
            "max_dd%": round(r["max_drawdown_pct"], 1),
            "switches": r["n_switches"],
        })
        cursor += pd.Timedelta(days=step_days)
    return pd.DataFrame(rows)


def fee_sensitivity(data: dict, top_k: int, momentum_lookback: int,
                    rebalance_bars: int) -> pd.DataFrame:
    """Run the same backtest with different fee assumptions."""
    rows = []
    original_fee = rb.FEE_RATE
    for fee in [0.0005, 0.001, 0.002, 0.0035, 0.005]:
        rb.FEE_RATE = fee
        r = run_rotation(data, rebalance_bars=rebalance_bars,
                         momentum_lookback=momentum_lookback, top_k=top_k)
        rows.append({
            "fee_per_trade%": fee * 100,
            "return%": round(r["return_pct"], 1),
            "max_dd%": round(r["max_drawdown_pct"], 1),
            "n_trades": r["n_trades"],
            "fee_drag%": round(r["n_trades"] * fee * 100, 1),
        })
    rb.FEE_RATE = original_fee
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--timeframe", default="4h")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--window-days", type=int, default=90,
                        help="Walk-forward window size")
    parser.add_argument("--step-days", type=int, default=30,
                        help="Walk-forward step size")
    args = parser.parse_args()

    ex = get_data_exchange()
    universe = get_universe(ex, top_n=args.top, min_volume_usd=5_000_000)
    print(f"Universe ({len(universe)} coins)")
    data = _ensure_data(ex, universe, args.timeframe, args.days)
    print(f"Data: {len(data)} coins\n")

    # ------------------------------------------------------------------
    # Test 1: Robustness sweep
    # ------------------------------------------------------------------
    print("=" * 80)
    print("TEST 1: Robustness sweep — (top_k × momentum_lookback × rebalance)")
    print("=" * 80)
    sweep = robustness_sweep(data)
    print(sweep.to_string(index=False))
    print()
    print("Top 10 configurations by return:")
    print(sweep.sort_values("return%", ascending=False).head(10).to_string(index=False))
    print()
    print("Top 10 by risk-adjusted return (return / |max_dd|):")
    sweep["ratio"] = (sweep["return%"] / sweep["max_dd%"].abs().replace(0, 1)).round(2)
    print(sweep.sort_values("ratio", ascending=False).head(10).to_string(index=False))
    sweep = sweep.drop(columns=["ratio"])

    # Pick best config for downstream tests (best risk-adjusted)
    sweep["ratio"] = sweep["return%"] / sweep["max_dd%"].abs().replace(0, 1)
    best = sweep.sort_values("ratio", ascending=False).iloc[0]
    best_top_k = int(best["top_k"])
    best_mom = int(best["lookback"])
    best_reb_label = best["rebalance"]
    best_reb = {"daily": 6, "weekly": 42, "biweekly": 84}[best_reb_label]
    print()
    print(f">>> Picked best risk-adjusted config: top_k={best_top_k}, "
          f"lookback={best_mom}, rebalance={best_reb_label}")

    # ------------------------------------------------------------------
    # Test 2: Walk-forward
    # ------------------------------------------------------------------
    print()
    print("=" * 80)
    print(f"TEST 2: Walk-forward (rolling {args.window_days}d windows, step {args.step_days}d)")
    print("=" * 80)
    wf = walk_forward(data, top_k=best_top_k, momentum_lookback=best_mom,
                      rebalance_bars=best_reb,
                      window_days=args.window_days, step_days=args.step_days)
    print(wf.to_string(index=False))
    print()
    print("Distribution:")
    print(f"  Strategy mean return:  {wf['strategy_return%'].mean():+.1f}%")
    print(f"  Strategy median:       {wf['strategy_return%'].median():+.1f}%")
    print(f"  Strategy worst window: {wf['strategy_return%'].min():+.1f}%")
    print(f"  Strategy best window:  {wf['strategy_return%'].max():+.1f}%")
    print(f"  BTC mean return:       {wf['btc_return%'].mean():+.1f}%")
    print(f"  Edge mean:             {wf['edge%'].mean():+.1f}%")
    print(f"  % windows beating BTC: {(wf['edge%'] > 0).mean() * 100:.0f}%")
    print(f"  % windows positive:    {(wf['strategy_return%'] > 0).mean() * 100:.0f}%")
    print(f"  Worst max drawdown:    {wf['max_dd%'].min():.1f}%")

    # ------------------------------------------------------------------
    # Test 3: Fee sensitivity
    # ------------------------------------------------------------------
    print()
    print("=" * 80)
    print("TEST 3: Fee sensitivity (full 1y, best config)")
    print("=" * 80)
    fees = fee_sensitivity(data, top_k=best_top_k, momentum_lookback=best_mom,
                           rebalance_bars=best_reb)
    print(fees.to_string(index=False))


if __name__ == "__main__":
    main()
