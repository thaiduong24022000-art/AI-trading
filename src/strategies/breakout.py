"""
Chien luoc 3: Breakout (kenh Donchian + xac nhan khoi luong).

Bo loc khoi luong phan biet breakout that voi breakout gia: pha vo khong co
khoi luong thuong bi keo nguoc lai ngay sau do.

Chong lookahead: indicators.donchian() da shift(1) nen kenh so sanh la kenh
cua cac nen TRUOC, khong bao gom chinh nen dang xet.
"""
import pandas as pd

from .base import BUY, SELL, Signal, Strategy
from .. import indicators
from ..regime import RANGE, TREND


class Breakout(Strategy):
    name = "breakout"
    preferred_regimes = (TREND, RANGE)
    default_params = {"channel_period": 20, "volume_mult": 1.5, "atr_buffer": 0.25}

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy() if self._col("dc_high") not in df.columns else df
        low, high = indicators.donchian(out, int(self.params["channel_period"]))
        out[self._col("dc_low")] = low
        out[self._col("dc_high")] = high
        out[self._col("vol_ma")] = out["volume"].rolling(20, min_periods=20).mean()
        if "atr" not in out.columns:
            out["atr"] = indicators.atr(out)
        return out

    def generate_at(self, df: pd.DataFrame, i: int) -> Signal:
        sig = self._base_signal()
        p = self.params
        if i < indicators.warmup_bars():
            sig.reason = "chua du nen warmup"
            return sig

        upper = df[self._col("dc_high")].iloc[i]
        lower = df[self._col("dc_low")].iloc[i]
        vol_ma = df[self._col("vol_ma")].iloc[i]
        atr_val = df["atr"].iloc[i]

        if pd.isna(upper) or pd.isna(atr_val) or pd.isna(vol_ma) or vol_ma <= 0:
            sig.reason = "chi bao chua san sang"
            return sig

        close = float(df["close"].iloc[i])
        volume = float(df["volume"].iloc[i])
        upper, lower, atr_val = float(upper), float(lower), float(atr_val)
        vol_ratio = volume / float(vol_ma)
        buffer = float(p["atr_buffer"]) * atr_val
        sig.metrics = {"dc_high": upper, "dc_low": lower, "vol_ratio": vol_ratio}

        if vol_ratio < p["volume_mult"]:
            sig.reason = "khoi luong x%.2f chua du xac nhan (can x%.1f)" % (vol_ratio, p["volume_mult"])
            return sig

        strength = min(1.0, 0.5 + (vol_ratio - float(p["volume_mult"])) / 3.0)
        if close > upper + buffer:
            sig.action, sig.strength = BUY, strength
            sig.reason = "pha dinh kenh %d nen, khoi luong x%.2f" % (p["channel_period"], vol_ratio)
        elif close < lower - buffer:
            sig.action, sig.strength = SELL, strength
            sig.reason = "thung day kenh %d nen, khoi luong x%.2f" % (p["channel_period"], vol_ratio)
        else:
            sig.reason = "gia van trong kenh"
        return sig
