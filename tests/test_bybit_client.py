"""
Kiem tra chan doan ket noi cua BybitClient.

TRONG TAM: nut "Thu ket noi" phai TACH DUOC hai kieu hong ma san gop chung
thanh mot loi 401 kho hieu.

    khoa KHONG TON TAI o san nay   -> tao khoa moi tai testnet.bybit.com
    khoa co that nhung THIEU QUYEN -> sua quyen tren chinh khoa do

Hai cai do sua theo hai cach hoan toan khac nhau. Doan nham thi nguoi dung se
di lat tung quyen mot trong khi van de la ho dang o nham san - va chuyen do
that su da xay ra ngay 2026-09-10, mat mot buoi.

Toan bo test o day dung phien gia lap: khong goi mang, khong can khoa that.
"""
import pytest

from src.bybit_client import BybitClient
from tests.conftest import make_cfg


class _PhienGia:
    """Gia lap pybit HTTP: moi endpoint tra ve gia tri dat san hoac nem loi."""

    def __init__(self, info=None, info_loi=None, so_du=None, so_du_loi=None):
        self._info, self._info_loi = info, info_loi
        self._so_du, self._so_du_loi = so_du, so_du_loi

    def get_api_key_information(self):
        if self._info_loi:
            raise Exception(self._info_loi)
        return self._info or {"retCode": 0, "result": {}}

    def get_wallet_balance(self, accountType=None):
        if self._so_du_loi:
            raise Exception(self._so_du_loi)
        return self._so_du or {"retCode": 0, "result": {"list": []}}


def _client(phien):
    c = BybitClient.__new__(BybitClient)
    c.cfg = make_cfg()
    c.session = phien
    return c


LOI_10003 = ("API key is invalid. (ErrCode: 10003) (ErrTime: 12:45:46). "
             "Request -> GET https://api-testnet.bybit.com/v5/user/query-api")
LOI_401 = ("Http status code is not 200. (ErrCode: 401) (ErrTime: 12:44:02). "
           "Request -> GET https://api-testnet.bybit.com/v5/account/wallet-balance")


# ==========================================================
# Khoa khong ton tai
# ==========================================================
def test_khoa_khong_ton_tai_thi_noi_thang_va_chi_dung_cho():
    """10003 la cau tra loi dut khoat nhat san cho duoc - phai noi thang."""
    kq = _client(_PhienGia(info_loi=LOI_10003)).kiem_tra_ket_noi()
    assert kq["ok"] is False
    assert kq["khoa_khong_ton_tai"] is True
    assert "testnet.bybit.com" in kq["chi_tiet"]


def test_retCode_khac_0_o_query_api_cung_la_khoa_khong_hop_le():
    kq = _client(_PhienGia(info={"retCode": 10003,
                                 "retMsg": "API key is invalid"})).kiem_tra_ket_noi()
    assert kq["ok"] is False
    assert kq["khoa_khong_ton_tai"] is True


def test_khoa_khong_ton_tai_thi_KHONG_do_loi_cho_quyen():
    """Loi cu dieu huong nguoi dung di kiem tra quyen - sai huong hoan toan."""
    kq = _client(_PhienGia(info_loi=LOI_10003)).kiem_tra_ket_noi()
    assert "quyen" not in kq["chi_tiet"].lower()


# ==========================================================
# Khoa co that nhung khong doc duoc so du
# ==========================================================
def test_khoa_hop_le_nhung_so_du_401_thi_huong_ve_QUYEN_chu_khong_ve_san():
    kq = _client(_PhienGia(info={"retCode": 0, "result": {}},
                           so_du_loi=LOI_401)).kiem_tra_ket_noi()
    assert kq["ok"] is False
    assert not kq.get("khoa_khong_ton_tai")
    assert "quyen" in kq["chi_tiet"].lower()
    # Khong duoc khuyen di tao khoa moi: khoa nay CO THAT. Kiem tren chinh cau
    # khuyen chu khong tren ten mien - ten mien con xuat hien trong URL cua
    # thong bao loi tho, va bat vao do la bat nham mot thu vo hai.
    assert "phai duoc tao tai" not in kq["chi_tiet"]


def test_bao_ro_loai_tai_khoan_dang_hoi():
    """Tai khoan khong phai UNIFIED la mot nguyen nhan that va hay gap."""
    kq = _client(_PhienGia(info={"retCode": 0},
                           so_du_loi=LOI_401)).kiem_tra_ket_noi("CONTRACT")
    assert "CONTRACT" in kq["chi_tiet"]


def test_so_du_tra_ve_rong_thi_bao_dung_la_khoa_van_on():
    kq = _client(_PhienGia(info={"retCode": 0},
                           so_du={"retCode": 0, "result": {"list": []}})).kiem_tra_ket_noi()
    assert kq["ok"] is False
    assert "khoa dung" in kq["chi_tiet"]


# ==========================================================
# Duong thanh cong
# ==========================================================
def test_khoa_tot_thi_bao_so_du():
    kq = _client(_PhienGia(
        info={"retCode": 0},
        so_du={"retCode": 0,
               "result": {"list": [{"totalEquity": "1234.5"}]}})).kiem_tra_ket_noi()
    assert kq["ok"] is True
    assert "1234.50" in kq["chi_tiet"]


def test_khong_bao_gio_nem_ngoai_le_len_tren():
    """Nut chan doan ma tu no no thi khong chan doan duoc gi."""
    for phien in (_PhienGia(info_loi="mang hong"),
                  _PhienGia(info={"retCode": 0}, so_du_loi="mang hong"),
                  _PhienGia(info={"retCode": 0}, so_du={"retCode": 99, "retMsg": "la"})):
        kq = _client(phien).kiem_tra_ket_noi()
        assert kq["ok"] is False
        assert kq["chi_tiet"]
