"""
Chien luoc 2: Mean-reversion (RSI cuc tri + Bollinger).

Y tuong: trong thi truong di ngang, gia bi keo qua xa khoi trung binh
co xu huong quay lai. Bo loc adx_max ton tai vi mean-reversion nguoc mot
xu huong manh la cach nhanh nhat de bi nghien nat.

Thang khi: sideway. Thua khi: trending manh.
"""
import pandas as pd

from .base import BUY, SELL, Signal, Strategy
from .. import indicators
from ..regime import RANGE


class MeanReversion(Strategy):
    name = "mean_reversion"
    preferred_regimes = (RANGE,)
    default_params = {
        "rsi_period": 14, "rsi_oversold": 30.0, "rsi_overbought": 70.0,
        "bb_period": 20, "bb_std": 2.0, "adx_max": 25.0,
    }

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy() if self._col("rsi") not in df.columns else df
        p = self.params
        out[self._col("rsi")] = indicators.rsi(out["close"], int(p["rsi_period"]))
        low, _mid, high = indicators.bollinger(out["close"], int(p["bb_period"]), float(p["bb_std"]))
        out[self._col("bb_low")] = low
        out[self._col("bb_high")] = high
        if "adx" not in out.columns:
            out["adx"] = indicators.adx(out)
        return out

    def generate_at(self, df: pd.DataFrame, i: int) -> Signal:
        sig = self._base_signal()
        p = self.params
        if i < indicators.warmup_bars():
            sig.reason = "chua du nen warmup"
            return sig

        rsi_val = df[self._col("rsi")].iloc[i]
        low_band = df[self._col("bb_low")].iloc[i]
        high_band = df[self._col("bb_high")].iloc[i]
        adx_val = df["adx"].iloc[i]
        close = float(df["close"].iloc[i])

        if pd.isna(rsi_val) or pd.isna(low_band) or pd.isna(adx_val):
            sig.reason = "chi bao chua san sang"
            return sig

        rsi_val, adx_val = float(rsi_val), float(adx_val)
        low_band, high_band = float(low_band), float(high_band)
        sig.metrics = {"rsi": rsi_val, "adx": adx_val}

        if adx_val > p["adx_max"]:
            sig.reason = "ADX=%.1f qua cao - tranh mean-reversion nguoc xu huong" % adx_val
            return sig

        if rsi_val <= p["rsi_oversold"] and close <= low_band:
            sig.action = BUY
            sig.strength = min(1.0, 0.5 + (float(p["rsi_oversold"]) - rsi_val) / 30.0)
            sig.reason = "RSI=%.1f qua ban, gia duoi dai Bollinger duoi" % rsi_val
        elif rsi_val >= p["rsi_overbought"] and close >= high_band:
            sig.action = SELL
            sig.strength = min(1.0, 0.5 + (rsi_val - float(p["rsi_overbought"])) / 30.0)
            sig.reason = "RSI=%.1f qua mua, gia tren dai Bollinger tren" % rsi_val
        else:
            sig.reason = "RSI=%.1f chua toi vung cuc tri" % rsi_val
        return sig
