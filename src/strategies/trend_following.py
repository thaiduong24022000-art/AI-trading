"""
Chien luoc 1: Trend-following (EMA cross + loc ADX).

Y tuong: chi di theo xu huong khi thi truong THUC SU co xu huong.
Bo loc ADX la phan quan trong nhat - EMA cross khong co loc ADX se bi cua
lien tuc trong thi truong di ngang, va do la cach mat tien pho bien nhat
cua chien luoc nay.

Thang khi: trending. Thua khi: sideway.
"""
import pandas as pd

from .base import BUY, SELL, Signal, Strategy
from .. import indicators
from ..regime import TREND


class TrendFollowing(Strategy):
    name = "trend_following"
    preferred_regimes = (TREND,)
    default_params = {"ema_fast": 20, "ema_slow": 50, "adx_min": 25.0, "confirm_bars": 3}

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy() if self._col("fast") not in df.columns else df
        out[self._col("fast")] = indicators.ema(out["close"], int(self.params["ema_fast"]))
        out[self._col("slow")] = indicators.ema(out["close"], int(self.params["ema_slow"]))
        if "adx" not in out.columns:
            out["adx"] = indicators.adx(out)
        return out

    def generate_at(self, df: pd.DataFrame, i: int) -> Signal:
        sig = self._base_signal()
        p = self.params
        confirm = int(p["confirm_bars"])
        if i < indicators.warmup_bars():
            sig.reason = "chua du nen warmup"
            return sig

        fast = df[self._col("fast")]
        slow = df[self._col("slow")]
        adx_val = df["adx"].iloc[i]

        if pd.isna(fast.iloc[i]) or pd.isna(slow.iloc[i]) or pd.isna(adx_val):
            sig.reason = "chi bao chua san sang"
            return sig

        adx_val = float(adx_val)
        sig.metrics = {"adx": adx_val, "ema_fast": float(fast.iloc[i]), "ema_slow": float(slow.iloc[i])}

        if adx_val < p["adx_min"]:
            sig.reason = "ADX=%.1f < %.1f, khong du xu huong" % (adx_val, p["adx_min"])
            return sig

        above_now = fast.iloc[i] > slow.iloc[i]
        lo = max(0, i - confirm)
        prev_fast = fast.iloc[lo:i]
        prev_slow = slow.iloc[lo:i]
        just_up = above_now and bool((prev_fast <= prev_slow).any())
        just_down = (not above_now) and bool((prev_fast >= prev_slow).any())
        strength = min(1.0, 0.5 + (adx_val - float(p["adx_min"])) / 50.0)

        if just_up:
            sig.action, sig.strength = BUY, strength
            sig.reason = "EMA%d cat len EMA%d, ADX=%.1f" % (p["ema_fast"], p["ema_slow"], adx_val)
        elif just_down:
            sig.action, sig.strength = SELL, strength
            sig.reason = "EMA%d cat xuong EMA%d, ADX=%.1f" % (p["ema_fast"], p["ema_slow"], adx_val)
        else:
            sig.reason = "khong co cross moi"
        return sig
