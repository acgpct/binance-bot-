"""EMA crossover strategy. Emits BUY when fast EMA crosses above slow EMA, SELL on the reverse."""

from dataclasses import dataclass

import pandas as pd

BUY = 1
SELL = -1
HOLD = 0


@dataclass
class EmaCrossover:
    fast: int = 9
    slow: int = 21

    def __post_init__(self) -> None:
        if self.fast >= self.slow:
            raise ValueError(f"fast ({self.fast}) must be < slow ({self.slow})")

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add ema_fast, ema_slow, and signal columns. Signal is BUY/SELL only on the crossover bar."""
        out = df.copy()
        out["ema_fast"] = out["close"].ewm(span=self.fast, adjust=False).mean()
        out["ema_slow"] = out["close"].ewm(span=self.slow, adjust=False).mean()

        diff = out["ema_fast"] - out["ema_slow"]
        prev = diff.shift(1)
        out["signal"] = HOLD
        out.loc[(prev <= 0) & (diff > 0), "signal"] = BUY
        out.loc[(prev >= 0) & (diff < 0), "signal"] = SELL
        return out

    def latest_signal(self, df: pd.DataFrame) -> int:
        return int(self.compute(df)["signal"].iloc[-1])
