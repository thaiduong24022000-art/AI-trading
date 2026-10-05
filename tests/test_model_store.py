"""
Kiem tra kho mo hinh - lop bao ve "khong tu pha model dang chay".

Trong tam la cac duong TU CHOI va duong LUI: mot kho mo hinh chi co gia tri khi
no ngan duoc viec de len phien ban cu, va khi duong quay lui chac chan hoat dong
vao luc can den no.
"""
import json
import os

import numpy as np
import pytest

from src import model_store
from tests.conftest import make_cfg


class BoosterGia:
    """Gia lap Booster cua LightGBM: chi can save_model va predict."""

    def __init__(self, gia_tri=0.5):
        self.gia_tri = gia_tri

    def save_model(self, path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("booster gia %s" % self.gia_tri)

    def predict(self, X):
        return np.full(len(X), self.gia_tri)


@pytest.fixture
def kho(tmp_path):
    return model_store.KhoModel(str(tmp_path / "models"))


def _meta(cot=None, cfg=None, max_horizon=60):
    cot = cot or ["a", "b"]
    cfg = cfg or make_cfg()
    return {
        "cot_dac_trung": cot,
        "max_horizon": max_horizon,
        "dau_van_tay": model_store.dau_van_tay(cot, cfg, max_horizon),
        "tham_so_bai_toan": {t: getattr(cfg, t, None)
                             for t in model_store.THAM_SO_BAI_TOAN},
    }


# ==========================================================
# Dau van tay
# ==========================================================
def test_doi_barrier_thi_dau_van_tay_doi():
    cot = ["a", "b"]
    a = model_store.dau_van_tay(cot, make_cfg(ATR_STOP_MULT=2.0))
    b = model_store.dau_van_tay(cot, make_cfg(ATR_STOP_MULT=1.5))
    assert a != b, "doi ATR_STOP_MULT la doi bai toan, van tay phai doi theo"


def test_doi_thu_tu_cot_thi_dau_van_tay_doi():
    """LightGBM an dac trung theo VI TRI cot. Doi thu tu ma van tay khong doi
    thi mo hinh cu se doc nham cot ma khong ai biet."""
    cfg = make_cfg()
    assert (model_store.dau_van_tay(["a", "b"], cfg)
            != model_store.dau_van_tay(["b", "a"], cfg))


def test_cung_cau_hinh_thi_dau_van_tay_on_dinh():
    cfg = make_cfg()
    assert model_store.dau_van_tay(["a"], cfg) == model_store.dau_van_tay(["a"], cfg)


# ==========================================================
# Bat bien
# ==========================================================
def test_luu_tao_thu_muc_day_du(kho):
    pb = kho.luu(BoosterGia(), BoosterGia(), _meta(), the="# the")
    d = os.path.join(kho.thu_muc, pb)
    for ten in ("long.txt", "short.txt", "meta.json", "the_mo_hinh.md"):
        assert os.path.exists(os.path.join(d, ten))


def test_khong_the_ghi_de_phien_ban_da_ton_tai(kho):
    m = _meta()
    m["phien_ban"] = "v_co_dinh"
    kho.luu(BoosterGia(), BoosterGia(), m)
    with pytest.raises(FileExistsError):
        kho.luu(BoosterGia(0.9), BoosterGia(0.9), m)


def test_luu_that_bai_khong_de_lai_thu_muc_ghi_do_dang(kho):
    """Neu ghi hong giua chung, khong duoc de lai mot phien ban nap duoc mot nua."""
    class BoosterHong(BoosterGia):
        def save_model(self, path):
            raise OSError("o dia day")

    m = _meta()
    m["phien_ban"] = "v_hong"
    with pytest.raises(OSError):
        kho.luu(BoosterHong(), BoosterGia(), m)
    assert kho.danh_sach() == []
    assert not os.path.exists(os.path.join(kho.thu_muc, "v_hong"))


def test_luu_khong_tu_dong_thang_cap(kho):
    """Huan luyen xong KHONG dong nghia voi duoc trien khai."""
    kho.luu(BoosterGia(), BoosterGia(), _meta())
    assert kho.champion_hien_tai() is None


# ==========================================================
# Thang cap / ha cap
# ==========================================================
def test_thang_cap_va_lui_mot_buoc(kho):
    m1, m2 = _meta(), _meta()
    m1["phien_ban"], m2["phien_ban"] = "v1", "v2"
    kho.luu(BoosterGia(), BoosterGia(), m1)
    kho.luu(BoosterGia(), BoosterGia(), m2)

    kho.thang_cap("v1", "dau tien")
    assert kho.champion_hien_tai() == "v1"
    kho.thang_cap("v2", "tot hon")
    assert kho.champion_hien_tai() == "v2"

    assert kho.ha_cap("ket qua that kem") == "v1"
    assert kho.champion_hien_tai() == "v1"


def test_ha_cap_khi_khong_con_duong_lui_thi_ve_chay_thuan_luat(kho):
    m = _meta()
    m["phien_ban"] = "v1"
    kho.luu(BoosterGia(), BoosterGia(), m)
    kho.thang_cap("v1", "dau tien")

    assert kho.ha_cap("hong") is None
    assert kho.champion_hien_tai() is None, "khong co mo hinh = trang thai an toan"


def test_khong_thang_cap_duoc_phien_ban_khong_ton_tai(kho):
    with pytest.raises(FileNotFoundError):
        kho.thang_cap("v_khong_co", "thu xem")


def test_champion_json_hong_thi_coi_nhu_khong_co_champion(kho):
    """Tep hong khong duoc lam sap bot - no phai lui ve trang thai an toan."""
    m = _meta()
    m["phien_ban"] = "v1"
    kho.luu(BoosterGia(), BoosterGia(), m)
    kho.thang_cap("v1", "x")
    with open(kho._tep_champion, "w", encoding="utf-8") as f:
        f.write("{ khong phai json")
    assert kho.champion_hien_tai() is None
    assert kho.nap_champion() is None


def test_moi_thay_doi_deu_vao_nhat_ky_su_kien(kho):
    m = _meta()
    m["phien_ban"] = "v1"
    kho.luu(BoosterGia(), BoosterGia(), m)
    kho.thang_cap("v1", "ly do thang cap")
    kho.ha_cap("ly do ha cap")

    loai = [e["loai"] for e in kho.su_kien()]
    assert loai == ["luu", "thang_cap", "ha_cap_hoan_toan"]
    assert any("ly do ha cap" in e.get("ly_do", "") for e in kho.su_kien())


# ==========================================================
# Kiem tra tinh hop le khi nap
# ==========================================================
def test_mo_hinh_hop_le_khi_cau_hinh_khong_doi():
    cfg = make_cfg()
    mh = model_store.MoHinhPolicy("v1", None, None, _meta(["a", "b"], cfg))
    assert mh.hop_le_voi(cfg) is None


def test_doi_atr_stop_mult_thi_mo_hinh_bi_coi_la_khong_hop_le():
    """Kieu hong im lang nguy hiem nhat: mo hinh van nap duoc, van du doan
    binh thuong, nhung dang tra loi mot cau hoi KHAC."""
    cfg_cu = make_cfg(ATR_STOP_MULT=2.0)
    mh = model_store.MoHinhPolicy("v1", None, None, _meta(["a", "b"], cfg_cu))

    cfg_moi = make_cfg(ATR_STOP_MULT=1.5)
    lech = mh.hop_le_voi(cfg_moi)
    assert lech is not None
    assert "ATR_STOP_MULT" in lech
