"""
Kiem tra vong hoc lien tuc: cong thang cap, bay ro ri, va duong ha cap.

HAI TEST QUAN TRONG NHAT TRONG CA DU AN NAM O DAY:

  test_ban_dac_trung_ro_ri_vao_thi_vong_hoc_phai_bat_duoc
      Ban mot cot bang dung ket qua tuong lai vao bo dac trung roi chay ca vong
      hoc that. No PHAI tu choi va bao nghi ro ri. Neu test nay hong, moi con so
      khac ma he thong bao cao deu khong dung duoc - va se khong co dau hieu nao
      khac cho biet dieu do.

  test_du_lieu_khong_co_tin_hieu_thi_cong_tu_choi
      Chay tren du lieu ngau nhien thuan tuy. Cong PHAI tu choi. Mot vong hoc
      lien tuc nao cung thang cap la mot vong duoi theo nhieu, va tren du lieu
      tai chinh do la trang thai mac dinh neu khong ai chan lai.
"""
import numpy as np
import pandas as pd
import pytest

from src import continual, datafeed, features, model_store, policy_train
from src import validation as val_mod
from src.storage import Storage
from tests.conftest import make_cfg

MAX_HORIZON = 15


# ==========================================================
# Cong thang cap - kiem tren chi so gia lap (nhanh)
# ==========================================================
def _kq(auc=0.56, ic=0.02, ic_t=3.0, so_lenh=200, ky_vong=0.003, pf=1.4,
        ty_le=0.15, auc_xao=0.50, val_hd=800, so_moc=120):
    kq = policy_train.KetQuaHuanLuyen()
    kq.booster_long = object()
    kq.booster_short = object()
    kq.so_dong = {"train": 20000, "val_hieu_dung": val_hd}
    kq.chi_so = {"auc_tb": auc, "ic": ic, "ic_t": ic_t, "so_moc_ic": so_moc,
                 "so_lenh": so_lenh, "loi_nhuan_tb": ky_vong, "profit_factor": pf,
                 "ty_le_vao_lenh": ty_le}
    kq.chi_so_xao = {"auc_tb": auc_xao}
    return kq


CFG = make_cfg()


def test_mo_hinh_tot_thi_qua_cong():
    cong = continual.cong_thang_cap(_kq(), None, CFG)
    assert cong.dat is True
    assert cong.canh_bao_ro_ri is False


def test_khong_co_ky_nang_thi_truot():
    assert continual.cong_thang_cap(_kq(auc=0.50, ic=0.0, ic_t=0.2), None, CFG).dat is False


def test_ic_duong_nhung_khong_dang_ke_thi_truot():
    """IC 0.02 voi t=0.8 la nhieu, khong phai tin hieu."""
    assert continual.cong_thang_cap(_kq(ic_t=0.8), None, CFG).dat is False


def test_auc_qua_cao_thi_bi_coi_la_nghi_ro_ri_chu_khong_phai_gioi():
    """Tren du lieu gia, AUC 0.9 gan nhu luon la dac trung nhin thay tuong lai."""
    cong = continual.cong_thang_cap(_kq(auc=0.92), None, CFG)
    assert cong.dat is False
    assert cong.canh_bao_ro_ri is True


def test_nhan_xao_tron_van_dep_thi_dung_lai_ngay():
    """Doi chung hong thi moi so lieu khac vo nghia - phai dung, khong cham tiep."""
    cong = continual.cong_thang_cap(_kq(auc_xao=0.70), None, CFG)
    assert cong.dat is False
    assert cong.canh_bao_ro_ri is True
    assert any("RO RI" in d for d in cong.dong)


def test_lai_tren_giay_nhung_lo_sau_phi_thi_truot():
    assert continual.cong_thang_cap(_kq(ky_vong=-0.001), None, CFG).dat is False


def test_qua_it_lenh_thi_truot_du_chi_so_dep():
    assert continual.cong_thang_cap(_kq(so_lenh=10), None, CFG).dat is False


def test_qua_it_mau_kiem_dinh_thi_truot():
    assert continual.cong_thang_cap(_kq(val_hd=50), None, CFG).dat is False


def test_doi_vao_lenh_qua_thuong_xuyen_thi_truot():
    """Mo hinh muon vao lenh o 80% so nen la mo hinh chua hoc duoc rang phan lon
    thoi diem khong dang giao dich sau khi tru phi."""
    assert continual.cong_thang_cap(_kq(ty_le=0.8), None, CFG).dat is False


def test_khong_hon_champion_thi_khong_thang_cap():
    champ = {"auc_tb": 0.58, "loi_nhuan_tb": 0.004}
    assert continual.cong_thang_cap(_kq(auc=0.56, ky_vong=0.003), champ, CFG).dat is False


def test_hon_champion_du_bien_thi_thang_cap():
    champ = {"auc_tb": 0.53, "loi_nhuan_tb": 0.001}
    assert continual.cong_thang_cap(_kq(auc=0.56, ky_vong=0.003), champ, CFG).dat is True


def test_hon_champion_qua_it_thi_khong_doi_mo_hinh():
    """Doi mo hinh vi 0.001 AUC la doi vi nhieu - va moi lan doi la mat ho so
    ket qua truc tuyen dang tich luy."""
    champ = {"auc_tb": 0.559, "loi_nhuan_tb": 0.001}
    assert continual.cong_thang_cap(_kq(auc=0.560), champ, CFG).dat is False


def test_huan_luyen_that_bai_thi_khong_the_qua_cong():
    kq = policy_train.KetQuaHuanLuyen()
    kq.loi = ["khong du du lieu"]
    assert continual.cong_thang_cap(kq, None, CFG).dat is False


# ==========================================================
# Chay that tren panel tong hop
# ==========================================================
def _panel_tong_hop(so_ma=10, n=1500, cfg=None):
    cfg = cfg or make_cfg()
    frames = {"MA%02dUSDT" % k: datafeed.synthetic_ohlcv(n=n, seed=100 + k)
              for k in range(so_ma)}
    return features.xay_panel(frames, cfg, max_horizon=MAX_HORIZON)


@pytest.fixture(scope="module")
def panel():
    return _panel_tong_hop()


@pytest.fixture(scope="module")
def cfg_hoc():
    return make_cfg(GATE_POLICY_MIN_MAU_TRAIN=3000, GATE_POLICY_MIN_MAU_VAL=100)


def _ba_khoi(panel):
    return val_mod.cat_ba_khoi(panel["timestamp"].nunique(), calib_bars=200,
                               val_bars=250, embargo=MAX_HORIZON)


def test_du_lieu_khong_co_tin_hieu_thi_cong_tu_choi(panel, cfg_hoc):
    """Du lieu ngau nhien -> khong co gi de hoc -> phai tu choi.

    Day la ket qua DUNG chu khong phai loi. Neu test nay bat dau pass nguoc lai
    (cong cho qua) thi cong dang bi ha nguong hoac duong ong da ro ri.
    """
    cot = features.cot_dac_trung(co_xep_hang=True)
    kq = policy_train.huan_luyen(panel, cot, _ba_khoi(panel), cfg_hoc, seed=0,
                                 kiem_tra_xao=False)
    assert kq.thanh_cong, kq.loi
    assert continual.cong_thang_cap(kq, None, cfg_hoc).dat is False


def test_ban_dac_trung_ro_ri_vao_thi_vong_hoc_phai_bat_duoc(panel, cfg_hoc):
    """Ban mot cot bang dung ket qua tuong lai vao bo dac trung.

    Mot bo chan ro ri khong the that bai thi khong chung minh duoc dieu gi. Day
    la test lam no that bai co chu dich, va doi no phai keu.
    """
    p = panel.copy()
    p["ro_ri"] = p["ret_long"]          # nhin thang vao ket qua tuong lai
    cot = features.cot_dac_trung(co_xep_hang=True) + ["ro_ri"]

    kq = policy_train.huan_luyen(p, cot, _ba_khoi(p), cfg_hoc, seed=0,
                                 kiem_tra_xao=True)
    assert kq.thanh_cong, kq.loi
    assert kq.chi_so["auc_tb"] > 0.9, "dac trung ro ri phai cho AUC gan hoan hao"

    cong = continual.cong_thang_cap(kq, None, cfg_hoc)
    assert cong.dat is False
    assert cong.canh_bao_ro_ri is True

    # Doi chung nhan xao tron van phai sach: xao nhan pha lien ket dac trung-nhan,
    # nen chinh cot ro ri kia cung tro nen vo dung.
    assert kq.chi_so_xao["auc_tb"] < 0.6


def test_trong_so_duy_nhat_ha_kich_thuoc_mau_ve_muc_that(panel, cfg_hoc):
    """Voi max_horizon=15, cac nhan chong lan nhau: so mau HIEU DUNG phai nho
    hon nhieu so dong tho."""
    cot = features.cot_dac_trung(co_xep_hang=True)
    kq = policy_train.huan_luyen(panel, cot, _ba_khoi(panel), cfg_hoc, seed=0,
                                 kiem_tra_xao=False)
    assert kq.so_dong["val_hieu_dung"] < kq.so_dong["val"] / 5


def test_phep_chia_sai_thu_tu_khong_the_dung_duoc():
    """Khoi train vuot qua khoi calib -> phai no ngay luc dung, khong phai lang
    le chay roi de purge tinh co che mat hau qua."""
    with pytest.raises(ValueError, match="sai thu tu"):
        val_mod.BaKhoi(train_lo=0, train_hi=900, calib_lo=700, calib_hi=800,
                       val_lo=850, val_hi=1000)


def test_khoi_rong_khong_the_dung_duoc():
    with pytest.raises(ValueError, match="rong"):
        val_mod.BaKhoi(train_lo=0, train_hi=500, calib_lo=500, calib_hi=500,
                       val_lo=500, val_hi=700)


def test_khoi_kiem_dinh_qua_ngan_thi_huan_luyen_tu_choi_chay(panel, cfg_hoc):
    """Khong du mau de ket luan -> dung lai truoc khi huan luyen."""
    so_moc = panel["timestamp"].nunique()
    ba_khoi_hep = val_mod.BaKhoi(train_lo=0, train_hi=so_moc - 60,
                                 calib_lo=so_moc - 50, calib_hi=so_moc - 20,
                                 val_lo=so_moc - 10, val_hi=so_moc)
    cot = features.cot_dac_trung(co_xep_hang=True)
    kq = policy_train.huan_luyen(panel, cot, ba_khoi_hep, cfg_hoc, seed=0)
    assert not kq.thanh_cong
    assert any("khong du du lieu" in l for l in kq.loi), kq.loi


# ==========================================================
# Duong ha cap tu dong
# ==========================================================
class _KetQuaGia:
    def __init__(self, action="BUY", pb="v1"):
        self.action, self.phien_ban = action, pb
        self.strength = 0.5
        self.p_long = self.p_short = 0.5
        self.ev_long = self.ev_short = 0.001
        self.ly_do = "test"


def _kho_co_champion(tmp_path, ky_vong_kiem_dinh=0.004, truoc_do=False):
    kho = model_store.KhoModel(str(tmp_path / "models"))

    class B:
        def save_model(self, p):
            open(p, "w").close()

    if truoc_do:
        kho.luu(B(), B(), {"phien_ban": "v0", "chi_so": {"loi_nhuan_tb": 0.002}})
        kho.thang_cap("v0", "cu")
    kho.luu(B(), B(), {"phien_ban": "v1",
                       "chi_so": {"loi_nhuan_tb": ky_vong_kiem_dinh}})
    kho.thang_cap("v1", "moi")
    return kho


def _nap_ket_qua(st, n, loi_nhuan, pb="v1"):
    for k in range(n):
        st.log_policy_prediction("BTCUSDT", 1_700_000_000_000 + k * 60_000,
                                 _KetQuaGia(pb=pb), che_do="shadow")
    with st.conn() as con:
        for r in con.execute("SELECT id FROM policy_predictions").fetchall():
            st.cap_nhat_ket_qua_policy(r["id"], loi_nhuan, -loi_nhuan, "BUY")


def test_chua_du_lenh_thi_khong_ha_cap(tmp_path):
    """Mot mo hinh khong duoc loai vi vai lenh dau tien xau."""
    st = Storage(str(tmp_path / "t.db"))
    kho = _kho_co_champion(tmp_path)
    _nap_ket_qua(st, 5, -0.02)
    kq = continual.theo_doi_champion(st, kho, make_cfg())
    assert kq["trang_thai"] == "chua_du_du_lieu"
    assert kho.champion_hien_tai() == "v1"


def test_lo_that_du_lau_thi_tu_dong_ha_cap(tmp_path):
    st = Storage(str(tmp_path / "t.db"))
    kho = _kho_co_champion(tmp_path, truoc_do=True)
    _nap_ket_qua(st, 60, -0.01)

    kq = continual.theo_doi_champion(st, kho, make_cfg(GATE_POLICY_MIN_LENH_THEO_DOI=40))
    assert kq["trang_thai"] == "da_ha_cap"
    assert kq["champion_moi"] == "v0"
    assert kho.champion_hien_tai() == "v0"


def test_van_co_lai_nhung_suy_giam_manh_thi_ha_cap(tmp_path):
    """Kiem dinh hua 0.004/lenh, thuc te chi 0.0005 - mo hinh khong con mo ta
    thi truong hien tai nua du van duong."""
    st = Storage(str(tmp_path / "t.db"))
    kho = _kho_co_champion(tmp_path, ky_vong_kiem_dinh=0.004)
    _nap_ket_qua(st, 60, 0.0005)
    kq = continual.theo_doi_champion(st, kho, make_cfg(GATE_POLICY_MIN_LENH_THEO_DOI=40))
    assert kq["suy_giam"] is True
    assert kq["trang_thai"] == "da_ha_cap"


def test_ket_qua_khop_kiem_dinh_thi_giu_nguyen(tmp_path):
    st = Storage(str(tmp_path / "t.db"))
    kho = _kho_co_champion(tmp_path, ky_vong_kiem_dinh=0.004)
    _nap_ket_qua(st, 60, 0.005)
    kq = continual.theo_doi_champion(st, kho, make_cfg(GATE_POLICY_MIN_LENH_THEO_DOI=40))
    assert kq["trang_thai"] == "binh_thuong"
    assert kho.champion_hien_tai() == "v1"


def test_khong_co_champion_thi_khong_lam_gi(tmp_path):
    st = Storage(str(tmp_path / "t.db"))
    kho = model_store.KhoModel(str(tmp_path / "models"))
    assert continual.theo_doi_champion(st, kho, make_cfg())["trang_thai"] == "khong_co_champion"


# ==========================================================
# So du doan
# ==========================================================
def test_ghi_ca_nhung_lan_policy_noi_HOLD(tmp_path):
    """Chi ghi luc vao lenh la thien lech chon mau: ta se chi thay ket qua cua
    nhung quyet dinh da chon, va cham diem mo hinh cao hon thuc te."""
    st = Storage(str(tmp_path / "t.db"))
    st.log_policy_prediction("BTCUSDT", 1_700_000_000_000, _KetQuaGia("HOLD"))
    with st.conn() as con:
        assert con.execute("SELECT COUNT(*) c FROM policy_predictions").fetchone()["c"] == 1


def test_ghi_lai_cung_mot_nen_khong_tao_ban_ghi_trung(tmp_path):
    """Vong lap chay 5 phut mot lan tren nen 4h - se gap lai cung mot nen nhieu
    lan. Lan ghi dau tien la lan duy nhat phan anh thong tin luc do."""
    st = Storage(str(tmp_path / "t.db"))
    for _ in range(5):
        st.log_policy_prediction("BTCUSDT", 1_700_000_000_000, _KetQuaGia("BUY"))
    with st.conn() as con:
        assert con.execute("SELECT COUNT(*) c FROM policy_predictions").fetchone()["c"] == 1


def test_thong_ke_chi_tinh_tren_lenh_da_co_ket_qua(tmp_path):
    st = Storage(str(tmp_path / "t.db"))
    _nap_ket_qua(st, 10, 0.01)
    st.log_policy_prediction("ETHUSDT", 1_800_000_000_000, _KetQuaGia("BUY"))  # chua co ket qua
    tk = st.thong_ke_policy("v1")
    assert tk["so_lenh"] == 10
    assert tk["loi_nhuan_tb"] == pytest.approx(0.01)
