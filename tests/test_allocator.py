"""
Kiem tra bo phan bo trong so va cach gop tin hieu.

Phan dang chu y nhat o day khong phai cong thuc, ma la SU AN KHOP giua
config.MIN_SIGNAL_STRENGTH va trong so ma allocator thuc su gan ra. Hai con so
nay nam o hai file khac nhau va khong co gi rang buoc chung; neu mot nguoi doi
STRATEGY_WEIGHT_FLOOR hay nguong tin hieu ma khong doi cai kia, bot se lang le
giao dich nhieu hon hoac it hon han y dinh - khong loi, khong canh bao.
"""
import pytest

from src.allocator import Allocation, allocate, combine_signals
from src.regime import HIGH_VOL, RANGE, TREND, RegimeResult
from src.strategies import build_default_ensemble
from src.strategies.base import BUY, HOLD, SELL, Signal
from tests.conftest import make_cfg


# ==========================================================
# allocate(): trong so theo regime
# ==========================================================
@pytest.mark.parametrize("regime", [TREND, RANGE])
def test_trong_so_ton_trong_san_va_tran(cfg, regime):
    alloc = allocate(build_default_ensemble(), RegimeResult(regime, 1.0), None, cfg)

    assert sum(alloc.weights.values()) == pytest.approx(1.0)
    for name, w in alloc.weights.items():
        assert cfg.STRATEGY_WEIGHT_FLOOR <= w <= cfg.STRATEGY_WEIGHT_CAP, name


def test_chien_luoc_hop_regime_duoc_uu_tien(cfg):
    strategies = build_default_ensemble()

    xu_huong = allocate(strategies, RegimeResult(TREND, 1.0), None, cfg).weights
    di_ngang = allocate(strategies, RegimeResult(RANGE, 1.0), None, cfg).weights

    assert xu_huong["trend_following"] > xu_huong["mean_reversion"]
    assert di_ngang["mean_reversion"] > di_ngang["trend_following"]


def test_bien_dong_cao_giam_nua_toan_bo_quy_mo(cfg):
    """Trong con hoang loan ca hai loai chien luoc deu nguy hiem.

    Cach xu ly la giam quy mo tat ca, khong phai chon 'chien luoc it te nhat'.
    """
    strategies = build_default_ensemble()
    binh_thuong = allocate(strategies, RegimeResult(RANGE, 0.8), None, cfg)
    hoang_loan = allocate(strategies, RegimeResult(HIGH_VOL, 0.8), None, cfg)

    assert sum(binh_thuong.weights.values()) == pytest.approx(1.0)
    assert sum(hoang_loan.weights.values()) == pytest.approx(0.5)
    assert "bien dong cao" in hoang_loan.note


def test_hieu_suat_kem_lam_giam_trong_so_nhung_khong_tat_han(cfg):
    """Chuoi thua ngan la binh thuong, khong phai bang chung chien luoc hong."""
    strategies = build_default_ensemble()
    reg = RegimeResult(TREND, 1.0)

    kem = allocate(strategies, reg, {"trend_following": 0.3}, cfg).weights
    tot = allocate(strategies, reg, {"trend_following": 2.0}, cfg).weights

    assert tot["trend_following"] > kem["trend_following"]
    assert kem["trend_following"] >= cfg.STRATEGY_WEIGHT_FLOOR


def test_khong_chien_luoc_nao_bi_don_het_von(cfg):
    """Ke ca khi mot chien luoc vua gap may lon, tran van phai giu."""
    strategies = build_default_ensemble()
    alloc = allocate(strategies, RegimeResult(TREND, 1.0),
                     {"trend_following": 10.0}, cfg)
    assert alloc.weights["trend_following"] <= cfg.STRATEGY_WEIGHT_CAP


def test_khong_co_chien_luoc_nao_thi_khong_vo(cfg):
    alloc = allocate([], RegimeResult(TREND, 1.0), None, cfg)
    assert alloc.weights == {}


# ==========================================================
# combine_signals(): gop tin hieu thanh mot quyet dinh
# ==========================================================
def _alloc(**weights):
    return Allocation(weights=weights, regime="test")


def test_khong_co_tin_hieu_thi_hold(cfg):
    action, strength, _ = combine_signals(
        [Signal(HOLD, 0.0, strategy="a")], _alloc(a=0.5), cfg)
    assert action == HOLD
    assert strength == 0.0


def test_tin_hieu_mau_thuan_thi_dung_ngoai(cfg):
    """Hai phia gan bang nhau nghia la thi truong khong ro rang."""
    action, _, reason = combine_signals(
        [Signal(BUY, 1.0, strategy="a"), Signal(SELL, 0.9, strategy="b")],
        _alloc(a=0.5, b=0.5), cfg)
    assert action == HOLD
    assert "mau thuan" in reason


def test_mot_phia_ap_dao_thi_vao_lenh(cfg):
    action, strength, _ = combine_signals(
        [Signal(BUY, 1.0, strategy="a"), Signal(SELL, 0.2, strategy="b")],
        _alloc(a=0.5, b=0.5), cfg)
    assert action == BUY
    assert strength == pytest.approx(0.4)      # 0.5*1.0 - 0.5*0.2


def test_tin_hieu_duoi_nguong_bi_loai(cfg):
    cfg = make_cfg(MIN_SIGNAL_STRENGTH=0.15)
    action, _, reason = combine_signals(
        [Signal(BUY, 0.20, strategy="a")], _alloc(a=0.5), cfg)
    assert action == HOLD                       # 0.5*0.20 = 0.10 < 0.15
    assert "yeu" in reason


def test_chien_luoc_khong_co_trong_so_thi_khong_dong_gop(cfg):
    action, _, _ = combine_signals(
        [Signal(BUY, 1.0, strategy="khong_ai_biet")], _alloc(a=0.5), cfg)
    assert action == HOLD


# ==========================================================
# An khop giua config va allocator (xem docstring dau file)
# ==========================================================
def test_chien_luoc_bi_ep_xuong_san_khong_the_tu_vao_lenh():
    """Khang dinh duoc viet trong config.py, o day duoc kiem bang so.

    Mot chien luoc dang bi phat xuong san trong so (0.10) khong duoc phep mot
    minh keo ca ensemble vao lenh, du no tu tin 100%.
    """
    cfg = make_cfg(MIN_SIGNAL_STRENGTH=0.15, STRATEGY_WEIGHT_FLOOR=0.10)
    action, _, _ = combine_signals(
        [Signal(BUY, 1.0, strategy="a")],
        _alloc(a=cfg.STRATEGY_WEIGHT_FLOOR, b=0.45, c=0.45), cfg)
    assert action == HOLD


def test_chien_luoc_hop_regime_can_dat_do_manh_toi_thieu():
    """Khang dinh thu hai trong config.py: voi trong so ~0.42, chien luoc hop
    regime can strength >= ~0.36 moi du keo ensemble vao lenh."""
    cfg = make_cfg(MIN_SIGNAL_STRENGTH=0.15)
    alloc = _alloc(a=0.42)

    duoi_nguong, _, _ = combine_signals([Signal(BUY, 0.34, strategy="a")], alloc, cfg)
    tren_nguong, _, _ = combine_signals([Signal(BUY, 0.38, strategy="a")], alloc, cfg)

    assert duoi_nguong == HOLD                  # 0.42*0.34 = 0.143
    assert tren_nguong == BUY                   # 0.42*0.38 = 0.160


def test_trong_so_thuc_te_khop_voi_gia_dinh_trong_config(cfg):
    """Con so 0.42 trong comment cua config.py phai la con so THAT.

    Trong regime xu huong, ca trend_following lan breakout deu hop regime,
    nen moi cai duoc khoang 0.43 - do la boi canh ma nguong 0.15 duoc chon.
    Neu preferred_regimes cua mot chien luoc doi, test nay se nhac lai rang
    nguong tin hieu can duoc xem lai.
    """
    weights = allocate(build_default_ensemble(), RegimeResult(TREND, 1.0), None, cfg).weights
    assert weights["trend_following"] == pytest.approx(0.43, abs=0.05)
