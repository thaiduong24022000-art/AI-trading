from .base import BUY, HOLD, SELL, Signal, Strategy
from .breakout import Breakout
from .mean_reversion import MeanReversion
from .trend_following import TrendFollowing

ALL_STRATEGIES = (TrendFollowing, MeanReversion, Breakout)


def build_default_ensemble():
    """Tao bo 3 chien luoc mac dinh voi tham so goc."""
    return [cls() for cls in ALL_STRATEGIES]


def build_ensemble(names=None, kho=None):
    """Tao ensemble tu danh sach ten.

    Ton tai vi khong phai luc nao cung nen chay ca ba: kiem dinh 2026-09 cho thay
    trend_following va mean_reversion co bien do am tren du lieu that, va de
    chung trong ensemble la keo tut chien luoc duy nhat con duong.

    Ngoai ba chien luoc goc, ten con co the la mot chien luoc LUAT dang o trang
    thai chu_dong trong kho (src/strategies/kho_luat.py). Chien luoc luat o
    trang thai bong CO Y khong lay duoc o day: chi viec co mat trong ensemble
    da lam doi trong so cua cac chien luoc khac, va nhu vay che do bong khong
    con la bong nua.
    """
    by_name = {c.name: c for c in ALL_STRATEGIES}
    if not names:
        return build_default_ensemble()

    thieu = [n for n in names if n not in by_name]
    if thieu:
        from .kho_luat import CHU_DONG, KhoLuat
        kho = kho or KhoLuat()
        luat = {c.name: c for c in kho.bien_dich_theo_trang_thai(CHU_DONG)}
        by_name.update(luat)
        thieu = [n for n in names if n not in by_name]

    if thieu:
        raise ValueError("Khong co chien luoc: %s (co san: %s)"
                         % (", ".join(thieu), ", ".join(sorted(by_name))))
    return [by_name[n]() for n in names]


__all__ = [
    "BUY", "SELL", "HOLD", "Signal", "Strategy",
    "TrendFollowing", "MeanReversion", "Breakout",
    "ALL_STRATEGIES", "build_default_ensemble", "build_ensemble",
]
