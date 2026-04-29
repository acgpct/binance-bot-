"""Rotational momentum backtest: at each rebalance bar, pick the top-ranked coin
from the universe and hold it. Switch when a different coin tops the ranking.

Run:  python -m src.rotation_backtest --top 20 --timeframe 4h --days 60 --rebalance-bars 6
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.data import fetch_history, load, save
from src.exchange import get_data_exchange
from src.scanner import get_universe, score

FEE_RATE = 0.001  # 0.1% per trade
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _ensure_data(exchange, universe: list[dict], timeframe: str, days: int) -> dict[str, pd.DataFrame]:
    """Fetch & cache OHLCV for every coin in the universe."""
    out = {}
    for entry in universe:
        sym = entry["symbol"]
        df = load(sym, timeframe)
        if df is None or len(df) < 100 or (df.index[-1] - df.index[0]).days < days * 0.7:
            try:
                df = fetch_history(exchange, sym, timeframe, days=days)
                save(df, sym, timeframe)
            except Exception as e:  # noqa: BLE001
                print(f"  [skip {sym}: {e}]")
                continue
        if df is not None and len(df) > 50:
            out[sym] = df
    return out


def _aligned_close_panel(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Single DataFrame: rows = timestamps, cols = symbols, values = close price (forward-filled)."""
    closes = pd.DataFrame({sym: df["close"] for sym, df in data.items()})
    return closes.sort_index().ffill()


def _trailing_usd_volume(df: pd.DataFrame, window_bars: int) -> pd.Series:
    """Trailing USD volume over `window_bars` (sum of base_volume × close)."""
    return (df["volume"] * df["close"]).rolling(window_bars, min_periods=1).sum()


def _btc_regime(data: dict[str, pd.DataFrame], ema_short: int = 50,
                ema_long: int = 200) -> pd.Series | None:
    """Return a bool Series aligned to BTC's index: True when BTC is in a
    bull regime (short EMA > long EMA). Used as a 'risk-on' filter.

    Logic: at each bar, check BTC's trend. If bearish, the strategy sits in
    cash. The signal is shifted by 1 bar to avoid lookahead bias (decisions
    use the previous bar's confirmed regime).
    """
    btc = data.get("BTC/USDT")
    if btc is None or len(btc) < ema_long + 5:
        return None
    close = btc["close"]
    short = close.ewm(span=ema_short, adjust=False).mean()
    long_ = close.ewm(span=ema_long, adjust=False).mean()
    regime = (short > long_).shift(1).fillna(False)
    return regime


def run(data: dict[str, pd.DataFrame], rebalance_bars: int = 6,
        momentum_lookback: int = 20, ema_short: int = 20, ema_long: int = 50,
        top_k: int = 1, starting_cash: float = 10_000.0,
        skip_top_n: int = 0, volatility_weighted: bool = False,
        trailing_stop_pct: float = 0.0,
        universe_size: int | None = None,
        volume_window_bars: int = 180,
        regime_filter: bool = False,
        regime_short: int = 50, regime_long: int = 200,
        regime_bear_alloc: float = 0.0) -> dict:
    """Rotational momentum simulation.

    skip_top_n           — skip the N most-pumped picks (avoids buying the very top)
    volatility_weighted  — size positions inversely to ATR% (less in volatile coins)
    trailing_stop_pct    — between rebalances, sell any coin that drops this % from
                           its post-entry high. The freed cash sits idle until the
                           next rebalance.
    universe_size        — if set, dynamically pick the top-N coins by trailing USD
                           volume at each rebalance (point-in-time universe; reduces
                           survivorship bias). If None, all coins in `data` are
                           eligible at every rebalance (the biased / legacy mode).
    volume_window_bars   — bars used for trailing volume ranking (default 180 ≈ 30d on 4h).
    """
    closes = _aligned_close_panel(data)
    if len(closes) == 0:
        raise ValueError("No data to backtest.")

    # Pre-compute trailing USD volume per coin (vectorised, cheaper than per-bar)
    trailing_vol = pd.DataFrame({
        sym: _trailing_usd_volume(df, volume_window_bars)
        for sym, df in data.items()
    }).reindex(closes.index).ffill()

    # Pre-compute BTC bull/bear regime if the filter is enabled
    btc_regime: pd.Series | None = None
    if regime_filter:
        btc_regime = _btc_regime(data, ema_short=regime_short, ema_long=regime_long)
        if btc_regime is None:
            raise ValueError("regime_filter=True requires BTC/USDT in `data`")
        btc_regime = btc_regime.reindex(closes.index, method="ffill").fillna(False).astype(bool)

    cash = starting_cash
    # holdings: sym -> {units, peak_price}
    holdings: dict[str, dict] = {}
    equity_curve = []
    trades = []
    last_picks: list[str] = []

    warmup = max(ema_long, momentum_lookback) + 5

    for i, ts in enumerate(closes.index):
        prices = closes.loc[ts]

        # Trailing stop check on every bar (not just rebalance bars)
        if trailing_stop_pct and holdings:
            for sym in list(holdings.keys()):
                px = float(prices.get(sym, 0) or 0)
                if px <= 0:
                    continue
                holdings[sym]["peak_price"] = max(holdings[sym]["peak_price"], px)
                if px <= holdings[sym]["peak_price"] * (1 - trailing_stop_pct):
                    proceeds = holdings[sym]["units"] * px * (1 - FEE_RATE)
                    cash += proceeds
                    trades.append({"timestamp": ts, "side": "SELL", "symbol": sym,
                                   "price": px, "units": holdings[sym]["units"],
                                   "reason": "TRAILING_STOP"})
                    del holdings[sym]

        position_value = sum(h["units"] * float(prices.get(sym, 0) or 0)
                             for sym, h in holdings.items())
        equity_curve.append(cash + position_value)

        if i < warmup:
            continue
        if (i - warmup) % rebalance_bars != 0:
            continue

        # Regime filter: if BTC is in a bear regime, scale allocation by
        # `regime_bear_alloc` (0.0 = full exit, 0.5 = soft 50%, 1.0 = no filter).
        regime_alloc = 1.0
        if regime_filter and btc_regime is not None and not bool(btc_regime.loc[ts]):
            regime_alloc = regime_bear_alloc
            if regime_alloc <= 0:
                # Hard exit: sell everything, sit in cash
                for sym in list(holdings.keys()):
                    px = float(prices.get(sym, 0) or 0)
                    if px > 0:
                        proceeds = holdings[sym]["units"] * px * (1 - FEE_RATE)
                        cash += proceeds
                        trades.append({"timestamp": ts, "side": "SELL", "symbol": sym,
                                       "price": px, "units": holdings[sym]["units"],
                                       "reason": "REGIME_BEAR"})
                    del holdings[sym]
                last_picks = []
                continue

        # Determine the eligible universe at this rebalance
        if universe_size:
            # Bias-aware: rank by trailing USD volume AT THIS POINT IN TIME
            vol_at_ts = trailing_vol.loc[ts].dropna()
            vol_at_ts = vol_at_ts[vol_at_ts > 0]
            eligible_symbols = list(vol_at_ts.nlargest(universe_size).index)
        else:
            eligible_symbols = list(data.keys())

        # Score eligible coins using ONLY data available up to and including ts
        scores = []
        for sym in eligible_symbols:
            df = data.get(sym)
            if df is None:
                continue
            slice_df = df.loc[:ts]
            if len(slice_df) < ema_long + 5:
                continue
            s = score(slice_df, momentum_lookback=momentum_lookback,
                      ema_short=ema_short, ema_long=ema_long)
            if s is None or not s["in_uptrend"]:
                continue
            s["symbol"] = sym
            s["price"] = float(prices.get(sym, 0) or 0)
            if s["price"] > 0:
                scores.append(s)

        scores.sort(key=lambda x: x["momentum_pct"], reverse=True)
        # Skip the most-pumped (most extended) coins, then take the next top_k
        eligible = scores[skip_top_n : skip_top_n + top_k]
        pick_symbols = [s["symbol"] for s in eligible]

        # Sell holdings no longer in picks
        for sym in list(holdings.keys()):
            if sym not in pick_symbols:
                px = float(prices.get(sym, 0) or 0)
                if px > 0:
                    proceeds = holdings[sym]["units"] * px * (1 - FEE_RATE)
                    cash += proceeds
                    trades.append({"timestamp": ts, "side": "SELL", "symbol": sym,
                                   "price": px, "units": holdings[sym]["units"],
                                   "reason": "ROTATION"})
                del holdings[sym]

        # Buy any pick we don't already hold, distributing the available cash
        # by either equal weight or inverse-ATR (volatility-weighted) sizing.
        new_eligibles = [s for s in eligible if s["symbol"] not in holdings]
        if new_eligibles and cash > 1.0:
            if volatility_weighted:
                inv_atr = [1.0 / max(s["atr_pct"], 0.5) for s in new_eligibles]
                tot = sum(inv_atr)
                weights = [w / tot for w in inv_atr]
            else:
                weights = [1.0 / len(new_eligibles)] * len(new_eligibles)

            # Scale deployment by the regime factor (1.0 = full, 0.5 = soft bear, etc.)
            cash_to_deploy = cash * regime_alloc
            for s, w in zip(new_eligibles, weights):
                sym = s["symbol"]
                px = float(prices.get(sym, 0) or 0)
                if px <= 0:
                    continue
                spend = cash_to_deploy * w
                if spend < 1.0 or spend > cash:
                    spend = min(spend, cash)
                units = (spend * (1 - FEE_RATE)) / px
                holdings[sym] = {"units": units, "peak_price": px}
                cash -= spend
                trades.append({"timestamp": ts, "side": "BUY", "symbol": sym,
                               "price": px, "units": units, "reason": "ROTATION"})

        last_picks = pick_symbols

    equity = pd.Series(equity_curve, index=closes.index, name="equity")
    trades_df = pd.DataFrame(trades)

    rolling_max = equity.cummax()
    drawdown = (equity - rolling_max) / rolling_max
    max_dd = drawdown.min() * 100 if len(drawdown) else 0.0

    return {
        "equity_curve": equity,
        "trades": trades_df,
        "final_equity": equity.iloc[-1],
        "return_pct": (equity.iloc[-1] / starting_cash - 1) * 100,
        "max_drawdown_pct": max_dd,
        "n_trades": len(trades_df),
        "n_switches": len(trades_df[trades_df["side"] == "BUY"]),
        "last_picks": last_picks,
        "symbols_traded": sorted(trades_df["symbol"].unique().tolist()) if len(trades_df) else [],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=20, help="Universe size")
    parser.add_argument("--timeframe", default="4h")
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--rebalance-bars", type=int, default=6,
                        help="Rebalance every N bars (e.g. 6 bars on 4h = daily)")
    parser.add_argument("--momentum-lookback", type=int, default=20)
    parser.add_argument("--ema-short", type=int, default=20)
    parser.add_argument("--ema-long", type=int, default=50)
    parser.add_argument("--top-k", type=int, default=1, help="Hold top K coins, equal-weighted")
    parser.add_argument("--cash", type=float, default=10_000.0)
    parser.add_argument("--min-volume", type=float, default=5_000_000)
    parser.add_argument("--bias-aware", action="store_true",
                        help="Use point-in-time universe (rank by trailing USD volume at "
                             "each rebalance). Requires --candidate-pool to be larger than --universe-size.")
    parser.add_argument("--candidate-pool", type=int, default=100,
                        help="With --bias-aware: total candidate pool fetched from mainnet")
    parser.add_argument("--universe-size", type=int, default=25,
                        help="With --bias-aware: top-N by volume picked at each rebalance")
    parser.add_argument("--regime-filter", action="store_true",
                        help="Only deploy when BTC is in a bull regime (50 EMA > 200 EMA). "
                             "Otherwise sit in cash. Halves drawdowns historically.")
    args = parser.parse_args()

    ex = get_data_exchange()
    pool_size = args.candidate_pool if args.bias_aware else args.top
    universe = get_universe(ex, top_n=pool_size, min_volume_usd=args.min_volume)
    print(f"Candidate pool ({len(universe)} coins)" if args.bias_aware
          else f"Universe ({len(universe)} coins): {', '.join(p['symbol'] for p in universe)}")
    print(f"Fetching history (this may take a few minutes, cached after first run)...")

    data = _ensure_data(ex, universe, args.timeframe, args.days)
    print(f"Got data for {len(data)} coins")

    result = run(
        data, rebalance_bars=args.rebalance_bars,
        momentum_lookback=args.momentum_lookback,
        ema_short=args.ema_short, ema_long=args.ema_long,
        top_k=args.top_k, starting_cash=args.cash,
        universe_size=args.universe_size if args.bias_aware else None,
        regime_filter=args.regime_filter,
    )

    btc = data.get("BTC/USDT")
    btc_hold = ((btc["close"].iloc[-1] / btc["close"].iloc[0]) - 1) * 100 if btc is not None else float("nan")

    print()
    print(f"Strategy:       Rotational momentum (top {args.top_k} of {args.top})")
    print(f"Timeframe:      {args.timeframe}, rebalance every {args.rebalance_bars} bars")
    print(f"Period:         {result['equity_curve'].index[0]} → {result['equity_curve'].index[-1]}")
    print(f"Starting:       ${args.cash:,.2f}")
    print(f"Final equity:   ${result['final_equity']:,.2f}")
    print(f"Return:         {result['return_pct']:+.2f}%")
    print(f"Max drawdown:   {result['max_drawdown_pct']:.2f}%")
    print(f"Switches:       {result['n_switches']}")
    print(f"Coins traded:   {len(result['symbols_traded'])} ({', '.join(result['symbols_traded'][:8])}{'...' if len(result['symbols_traded'])>8 else ''})")
    print(f"Currently:      {result['last_picks']}")
    print(f"BTC buy & hold: {btc_hold:+.2f}%   (benchmark)")


if __name__ == "__main__":
    main()
