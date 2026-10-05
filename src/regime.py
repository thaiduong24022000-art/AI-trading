"""
Phan loai che do thi truong (regime) - Nang cap 2.

Ly do ton tai: mot chien lugc thang trong thi truong co xu huong se bi cua
nat trong thi truong di ngang. Biet dang o regime nao cho phep allocator
doi trong so giua cac chien luoc thay vi chay mot chien luoc cho moi hoan canh.

Phan nay hoan toan DINH LUONG (ADX + ATR percentile + autocorrelation).
LLM co the bo sung boi canh tuong thuat o giai doan 4, nhung khong bat buoc:
he thong phai chay dung khi khong co LLM.
"""
from dataclasses import dataclass, field
from typing import Dict

import numpy as np
import pandas as pd

import config

TREND = "trend"
RANGE = "range"
HIGH_VOL = "high_vol"
UNKNOWN = "unknown"

ALL_REGIMES = (TREND, RANGE, HIGH_VOL)


@dataclass
class RegimeResult:
    regime: str
    confidence: float
    metrics: Dict[str, float] = field(default_factory=dict)
    reason: str = ""

    def __str__(self) -> str:
        return "%s (conf=%.2f) %s" % (self.regime, self.confidence, self.reason)


def classify_at(df: pd.DataFrame, i: int, cfg=config) -> RegimeResult:
    """Phan loai regime tai dong i (chi nhin cac dong <= i)."""
    lo = max(0, i - cfg.REGIME_LOOKBACK + 1)
    return classify(df.iloc[lo:i + 1], cfg)


def classify(df: pd.DataFrame, cfg=config) -> RegimeResult:
    """Phan loai regime tu DataFrame da co chi bao (add_indicators).

    Thu tu uu tien: high_vol > trend > range.
    High vol duoc kiem tra truoc vi trong con hoang loan, ca trend-following
    lan mean-reversion deu nguy hiem - luc do nen giam quy mo hoac dung han.
    """
    needed = ("adx", "atr_pct")
    for col in needed:
        if col not in df.columns:
            return RegimeResult(UNKNOWN, 0.0, {}, "thieu cot %s" % col)

    lookback = min(cfg.REGIME_LOOKBACK, len(df))
    window = df.iloc[-lookback:]
    if len(window) < 30:
        return RegimeResult(UNKNOWN, 0.0, {}, "chua du du lieu")

    adx_now = float(window["adx"].iloc[-1]) if not np.isnan(window["adx"].iloc[-1]) else 0.0
    atr_series = window["atr_pct"].dropna()
    if len(atr_series) < 20:
        return RegimeResult(UNKNOWN, 0.0, {}, "chua du du lieu ATR")

    atr_now = float(atr_series.iloc[-1])
    atr_rank = float((atr_series < atr_now).mean())  # percentile 0..1

    # Autocorrelation cua return: duong = co quan tinh (trend),
    # am = hay dao chieu (mean-reverting)
    returns = window["close"].pct_change().dropna()
    autocorr = float(returns.autocorr(lag=1)) if len(returns) > 10 else 0.0
    if np.isnan(autocorr):
        autocorr = 0.0

    metrics = {
        "adx": adx_now,
        "atr_pct": atr_now,
        "atr_percentile": atr_rank,
        "autocorr": autocorr,
    }

    if atr_rank >= cfg.ATR_HIGH_VOL_PERCENTILE:
        conf = min(1.0, (atr_rank - cfg.ATR_HIGH_VOL_PERCENTILE) / max(1e-9, 1.0 - cfg.ATR_HIGH_VOL_PERCENTILE))
        return RegimeResult(
            HIGH_VOL, max(0.5, conf), metrics,
            "ATR o percentile %.0f%% - bien dong bat thuong" % (atr_rank * 100),
        )

    if adx_now >= cfg.ADX_TREND_THRESHOLD:
        conf = min(1.0, (adx_now - cfg.ADX_TREND_THRESHOLD) / 25.0 + 0.5)
        return RegimeResult(
            TREND, conf, metrics,
            "ADX=%.1f vuot nguong %.0f" % (adx_now, cfg.ADX_TREND_THRESHOLD),
        )

    conf = min(1.0, (cfg.ADX_TREND_THRESHOLD - adx_now) / 25.0 + 0.4)
    return RegimeResult(
        RANGE, conf, metrics,
        "ADX=%.1f duoi nguong - thi truong di ngang" % adx_now,
    )
