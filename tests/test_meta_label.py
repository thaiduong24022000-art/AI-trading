"""
Kiem tra lop bo loc meta-label.

BA THU DUOC BAO VE O DAY, theo thu tu quan trong:

  1. LAY DUNG CHIEU KET QUA. Luat de xuat BAN ma ta gan nhan bang ket qua cua
     lenh MUA thi mo hinh hoc chinh xac dieu nguoc lai voi cai ta can - va no
     van huan luyen duoc, van ra AUC dep, khong co gi bao loi. Day la loi im
     lang hoan hao nhat trong ca module.

  2. VI TRI NEN, KHONG PHAI VI TRI TIN HIEU. Purge va embargo dem theo nen cua
     lich su day du. Tin hieu chi chiem ~4% so nen, nen danh so tren rieng cac
     tin hieu se lam embargo ngan di khoang 25 lan ma khong co gi bao loi.

  3. BO LOC KHONG BAO GIO LAM TIN HIEU MANH LEN. No la mot lop LOC; neu no
     duoc phep nhan them thi no da tro thanh mot nguon tin hieu, va nguon tin
     hieu phai di qua cong thang cap rieng cua no.
"""
import numpy as np
import pandas as pd
import pytest

from src import datafeed, indicators, meta_label, meta_train, model_store
from src import validation as val_mod
from src.meta_policy import CHAN, GIAM, GIU, KHONG_Y_KIEN, KetQuaLoc, MetaPolicy
from src.strategies import Breakout, build_ensemble
from src.strategies.base import BUY, SELL
from tests.conftest import make_cfg

MAX_HORIZON = 12


@pytest.fixture(scope="module")
def frames():
    return {"MA%02dUSDT" % k: datafeed.synthetic_ohlcv(n=1200, seed=200 + k)
            for k in range(8)}


@pytest.fixture(scope="module")
def bo(frames):
    return meta_label.xay_bo_meta(frames, build_ensemble(["breakout"]),
                                  make_cfg(), MAX_HORIZON)


# ==========================================================
# Dung chieu ket qua
# ==========================================================
def test_ket_qua_lay_theo_dung_chieu_luat_de_xuat(bo):
    """Dong BUY phai mang ret_long, dong SELL phai mang ret_short."""
    if bo.empty:
        pytest.skip("du lieu tong hop khong sinh tin hieu nao")
    mua = bo[bo["la_mua"] > 0.5]
    ban = bo[bo["la_mua"] <= 0.5]
    if len(mua):
        assert np.allclose(mua["ret"], mua["ret_long"])
    if len(ban):
        assert np.allclose(ban["ret"], ban["ret_short"])


def test_nhan_khop_voi_ket_qua(bo):
    if bo.empty:
        pytest.skip("khong co tin hieu")
    assert ((bo["ret"] > 0).astype(int) == bo["y"]).all()


def test_moi_dong_deu_la_mot_tin_hieu_that(bo, frames):
    """Bo meta chi duoc chua nen ma chien luoc THUC SU len tieng."""
    if bo.empty:
        pytest.skip("khong co tin hieu")
    st = Breakout()
    d = st.prepare(indicators.add_indicators(frames["MA00USDT"]))
    theo_ts = {int(t): k for k, t in enumerate(d["timestamp"].to_numpy())}

    con = bo[bo["symbol"] == "MA00USDT"].head(12)
    for _, hang in con.iterrows():
        i = theo_ts[int(hang["timestamp"])]
        sig = st.generate_at(d, i)
        assert sig.action in (BUY, SELL)
        assert sig.action == hang["huong"]


def test_bo_meta_nho_hon_han_so_nen(bo, frames):
    """Neu bo meta to bang ca panel thi no dang lay moi nen, khong phai tin hieu."""
    if bo.empty:
        pytest.skip("khong co tin hieu")
    so_nen = bo.attrs["so_moc"] * len(frames)
    assert len(bo) < so_nen * 0.5


# ==========================================================
# Vi tri nen
# ==========================================================
def test_vi_tri_dem_theo_nen_cua_lich_su_day_du(bo):
    """`_i` phai trai rong theo so NEN, khong phai theo so tin hieu."""
    if bo.empty:
        pytest.skip("khong co tin hieu")
    so_moc = bo.attrs["so_moc"]
    assert bo["_i"].max() < so_moc
    # Tin hieu thua thot: khoang cach lon nhat giua hai `_i` lien tiep phai > 1,
    # tuc chung KHONG duoc danh so lien tuc 0,1,2,...
    mot_ma = bo[bo["symbol"] == bo["symbol"].iloc[0]]["_i"].to_numpy()
    if len(mot_ma) > 5:
        assert np.diff(mot_ma).max() > 1


def test_cung_mot_moc_thi_moi_ma_co_cung_vi_tri(bo):
    if bo.empty:
        pytest.skip("khong co tin hieu")
    assert (bo.groupby("timestamp")["_i"].nunique() == 1).all()


# ==========================================================
# Bien do va nguong
# ==========================================================
def test_hoa_von_tinh_tu_bien_do_thuc_khong_tu_ty_le_barrier():
    """TP 3xATR / SL 2xATR noi hoa von 40%, nhung bien do THUC quyet dinh."""
    d = pd.DataFrame({"ret": [0.06] * 4 + [-0.04] * 6})
    bd = meta_label.bien_do_thuc(d)
    assert bd["lai"] == pytest.approx(0.06)
    assert bd["lo"] == pytest.approx(-0.04)
    assert bd["p_hoa_von"] == pytest.approx(0.04 / 0.10)


def test_ky_vong_bang_khong_dung_tai_diem_hoa_von():
    bd = {"lai": 0.06, "lo": -0.04, "p_hoa_von": 0.4}
    assert meta_label.ky_vong(np.array([0.4]), bd)[0] == pytest.approx(0.0)
    assert meta_label.ky_vong(np.array([0.5]), bd)[0] > 0
    assert meta_label.ky_vong(np.array([0.3]), bd)[0] < 0


def test_chon_nguong_khong_ra_ngoai_vung_cong_chap_nhan():
    """Bo chon nguong va cong phai dong y ve vung kha thi.

    Neu bo chon duoc tu do chon mot nguong giu 4% trong khi cong doi 15-90% thi
    no luon sinh ra mot bo loc ma cong chac chan tu choi, va khong ai doc ra
    duoc rang hai lop dang bat dong.
    """
    cfg = make_cfg(GATE_META_TY_LE_GIU_MIN=0.20, GATE_META_TY_LE_GIU_MAX=0.80)
    rng = np.random.default_rng(0)
    p = rng.uniform(0.3, 0.6, size=400)
    # Chi 5% tot nhat co lai - toi da hoa tho se muon chon dung nhom do
    ret = np.where(p > np.quantile(p, 0.95), 0.10, -0.01)
    bd = {"lai": 0.10, "lo": -0.01, "p_hoa_von": 0.09}

    nguong, _ = meta_train.chon_nguong(p, ret, bd, cfg)
    giu = (p >= nguong).mean()
    assert 0.20 <= giu <= 0.80, "nguong %.4f giu %.3f - ra ngoai vung cong" % (nguong, giu)


def test_khong_nguong_nao_co_lai_thi_lui_ve_hoa_von_ly_thuyet():
    cfg = make_cfg()
    p = np.linspace(0.3, 0.6, 200)
    ret = np.full(200, -0.02)          # moi tin hieu deu lo
    bd = {"lai": 0.05, "lo": -0.02, "p_hoa_von": 0.2857}
    nguong, chi_tiet = meta_train.chon_nguong(p, ret, bd, cfg)
    assert chi_tiet["cach_chon"] == "hoa_von_ly_thuyet"
    assert nguong == pytest.approx(meta_train.nguong_hoa_von(bd, cfg))


# ==========================================================
# Mo phong loc luon di kem ban doi chung
# ==========================================================
def test_mo_phong_loc_luon_bao_kem_ban_khong_loc():
    te = pd.DataFrame({"ret": [0.05, -0.02, 0.04, -0.03, -0.02]})
    p = np.array([0.9, 0.1, 0.8, 0.2, 0.15])
    kq = meta_train.mo_phong_loc(p, te, 0.5, {"p_hoa_von": 0.4})
    assert kq["so_lenh_giu"] == 2
    assert kq["ky_vong"] == pytest.approx(0.045)
    assert kq["ky_vong_khong_loc"] == pytest.approx(te["ret"].mean())
    assert kq["cai_thien"] == pytest.approx(kq["ky_vong"] - kq["ky_vong_khong_loc"])


def test_loc_het_thi_bao_khong_lenh_nao_chu_khong_no():
    te = pd.DataFrame({"ret": [0.05, -0.02]})
    kq = meta_train.mo_phong_loc(np.array([0.1, 0.1]), te, 0.9, {"p_hoa_von": 0.4})
    assert kq["so_lenh_giu"] == 0
    assert kq["ky_vong"] == 0.0


# ==========================================================
# Purged K-fold
# ==========================================================
def _bo_gia(n=1500, so_ma=3, buoc=4):
    """Bo tin hieu gia lap du lon de K-fold chay that.

    Du lieu tong hop chi sinh ~115 tin hieu breakout tren 8 ma - khong du de
    fold nao dat nguong toi thieu, va mot test luon bi bo qua thi khong bao ve
    duoc gi. O day dung du lieu dat thang de bo test luon chay.
    """
    rng = np.random.default_rng(0)
    dong = []
    for k in range(n):
        for m in range(so_ma):
            dong.append({"_i": k * buoc, "symbol": "MA%d" % m, "bars_held": 2,
                         "y": int(rng.random() < 0.45), "ret": rng.normal(0, 0.02),
                         "a": rng.normal(), "b": rng.normal()})
    return pd.DataFrame(dong)


def test_kfold_cho_du_doan_ngoai_mau_tren_ca_vung_train():
    tr = _bo_gia()
    so_moc = int(tr["_i"].max()) + 1
    p, vong = meta_train.du_doan_ngoai_mau(tr, ["a", "b"], 0, so_moc,
                                           MAX_HORIZON, so_moc, seed=0, so_fold=4)
    assert np.isfinite(p).sum() > len(tr) * 0.8, "K-fold phai phu gan het vung train"
    assert len(vong) == 4


def test_kfold_purge_bo_mau_co_nhan_cham_vao_fold_test():
    """Mau o cuoi mot fold train co nhan keo sang fold test phai bi loai."""
    n = 800
    tr = pd.DataFrame({
        "_i": np.arange(n), "symbol": "X", "bars_held": 30,
        "y": np.arange(n) % 2, "ret": 0.01,
        "a": np.linspace(0, 1, n), "b": 1.0,
    })
    # Fold 2 cua 4 nam o [400, 600). Voi bars_held=30, moi mau tu 370 tro di
    # deu cham vao no va phai bi purge khoi tap train cua fold do.
    p, _ = meta_train.du_doan_ngoai_mau(tr, ["a", "b"], 0, n, 10, n, seed=0, so_fold=4)
    assert np.isfinite(p).sum() > 0


def test_kfold_khong_lay_tuong_lai_lam_train():
    """Fold phai la doan LIEN MACH theo thoi gian, khong xao tron ngau nhien.

    Xao tron se cho mo hinh nhin thay tuong lai cua chinh no - va tren du lieu
    tai chinh do la kieu ro ri cho ra ket qua dep nhat, nen no rat de duoc tin.
    """
    n = 600
    df = pd.DataFrame({
        "_i": np.arange(n), "symbol": "X", "bars_held": 0,
        "y": np.arange(n) % 2, "ret": 0.01,
        "a": np.arange(n, dtype=float), "b": 1.0,
    })
    p, _ = meta_train.du_doan_ngoai_mau(df, ["a", "b"], 0, n, 5, n, seed=0, so_fold=4)
    co = np.isfinite(p)
    # Moi vung duoc du doan phai la mot doan lien mach, khong phai rai rac
    doan = np.split(np.flatnonzero(co), np.flatnonzero(np.diff(np.flatnonzero(co)) > 1) + 1)
    assert len(doan) <= 4


# ==========================================================
# Lop suy luan: mac dinh la CHO QUA
# ==========================================================
class _BoosterGia:
    def __init__(self, p):
        self.p = p

    def predict(self, X):
        return np.full(len(X), self.p)


def _policy(p_thang=0.6, nguong=0.5, cfg=None, cot=None):
    cfg = cfg or make_cfg()
    cot = cot or ["mom_6", "adx", "la_mua", "suc_manh_luat",
                  "regime_trend", "regime_range", "regime_bien_dong"]
    mp = MetaPolicy.__new__(MetaPolicy)
    mp.cfg = cfg
    mp.kho = None
    mp._van_tay_loi = None
    mp._mtime = 0.0
    mp.mo_hinh = model_store.MoHinhPolicy(
        "v_test", _BoosterGia(p_thang), None,
        {"loai": model_store.META, "cot_dac_trung": cot, "nguong": nguong,
         "chien_luoc_nguon": ["breakout"],
         "bien_do": {"lai": 0.06, "lo": -0.04, "p_hoa_von": 0.4}})
    return mp


def _hang(**kw):
    d = {"mom_6": 0.01, "adx": 25.0, "n_ma": 20}
    d.update(kw)
    return pd.Series(d)


def test_tren_nguong_thi_giu_nguyen_tin_hieu():
    kq = _policy(0.62, 0.55).danh_gia(_hang(), BUY, 0.8, "trend")
    assert kq.quyet_dinh == GIU
    assert kq.he_so == 1.0


def test_sat_duoi_nguong_thi_giam_chu_khong_chan():
    cfg = make_cfg(META_VUNG_GIAM=0.05, POLICY_FILTER_GIAM=0.5)
    kq = _policy(0.52, 0.55, cfg).danh_gia(_hang(), BUY, 0.8, "trend")
    assert kq.quyet_dinh == GIAM
    assert kq.he_so == 0.5


def test_duoi_han_thi_chan():
    cfg = make_cfg(META_VUNG_GIAM=0.02)
    kq = _policy(0.30, 0.55, cfg).danh_gia(_hang(), BUY, 0.8, "trend")
    assert kq.quyet_dinh == CHAN
    assert kq.he_so == 0.0


def test_bo_loc_khong_bao_gio_lam_tin_hieu_manh_len():
    """Bat bien kien truc: he so luon <= 1.0 o moi muc xac suat.

    Mot lop LOC lam tin hieu manh len thi no da tro thanh mot NGUON tin hieu,
    va nguon tin hieu phai di qua cong thang cap rieng cua no.
    """
    for p in (0.01, 0.3, 0.5, 0.7, 0.99):
        assert _policy(p, 0.55).danh_gia(_hang(), BUY, 0.8, "trend").he_so <= 1.0


def test_thieu_dac_trung_thi_khong_y_kien_va_CHO_QUA():
    """Mac dinh khi khong chac la CHO QUA, khac han MLPolicy (mac dinh HOLD).

    O day ta dang xen vao mot tin hieu da qua kiem dinh cua chien luoc luat.
    Chan no vi mot ly do ky thuat la thay mot quyet dinh co co so bang mot
    quyet dinh khong co co so nao.
    """
    kq = _policy().danh_gia(pd.Series({"mom_6": 0.01, "n_ma": 20}), BUY, 0.8, "trend")
    assert kq.quyet_dinh == KHONG_Y_KIEN
    assert kq.co_y_kien is False
    assert kq.he_so == 1.0


def test_dac_trung_NaN_thi_khong_y_kien():
    kq = _policy().danh_gia(_hang(adx=float("nan")), BUY, 0.8, "trend")
    assert kq.co_y_kien is False
    assert "adx" in kq.ly_do


def test_qua_it_ma_thi_khong_y_kien_khi_co_cot_xep_hang():
    cot = ["mom_6", "adx", "mom_6_r", "la_mua", "suc_manh_luat",
           "regime_trend", "regime_range", "regime_bien_dong"]
    kq = _policy(cfg=make_cfg(POLICY_MIN_MA=8), cot=cot).danh_gia(
        _hang(n_ma=3, mom_6_r=0.9), BUY, 0.8, "trend")
    assert kq.co_y_kien is False
    assert "ma" in kq.ly_do


def test_booster_no_thi_khong_lam_sap_vong_giao_dich():
    class BoosterNo:
        def predict(self, X):
            raise RuntimeError("hong")

    mp = _policy()
    mp.mo_hinh.booster_long = BoosterNo()
    kq = mp.danh_gia(_hang(), BUY, 0.8, "trend")
    assert kq.co_y_kien is False
    assert kq.he_so == 1.0


def test_danh_gia_khong_sua_dong_panel_goc():
    """Gan dac trung tin hieu vao ban sao. Sua hang goc se lam ban ky uc cua
    vong lap: ma sau doc phai gia tri cua ma truoc."""
    h = _hang()
    truoc = h.to_dict()
    _policy().danh_gia(h, BUY, 0.8, "trend")
    assert h.to_dict() == truoc


def test_mo_hinh_hai_chieu_bi_tu_choi_lam_bo_loc():
    """Champion cua kho AI policy khong duoc dung lam bo loc - hai loai mo hinh
    tra loi hai cau hoi khac han nhau."""
    mp = _policy()
    mp.mo_hinh.meta["loai"] = model_store.HAI_CHIEU
    assert mp.mo_hinh.la_meta is False
