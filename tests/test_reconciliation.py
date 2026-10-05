"""
Kiem tra doi soat trang thai khi khoi dong.

Kich ban ma module nay sinh ra de ngan: bot crash luc dang giu vi the, khoi
dong lai, khong biet minh dang co lenh, va mo them lenh nua.

Cai bay tinh vi nhat o day khong phai "doc sai", ma la "khong doc duoc nhung
lai bao cao la sach". Hai truong hop do phai duoc phan biet tuyet doi: mot cai
nghia la san trong that, cai kia nghia la ta dang mu. Coi chung nhu nhau chinh
la dang DOAN - dieu ma docstring cua module cam.
"""
import pytest

from src.reconciliation import reconcile
from tests.conftest import make_cfg


class FakeClient:
    def __init__(self, balances=None, positions=None, orders=None,
                 loi_so_du=False, loi_lenh_cho=False, price=100.0):
        self._balances = balances or {}
        self._positions = positions or []
        self._orders = orders or []
        self.loi_so_du = loi_so_du
        self.loi_lenh_cho = loi_lenh_cho
        self.price = price

    def get_spot_balances(self):
        if self.loi_so_du:
            raise RuntimeError("401 Unauthorized")
        return self._balances

    def get_open_positions(self):
        if self.loi_so_du:
            raise RuntimeError("401 Unauthorized")
        return self._positions

    def get_open_orders(self):
        if self.loi_lenh_cho:
            raise RuntimeError("timeout doc lenh cho")
        return self._orders

    def get_last_price(self, symbol):
        return self.price


SPOT = make_cfg(CATEGORY="spot")
LINEAR = make_cfg(CATEGORY="linear")


# ==========================================================
# Doc that bai KHONG duoc bao cao la sach
# ==========================================================
def test_doc_lenh_cho_that_bai_thi_doi_soat_that_bai():
    """Test hoi quy.

    Truoc day loi doc lenh cho chi bi ghi warning roi bo qua, va doi soat van
    tra ve ok=True kem thong bao "khong co vi the/lenh cho nao tren san".
    Neu tren san dang co lenh cho that, bot se dat chong len no.
    """
    res = reconcile(FakeClient(loi_lenh_cho=True), None, SPOT)

    assert not res.ok, "khong doc duoc lenh cho ma van bao sach - day la dang DOAN"
    assert "lenh cho" in res.message


def test_doc_so_du_that_bai_thi_doi_soat_that_bai():
    res = reconcile(FakeClient(loi_so_du=True), None, SPOT)
    assert not res.ok
    assert "khong doc duoc" in res.message


def test_doc_vi_the_futures_that_bai_thi_doi_soat_that_bai():
    res = reconcile(FakeClient(loi_so_du=True), None, LINEAR)
    assert not res.ok


# ==========================================================
# Duong chay binh thuong
# ==========================================================
def test_san_sach_thi_cho_di_tiep():
    res = reconcile(FakeClient(), None, SPOT)
    assert res.ok
    assert res.exchange_positions == {}


def test_phat_hien_vi_the_spot_dang_co_tren_san():
    res = reconcile(FakeClient(balances={"BTC": 0.5, "USDT": 5000.0}, price=100000.0),
                    None, SPOT)

    assert res.ok
    assert "BTCUSDT" in res.exchange_positions
    assert res.exchange_positions["BTCUSDT"].qty == 0.5
    assert "vi the" in res.message


def test_bo_qua_so_du_bui():
    """So du vai dong le tu cac lan giao dich truoc khong phai la vi the."""
    res = reconcile(FakeClient(balances={"BTC": 0.00001}, price=100000.0), None, SPOT)
    assert res.exchange_positions == {}


def test_usdt_khong_bi_coi_la_vi_the():
    res = reconcile(FakeClient(balances={"USDT": 10000.0, "USDC": 500.0}), None, SPOT)
    assert res.exchange_positions == {}


def test_canh_bao_vi_the_khong_co_stop_loss():
    """Vi the khong stop-loss la rui ro khong gioi han - phai bao that manh."""
    res = reconcile(FakeClient(balances={"BTC": 0.5}, price=100000.0), None, SPOT)
    assert any("KHONG co stop-loss" in d for d in res.discrepancies)


def test_bao_cao_lenh_cho_dang_ton_tai():
    res = reconcile(FakeClient(orders=[{"orderId": "1"}, {"orderId": "2"}]), None, SPOT)
    assert res.ok
    assert "2 lenh cho" in res.message


def test_vi_the_futures_giu_nguyen_huong_va_stop():
    res = reconcile(FakeClient(positions=[
        {"symbol": "BTCUSDT", "side": "Sell", "size": "0.3",
         "avgPrice": "95000", "stopLoss": "97000", "takeProfit": "90000"}]), None, LINEAR)

    pos = res.exchange_positions["BTCUSDT"]
    assert pos.side == "Sell"
    assert pos.stop_loss == pytest.approx(97000.0)
    assert not any("KHONG co stop-loss" in d for d in res.discrepancies)


def test_khong_co_ket_noi_san_thi_bo_qua():
    """Che do backtest/dry-run offline: khong co client thi khong doi soat."""
    res = reconcile(None, None, SPOT)
    assert res.ok
    assert "bo qua doi soat" in res.message
