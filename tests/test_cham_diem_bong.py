"""
Kiem tra cham diem che do BONG.

VAN DE MA LOP NAY SUA: cong thang cap len `chu_dong` truoc day chi dem NGAY.
14 ngay im lang qua cong y het 14 ngay tot - va nhu vay che do bong chi la mot
khoang cho, tao ra cam giac an toan ma khong tao ra bang chung.

BA BAT BIEN:
  1. Chua du so tin hieu thi KHONG du bang chung, du ky vong co dep den dau.
     Ky vong tren 5 lenh la nhieu, khong phai ket qua.
  2. Ky vong AM thi khong bao gio du bang chung. Chay bong lau hon khong sua
     duoc mot bien do am.
  3. Lop CHAM DIEM hong khong duoc bien thanh lop CHAN. Khong cham duoc thi
     quay ve dieu kien so ngay nhu cu, chu khong lam ket cung ca kho.
"""
import time

import pytest

from src import cham_diem_bong
from src.storage import Storage
from src.strategies import kho_luat as kl


@pytest.fixture
def st(tmp_path):
    return Storage(db_path=str(tmp_path / "t.db"))


def them_tin_hieu(st, ten, n, ret, action="BUY", da_cham=True):
    """Them n tin hieu bong. Chi cham diem CHINH n dong vua them - khong dung
    lai cac dong da co, neu khong mot lan goi sau se ghi de ket qua cua lan
    truoc va lam test do nham thu khac.
    """
    with st.conn() as c:
        truoc = c.execute("SELECT COALESCE(MAX(id), 0) AS m FROM shadow_signals"
                          ).fetchone()["m"]
    for i in range(n):
        st.log_shadow_signal("BTCUSDT", ten, action, 0.6, 100.0,
                             bar_ts=1_700_000_000_000 + i * 60_000)
    if da_cham:
        with st.conn() as c:
            ids = [r["id"] for r in c.execute(
                "SELECT id FROM shadow_signals WHERE chien_luoc=? AND id > ?",
                (ten, truoc))]
        for i in ids:
            st.cap_nhat_ket_qua_shadow(i, ret)


# ==========================================================
# Cham diem
# ==========================================================
class TestDiemShadow:
    def test_dem_dung_va_tinh_ky_vong(self, st):
        them_tin_hieu(st, "a", 10, 0.01)
        d = st.diem_shadow("a")
        assert d["so_tin_hieu_da_cham"] == 10
        assert d["ky_vong_moi_lenh"] == pytest.approx(0.01)
        assert d["ty_le_thang"] == 1.0

    def test_tin_hieu_chua_cham_khong_tinh_vao_ky_vong(self, st):
        them_tin_hieu(st, "a", 5, 0.01)
        them_tin_hieu(st, "a", 3, 0, da_cham=False)
        d = st.diem_shadow("a")
        assert d["so_tin_hieu_da_cham"] == 5
        assert d["so_tin_hieu_cho_cham"] == 3

    def test_HOLD_khong_tinh_vao_ky_vong_moi_lenh(self, st):
        """Ghi ca HOLD de ho so khong thien lech chon mau, nhung ky vong moi
        lenh chi co nghia tren nhung lan chien luoc thuc su muon vao lenh.
        """
        them_tin_hieu(st, "a", 5, 0.02, action="BUY")
        them_tin_hieu(st, "a", 50, -0.09, action="HOLD")
        d = st.diem_shadow("a")
        assert d["so_tin_hieu_da_cham"] == 5
        assert d["ky_vong_moi_lenh"] == pytest.approx(0.02)

    def test_chien_luoc_chua_co_tin_hieu(self, st):
        d = st.diem_shadow("chua_co")
        assert d["so_tin_hieu_da_cham"] == 0
        assert d["ky_vong_moi_lenh"] is None


class TestDanhGia:
    def test_du_tin_hieu_va_ky_vong_duong_thi_du_bang_chung(self, st):
        them_tin_hieu(st, "tot", cham_diem_bong.SO_TIN_HIEU_TOI_THIEU, 0.008)
        d = cham_diem_bong.danh_gia(st, "tot")
        assert d["du_bang_chung"] is True

    def test_it_tin_hieu_thi_khong_du_du_ky_vong_dep(self, st):
        """Ky vong +5% tren 5 lenh van la nhieu."""
        them_tin_hieu(st, "it", 5, 0.05)
        d = cham_diem_bong.danh_gia(st, "it")
        assert d["du_bang_chung"] is False
        assert "tin hieu da cham" in d["ly_do"]

    def test_ky_vong_am_thi_khong_bao_gio_du(self, st):
        them_tin_hieu(st, "am", 100, -0.002)
        d = cham_diem_bong.danh_gia(st, "am")
        assert d["du_bang_chung"] is False
        assert "am sau phi" in d["ly_do"]

    def test_ky_vong_bang_khong_van_qua(self, st):
        """Cong nay chi doi 'dung dau', khong doi 'dep'. Dat nguong cao hon se
        lap lai bay chon-cai-dep-nhat tren mau nho ma Strategy Lab da tranh.
        """
        them_tin_hieu(st, "hoa", 50, 0.0)
        assert cham_diem_bong.danh_gia(st, "hoa")["du_bang_chung"] is True


# ==========================================================
# Cong thang cap: ngay VA bang chung
# ==========================================================
@pytest.fixture
def kho(tmp_path):
    k = kl.KhoLuat(duong_dan=str(tmp_path / "kho.json"))
    k.them_ung_vien({"ten": "thu", "long": [["rsi", "<", 30]]},
                    {"qua_cong": True, "sharpe_min": 1.4, "tong_lenh": 120})
    k.thang_cap("thu")                       # -> bong
    # gia lap da chay bong du lau
    data = k._doc()
    data["muc"]["thu"]["vao_bong_luc"] = time.time() - (kl.NGAY_BONG_TOI_THIEU + 1) * 86400
    k._ghi(data)
    return k


class TestCongBangChung:
    def test_du_ngay_nhung_thieu_bang_chung_thi_bi_chan(self, kho, st):
        them_tin_hieu(st, "thu", 3, 0.01)
        with pytest.raises(kl.KhoLuatLoi, match="CHUA du bang chung"):
            kho.thang_cap("thu", storage=st)
        assert kho.lay("thu")["trang_thai"] == kl.BONG

    def test_du_ngay_va_du_bang_chung_thi_len_duoc(self, kho, st):
        them_tin_hieu(st, "thu", cham_diem_bong.SO_TIN_HIEU_TOI_THIEU, 0.01)
        assert kho.thang_cap("thu", storage=st)["trang_thai"] == kl.CHU_DONG

    def test_ky_vong_am_thi_chan_du_da_chay_rat_lau(self, kho, st):
        them_tin_hieu(st, "thu", 200, -0.003)
        with pytest.raises(kl.KhoLuatLoi, match="am sau phi"):
            kho.thang_cap("thu", storage=st)

    def test_ep_bo_qua_ca_bang_chung(self, kho, st):
        them_tin_hieu(st, "thu", 2, -0.05)
        assert kho.thang_cap("thu", ep=True, storage=st)["trang_thai"] == kl.CHU_DONG

    def test_khong_co_storage_thi_quay_ve_dieu_kien_so_ngay(self, kho):
        """Lop DO khong duoc tu bien thanh lop CHAN: khong cham duoc diem thi
        van hanh xu nhu truoc khi co lop nay, chu khong lam ket cung ca kho.
        """
        assert kho.thang_cap("thu")["trang_thai"] == kl.CHU_DONG

    def test_module_cham_diem_hong_khong_lam_ket_kho(self, kho, st, monkeypatch):
        def no(*a, **k):
            raise RuntimeError("hong")
        monkeypatch.setattr(cham_diem_bong, "danh_gia", no)
        assert kho.thang_cap("thu", storage=st)["trang_thai"] == kl.CHU_DONG

    def test_chua_du_ngay_van_chan_truoc_khi_xet_bang_chung(self, st, tmp_path):
        k = kl.KhoLuat(duong_dan=str(tmp_path / "k2.json"))
        k.them_ung_vien({"ten": "moi", "long": [["rsi", "<", 30]]},
                        {"qua_cong": True, "sharpe_min": 1.4, "tong_lenh": 120})
        k.thang_cap("moi")
        them_tin_hieu(st, "moi", 100, 0.02)     # bang chung rat dep
        with pytest.raises(kl.KhoLuatLoi, match="ngay"):
            k.thang_cap("moi", storage=st)


# ==========================================================
# Dien ket qua tu du lieu thi truong
# ==========================================================
class TestDienKetQua:
    def test_khong_co_gi_cho_thi_tra_ve_0(self, st):
        assert cham_diem_bong.dien_ket_qua(st, ["BTCUSDT"], "240") == 0

    def test_tin_hieu_qua_moi_thi_chua_cham(self, st):
        """Barrier chua nga ngu thi cham diem la doan."""
        st.log_shadow_signal("BTCUSDT", "a", "BUY", 0.6, 100.0,
                             bar_ts=int(time.time() * 1000))
        assert cham_diem_bong.dien_ket_qua(st, ["BTCUSDT"], "240") == 0
        assert st.diem_shadow("a")["so_tin_hieu_da_cham"] == 0
