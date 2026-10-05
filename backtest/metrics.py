"""
Chi so danh gia chien luoc.

Luu y ve Sharpe: no duoc tinh tren chuoi loi nhuan theo NEN, roi quy doi
sang nam theo so nen moi nam. Voi khung 1 gio, mot nam co ~8760 nen.
Sharpe cua chien luoc giao dich khong the so sanh truc tiep voi Sharpe cua
danh muc mua-va-giu, va Sharpe tinh tren qua it lenh thi khong co y nghia.
"""
import math
from dataclasses import asdict, dataclass
from typing import Dict, List

import numpy as np
import pandas as pd


@dataclass
class Metrics:
    num_trades: int = 0
    win_rate: float = 0.0
    total_return: float = 0.0
    profit_factor: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    expectancy: float = 0.0
    total_fees: float = 0.0
    final_equity: float = 0.0

    def to_dict(self) -> Dict:
        return asdict(self)

    def summary(self) -> str:
        return (
            "lenh=%d | win=%.1f%% | return=%.2f%% | PF=%.2f | Sharpe=%.2f | maxDD=%.2f%% | phi=%.2f"
            % (self.num_trades, self.win_rate * 100, self.total_return * 100,
               self.profit_factor, self.sharpe, self.max_drawdown * 100, self.total_fees)
        )


# So nen mot nam theo tung khung. Sharpe duoc quy doi sang nam bang con so nay,
# nen dung sai no la Sharpe cua cac khung KHONG so sanh duoc voi nhau -
# va do la loi im lang: moi con so van hien ra binh thuong.
BARS_PER_YEAR = {
    "1": 525600, "3": 175200, "5": 105120, "15": 35040, "30": 17520,
    "60": 8760, "120": 4380, "240": 2190, "360": 1460, "720": 730,
    "D": 365, "W": 52, "M": 12,
}


def bars_per_year(interval: str) -> int:
    return BARS_PER_YEAR.get(str(interval).upper().strip(), 8760)


def max_drawdown(equity_curve: pd.Series) -> float:
    if len(equity_curve) == 0:
        return 0.0
    running_max = equity_curve.cummax()
    dd = (equity_curve - running_max) / running_max.replace(0, np.nan)
    return abs(float(dd.min())) if not dd.isna().all() else 0.0


def sharpe_ratio(returns: pd.Series, bars_per_year: int = 8760) -> float:
    if len(returns) < 2:
        return 0.0
    std = float(returns.std(ddof=1))
    if std == 0 or math.isnan(std):
        return 0.0
    return float(returns.mean() / std * math.sqrt(bars_per_year))


def by_regime(trades: List[dict]) -> Dict[str, Dict[str, float]]:
    """Gom lenh theo regime luc VAO lenh.

    Dung cho cong thong ke 'co lai o it nhat 2 trong 3 regime': mot chien luoc
    chi lai trong dung mot loai thi truong la mot chien luoc mong manh.
    """
    out: Dict[str, Dict[str, float]] = {}
    for t in trades:
        bucket = out.setdefault(t.get("regime") or "unknown",
                                {"num_trades": 0.0, "pnl": 0.0})
        bucket["num_trades"] += 1
        bucket["pnl"] += float(t.get("pnl", 0.0))
    return out


def compute(trades: List[dict], equity_curve: pd.Series,
            initial_equity: float, bars_per_year: int = 8760) -> Metrics:
    m = Metrics()
    m.num_trades = len(trades)
    m.final_equity = float(equity_curve.iloc[-1]) if len(equity_curve) else initial_equity
    m.total_return = (m.final_equity / initial_equity - 1.0) if initial_equity else 0.0
    m.max_drawdown = max_drawdown(equity_curve)
    m.total_fees = float(sum(t.get("fees", 0.0) for t in trades))

    if len(equity_curve) > 1:
        m.sharpe = sharpe_ratio(equity_curve.pct_change().dropna(), bars_per_year)

    if not trades:
        return m

    pnls = np.array([t["pnl"] for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]

    m.win_rate = len(wins) / len(pnls)
    m.avg_win = float(wins.mean()) if len(wins) else 0.0
    m.avg_loss = float(losses.mean()) if len(losses) else 0.0
    gross_win = float(wins.sum()) if len(wins) else 0.0
    gross_loss = float(-losses.sum()) if len(losses) else 0.0
    m.profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (
        float("inf") if gross_win > 0 else 0.0)
    m.expectancy = float(pnls.mean())
    return m
