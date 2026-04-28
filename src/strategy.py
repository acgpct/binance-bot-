"""EMA crossover strategy with optional higher-timeframe trend filter and risk params.

Entry signal (BUY): fast EMA crosses above slow EMA on the trading timeframe,
                    AND the higher timeframe is in an uptrend (if htf_minutes is set).
Exit signal (SELL): fast EMA crosses below slow EMA. The bot/backtest layer also
                    applies stop-loss, take-profit, and trailing-stop exits which
                    take priority over the EMA cross exit.
"""

from dataclasses import dataclass

import pandas as pd

BUY = 1
SELL = -1
HOLD = 0


@dataclass
class EmaCrossover:
    # Entry signal
    fast: int = 9
    slow: int = 21

    # Higher-timeframe trend filter (None to disable)
    htf_minutes: int | None = 60
    htf_fast: int = 50
    htf_slow: int = 200

    # Risk management — applied by the backtest/bot loop, not in compute()
    stop_loss_pct: float = 0.02       # 2% stop loss; 0 to disable
    take_profit_pct: float = 0.04     # 4% take profit; 0 to disable
    trailing_stop_pct: float = 0.0    # 0 to disable; e.g. 0.015 = 1.5% trailing

    def __post_init__(self) -> None:
        if self.fast >= self.slow:
            raise ValueError(f"fast ({self.fast}) must be < slow ({self.slow})")
        if self.htf_minutes is not None and self.htf_fast >= self.htf_slow:
            raise ValueError(f"htf_fast ({self.htf_fast}) must be < htf_slow ({self.htf_slow})")

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add ema_fast, ema_slow, htf_uptrend, signal columns."""
        out = df.copy()
        out["ema_fast"] = out["close"].ewm(span=self.fast, adjust=False).mean()
        out["ema_slow"] = out["close"].ewm(span=self.slow, adjust=False).mean()

        if self.htf_minutes:
            out["htf_uptrend"] = self._htf_uptrend(df)
        else:
            out["htf_uptrend"] = True

        diff = out["ema_fast"] - out["ema_slow"]
        prev = diff.shift(1)
        out["signal"] = HOLD
        out.loc[(prev <= 0) & (diff > 0) & out["htf_uptrend"], "signal"] = BUY
        out.loc[(prev >= 0) & (diff < 0), "signal"] = SELL
        return out

    def latest_signal(self, df: pd.DataFrame) -> int:
        return int(self.compute(df)["signal"].iloc[-1])

    def _htf_uptrend(self, df: pd.DataFrame) -> pd.Series:
        """Resample to higher timeframe, compute trend (fast EMA > slow EMA),
        shift by 1 to avoid lookahead, then forward-fill back to the LTF index."""
        htf = df.resample(f"{self.htf_minutes}min").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
        }).dropna()
        f = htf["close"].ewm(span=self.htf_fast, adjust=False).mean()
        s = htf["close"].ewm(span=self.htf_slow, adjust=False).mean()
        uptrend = (f > s).shift(1)
        return uptrend.reindex(df.index, method="ffill").fillna(False).astype(bool)
