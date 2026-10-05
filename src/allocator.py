"""
Bo phan bo trong so giua cac chien luoc - Nang cap 2.

Trong so phu thuoc hai thu:
  1. Regime hien tai co nam trong preferred_regimes cua chien luoc khong.
  2. Hieu suat cuon chieu gan day cua chien luoc (lay tu database).

Co san va tran (STRATEGY_WEIGHT_FLOOR / CAP) de:
  - Khong bao gio tat han mot chien luoc chi vi no vua trai qua chuoi thua
    ngan (chuoi thua ngan la binh thuong, khong phai bang chung chien luoc hong).
  - Khong bao gio don het von vao mot chien luoc vua gap may.
"""
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import config
from .regime import HIGH_VOL, RegimeResult
from .strategies.base import Strategy

logger = logging.getLogger(__name__)


@dataclass
class Allocation:
    weights: Dict[str, float]
    regime: str
    note: str = ""


def _normalize(raw: Dict[str, float], floor: float, cap: float) -> Dict[str, float]:
    """Chuan hoa ve tong = 1 roi ep vao khoang [floor, cap], lap lai vai vong."""
    if not raw:
        return {}
    total = sum(raw.values())
    if total <= 0:
        equal = 1.0 / len(raw)
        return {k: equal for k in raw}

    weights = {k: v / total for k, v in raw.items()}
    for _ in range(10):
        weights = {k: min(cap, max(floor, v)) for k, v in weights.items()}
        total = sum(weights.values())
        if abs(total - 1.0) < 1e-6:
            break
        weights = {k: v / total for k, v in weights.items()}
    return weights


def allocate(
    strategies: Sequence[Strategy],
    regime: RegimeResult,
    performance: Optional[Dict[str, float]] = None,
    cfg=config,
) -> Allocation:
    """Tra ve trong so cho tung chien luoc.

    performance: dict {ten_chien_luoc: profit_factor gan day}. Co the None
    trong nhung ngay dau khi chua co du lieu - luc do chi dua vao regime.
    """
    performance = performance or {}
    raw: Dict[str, float] = {}

    for strat in strategies:
        # Diem co ban theo do phu hop regime
        if regime.regime in strat.preferred_regimes:
            score = 1.0 + 0.5 * regime.confidence
        else:
            score = 0.5

        # Dieu chinh theo hieu suat gan day (profit factor quanh 1.0 la hoa von)
        pf = performance.get(strat.name)
        if pf is not None:
            # pf=1.0 -> he so 1.0 ; pf=2.0 -> 1.5 ; pf=0.5 -> 0.75
            score *= max(0.4, min(1.6, 0.5 + pf / 2.0))

        raw[strat.name] = score

    weights = _normalize(raw, cfg.STRATEGY_WEIGHT_FLOOR, cfg.STRATEGY_WEIGHT_CAP)

    note = "regime=%s" % regime.regime
    # Trong con bien dong cuc doan, ca hai loai chien luoc deu nguy hiem:
    # giam toan bo quy mo thay vi co chon chien luoc "it te nhat".
    if regime.regime == HIGH_VOL:
        weights = {k: v * 0.5 for k, v in weights.items()}
        note += " (bien dong cao - giam nua quy mo)"

    return Allocation(weights=weights, regime=regime.regime, note=note)


def combine_signals(signals: List, allocation: Allocation, cfg=config):
    """Gop tin hieu cua nhieu chien luoc thanh mot quyet dinh chung.

    Cach gop: cong diem co trong so cho moi huong (BUY/SELL), huong nao
    thang thi lay, kem do manh tong hop. Neu hai huong nguoc nhau ma diem
    xap xi bang nhau -> khong lam gi (thi truong khong ro rang).
    """
    from .strategies.base import BUY, HOLD, SELL

    buy_score = 0.0
    sell_score = 0.0
    reasons = []

    for sig in signals:
        if not sig.is_actionable:
            continue
        w = allocation.weights.get(sig.strategy, 0.0)
        contribution = w * sig.strength
        if sig.action == BUY:
            buy_score += contribution
        elif sig.action == SELL:
            sell_score += contribution
        reasons.append("%s:%s(%.2f)" % (sig.strategy, sig.action, contribution))

    net = buy_score - sell_score
    if abs(net) < 1e-9:
        return HOLD, 0.0, "khong co tin hieu"

    action = BUY if net > 0 else SELL
    strength = min(1.0, abs(net))

    # Neu hai phia gan bang nhau -> mau thuan, khong vao lenh
    stronger = max(buy_score, sell_score)
    weaker = min(buy_score, sell_score)
    if stronger > 0 and weaker / stronger > 0.7:
        return HOLD, 0.0, "tin hieu mau thuan (%s)" % ", ".join(reasons)

    if strength < cfg.MIN_SIGNAL_STRENGTH:
        return HOLD, strength, "tin hieu yeu %.2f < %.2f (%s)" % (
            strength, cfg.MIN_SIGNAL_STRENGTH, ", ".join(reasons))

    return action, strength, ", ".join(reasons)
