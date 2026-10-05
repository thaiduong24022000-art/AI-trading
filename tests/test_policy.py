"""
Kiem tra lop suy luan cua policy.

TRONG TAM LA CAC DUONG TU CHOI. Mot mo hinh du doan sai thi backtest se thay;
mot mo hinh du doan tren dac trung NaN, tren xep hang cua 3 ma, hoac tren mot
bai toan da doi barrier thi khong ai thay - no van tra ve mot con so trong nhu
that. Vi vay moi truong hop khong du dieu kien deu phai tra ve "khong y kien",
va day la bo test dam bao dieu do.

Cung o day: rang buoc cua che do bong phai duoc thuc thi BANG CODE. Test cuoi
file ep mo hinh noi BUY that to roi kiem tra tin hieu ra van la HOLD.
"""
import numpy as np
import pandas as pd
import pytest

from src import model_store, policy as policy_mod
from src.strategies.base import BUY, HOLD, SELL
from src.strategies.ml_policy import MLPolicyStrategy
from tests.conftest import make_cfg

COT = ["mom_6", "adx"]


class BoosterGia:
    def __init__(self, p):
        self.p = p

    def save_model(self, path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("gia")

    def predict(self, X):
        return np.full(len(X), self.p)


def _mo_hinh(p_long=0.5, p_short=0.5, cfg=None, lai=0.02, lo=-0.01):
    cfg = cfg or make_cfg()
    meta = {
        "cot_dac_trung": COT,
        "max_horizon": 60,
        "dau_van_tay": model_store.dau_van_tay(COT, cfg, 60),
        "tham_so_bai_toan": {t: getattr(cfg, t, None)
                             for t in model_store.THAM_SO_BAI_TOAN},
        "bien_do": {"lai_long": lai, "lo_long": lo, "lai_short": lai, "lo_short": lo},
    }
    return model_store.MoHinhPolicy("v_test", BoosterGia(p_long), BoosterGia(p_short), meta)


def _policy(mo_hinh=None, cfg=None, tmp_path=None):
    cfg = cfg or make_cfg(POLICY_MODE=policy_mod.CHU_DONG)
    kho = model_store.KhoModel(str(tmp_path)) if tmp_path else model_store.KhoModel()
    p = policy_mod.MLPolicy.__new__(policy_mod.MLPolicy)
    p.cfg = cfg
    p.kho = kho
    p.mo_hinh = mo_hinh
    p._van_tay_loi = None
    p._mtime_champion = 0.0
    return p


def _hang(n_ma=20, **gia_tri):
    d = {"mom_6": 0.01, "adx": 25.0, "n_ma": n_ma, "symbol": "BTCUSDT",
         "timestamp": 1_700_000_000_000}
    d.update(gia_tri)
    return pd.Series(d)


# ==========================================================
# Duong tu choi
# ==========================================================
def test_khong_co_mo_hinh_thi_khong_co_y_kien():
    kq = _policy(None).du_doan(_hang())
    assert kq.action == HOLD
    assert kq.co_y_kien is False
    assert "champion" in kq.ly_do


def test_dac_trung_NaN_thi_tu_choi():
    kq = _policy(_mo_hinh(0.9, 0.1)).du_doan(_hang(adx=float("nan")))
    assert kq.co_y_kien is False
    assert "adx" in kq.ly_do


def test_thieu_cot_dac_trung_thi_tu_choi():
    hang = pd.Series({"mom_6": 0.01, "n_ma": 20})
    kq = _policy(_mo_hinh(0.9, 0.1)).du_doan(hang)
    assert kq.co_y_kien is False
    assert "thieu" in kq.ly_do


def test_qua_it_ma_thi_tu_choi_vi_xep_hang_vo_nghia():
    """Voi 3 ma, 'top 33%' khong mang thong tin gi, nhung mo hinh van an cot _r
    nhu that. Phai tu choi thay vi du doan tren rac."""
    cfg = make_cfg(POLICY_MODE=policy_mod.CHU_DONG, POLICY_MIN_MA=8)
    mh = _mo_hinh(0.9, 0.1, cfg)
    mh.meta["cot_dac_trung"] = ["mom_6", "adx", "mom_6_r"]

    hang = _hang(n_ma=3)
    hang["mom_6_r"] = 0.8
    kq = _policy(mh, cfg).du_doan(hang)
    assert kq.co_y_kien is False
    assert "xep hang" in kq.ly_do


def test_du_ma_thi_khong_con_chan_vi_ly_do_xep_hang():
    cfg = make_cfg(POLICY_MODE=policy_mod.CHU_DONG, POLICY_MIN_MA=8)
    mh = _mo_hinh(0.9, 0.1, cfg)
    mh.meta["cot_dac_trung"] = ["mom_6", "adx", "mom_6_r"]
    hang = _hang(n_ma=20)
    hang["mom_6_r"] = 0.8
    assert _policy(mh, cfg).du_doan(hang).co_y_kien is True


def test_booster_nem_ngoai_le_thi_khong_lam_sap_vong_giao_dich():
    class BoosterNo:
        def predict(self, X):
            raise RuntimeError("mo hinh hong")

    mh = _mo_hinh(0.9, 0.1)
    mh.booster_long = BoosterNo()
    kq = _policy(mh).du_doan(_hang())
    assert kq.co_y_kien is False
    assert "loi suy luan" in kq.ly_do


def _booster_that(seed=0):
    """Booster LightGBM that, nho nhat co the - de test duong nap tu dia."""
    import lightgbm as lgb

    rng = np.random.default_rng(seed)
    X = rng.normal(size=(200, len(COT)))
    y = (X[:, 0] > 0).astype(int)
    return lgb.train({"objective": "binary", "verbosity": -1, "num_leaves": 3},
                     lgb.Dataset(X, label=y, feature_name=COT), num_boost_round=5)


def test_doi_barrier_thi_policy_tu_choi_nap_champion(tmp_path):
    """Mo hinh cu van nap duoc va van du doan - nhung no giai bai toan khac."""
    cfg_cu = make_cfg(POLICY_MODE=policy_mod.CHU_DONG, ATR_STOP_MULT=2.0)
    kho = model_store.KhoModel(str(tmp_path))
    meta = _mo_hinh(0.9, 0.1, cfg_cu).meta
    meta["phien_ban"] = "v1"
    kho.luu(_booster_that(0), _booster_that(1), meta)
    kho.thang_cap("v1", "test")

    # Cung cau hinh -> nap duoc binh thuong
    assert policy_mod.MLPolicy(cfg_cu, kho).san_sang is True

    # Doi ATR_STOP_MULT -> mo hinh van doc duoc tu dia nhung phai bi TU CHOI
    cfg_moi = make_cfg(POLICY_MODE=policy_mod.CHU_DONG, ATR_STOP_MULT=1.5)
    p = policy_mod.MLPolicy(cfg_moi, kho)
    assert p.san_sang is False
    assert "ATR_STOP_MULT" in p.du_doan(_hang()).ly_do


def test_tep_mo_hinh_hong_thi_lui_ve_chay_thuan_luat(tmp_path):
    """Tep hong khong duoc nem ngoai le len vong giao dich."""
    cfg = make_cfg(POLICY_MODE=policy_mod.CHU_DONG)
    kho = model_store.KhoModel(str(tmp_path))
    meta = _mo_hinh(0.9, 0.1, cfg).meta
    meta["phien_ban"] = "v1"
    kho.luu(BoosterGia(0.9), BoosterGia(0.1), meta)      # ghi rac thay vi booster
    kho.thang_cap("v1", "test")

    p = policy_mod.MLPolicy(cfg, kho)
    assert p.san_sang is False
    assert p.du_doan(_hang()).co_y_kien is False


# ==========================================================
# Toan ky vong
# ==========================================================
def test_ky_vong_duong_manh_thi_vao_lenh_mua():
    # p=0.9 -> EV = 0.9*0.02 + 0.1*(-0.01) = +0.017
    cfg = make_cfg(POLICY_MODE=policy_mod.CHU_DONG, POLICY_EV_MIN=0.0015,
                   POLICY_EV_FULL=0.012)
    kq = _policy(_mo_hinh(0.9, 0.1, cfg), cfg).du_doan(_hang())
    assert kq.action == BUY
    assert kq.ev_long == pytest.approx(0.017)
    assert kq.strength == pytest.approx(1.0)     # vuot muc EV_FULL


def test_ky_vong_duoi_nguong_thi_HOLD():
    # p=0.4 -> EV = 0.4*0.02 + 0.6*(-0.01) = +0.002 cho ca hai chieu
    cfg = make_cfg(POLICY_MODE=policy_mod.CHU_DONG, POLICY_EV_MIN=0.005)
    kq = _policy(_mo_hinh(0.4, 0.4, cfg), cfg).du_doan(_hang())
    assert kq.action == HOLD
    assert kq.co_y_kien is True          # co danh gia, va ket luan la dung yen
    assert "duoi nguong" in kq.ly_do


def test_ben_ban_manh_hon_thi_vao_lenh_ban():
    cfg = make_cfg(POLICY_MODE=policy_mod.CHU_DONG, POLICY_EV_MIN=0.0015)
    kq = _policy(_mo_hinh(0.2, 0.9, cfg), cfg).du_doan(_hang())
    assert kq.action == SELL


def test_ca_hai_chieu_deu_duong_thi_coi_la_tu_mau_thuan_va_HOLD():
    """Mo hinh noi 'mua cung lai, ban cung lai' la mo hinh dang tu mau thuan.
    Do la tin hieu KEM chac chan hon, khong phai manh hon."""
    cfg = make_cfg(POLICY_MODE=policy_mod.CHU_DONG, POLICY_EV_MIN=0.0015)
    kq = _policy(_mo_hinh(0.9, 0.9, cfg), cfg).du_doan(_hang())
    assert kq.action == HOLD
    assert "mau thuan" in kq.ly_do


def test_strength_tang_dan_theo_ky_vong():
    cfg = make_cfg(POLICY_MODE=policy_mod.CHU_DONG, POLICY_EV_MIN=0.0,
                   POLICY_EV_FULL=0.02)
    yeu = _policy(_mo_hinh(0.55, 0.1, cfg), cfg).du_doan(_hang()).strength
    manh = _policy(_mo_hinh(0.80, 0.1, cfg), cfg).du_doan(_hang()).strength
    assert 0.0 < yeu < manh <= 1.0


# ==========================================================
# Che do trien khai
# ==========================================================
def _chien_luoc(che_do, p_long=0.95, p_short=0.05):
    cfg = make_cfg(POLICY_MODE=che_do, POLICY_EV_MIN=0.0015, POLICY_MIN_MA=8)
    st = MLPolicyStrategy.__new__(MLPolicyStrategy)
    st.params = {}
    st.cfg = cfg
    st.policy = _policy(_mo_hinh(p_long, p_short, cfg), cfg)
    st._symbol = ""
    st._panel = None
    st.ket_qua_gan_nhat = None
    return st


def _panel_mot_hang():
    return pd.DataFrame([{"mom_6": 0.01, "adx": 25.0, "n_ma": 20,
                          "symbol": "BTCUSDT", "timestamp": 1_700_000_000_000}])


def _df_mot_nen():
    return pd.DataFrame({"timestamp": [1_700_000_000_000], "close": [100.0]})


def test_che_do_bong_khong_bao_gio_tra_ve_lenh():
    """Rang buoc quan trong nhat cua che do bong: du mo hinh chac chan den dau,
    tin hieu ra van phai la HOLD. Duoc thuc thi bang code, khong bang ky luat."""
    st = _chien_luoc(policy_mod.BONG)
    st.dat_boi_canh("BTCUSDT", _panel_mot_hang())
    sig = st.generate_at(_df_mot_nen(), 0)

    assert sig.action == HOLD
    # ...nhung y kien that van duoc giu lai de ghi so
    assert st.y_kien_tho().action == BUY


def test_che_do_active_thi_tin_hieu_di_ra_binh_thuong():
    st = _chien_luoc(policy_mod.CHU_DONG)
    st.dat_boi_canh("BTCUSDT", _panel_mot_hang())
    assert st.generate_at(_df_mot_nen(), 0).action == BUY


def test_khong_co_panel_thi_khong_ra_tin_hieu():
    st = _chien_luoc(policy_mod.CHU_DONG)
    sig = st.generate_at(_df_mot_nen(), 0)
    assert sig.action == HOLD
    assert "panel" in sig.reason


def test_panel_khong_co_ma_dang_xet_thi_khong_ra_tin_hieu():
    st = _chien_luoc(policy_mod.CHU_DONG)
    st.dat_boi_canh("ETHUSDT", _panel_mot_hang())     # panel chi co BTCUSDT
    sig = st.generate_at(_df_mot_nen(), 0)
    assert sig.action == HOLD
    assert "khong tim thay" in sig.reason


def test_lay_hang_theo_dung_moc_thoi_gian():
    panel = pd.DataFrame([
        {"symbol": "BTCUSDT", "timestamp": 100, "x": 1},
        {"symbol": "BTCUSDT", "timestamp": 200, "x": 2},
    ])
    assert policy_mod.lay_hang(panel, "BTCUSDT", 100)["x"] == 1
    assert policy_mod.lay_hang(panel, "BTCUSDT")["x"] == 2          # moc moi nhat
    assert policy_mod.lay_hang(panel, "BTCUSDT", 999) is None
