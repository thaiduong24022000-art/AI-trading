"""
Kiem tra OkxClient - dac biet la cho DICH SANG DINH DANG BYBIT, vi day la
diem neu sai thi loi se im lang: executor.py va reconciliation.py doc thang
cac truong nhu retCode/lotSizeFilter.qtyStep/stopLoss ma khong biet client
phia sau la Bybit hay OKX. Test nay khong goi mang that - moi test tu day
_request()/_raw_candles() bang gia tri gia lap.
"""
import pandas as pd
import pytest

from src.okx_client import (
    OkxClient, _from_okx_symbol, _interval_ms_okx, _to_okx_symbol,
)
from tests.conftest import make_cfg


def make_client(**cfg_overrides):
    base = {"CATEGORY": "spot", "EXCHANGE": "okx"}
    base.update(cfg_overrides)
    cfg = make_cfg(**base)
    return OkxClient(api_key="k", api_secret="s", passphrase="p", testnet=True, cfg=cfg)


# ---------- chuyen doi symbol / khung ----------
class TestChuyenDoiSymbol:
    def test_spot(self):
        assert _to_okx_symbol("BTCUSDT", "SPOT") == "BTC-USDT"

    def test_swap(self):
        assert _to_okx_symbol("BTCUSDT", "SWAP") == "BTC-USDT-SWAP"

    def test_khu_tien_to_1000(self):
        # Ma nhu 1000PEPEUSDT van chi tach 4 ky tu cuoi "USDT", giu nguyen phan con lai.
        assert _to_okx_symbol("1000PEPEUSDT", "SPOT") == "1000PEPE-USDT"

    def test_khu_hoi_ve_dinh_dang_bot(self):
        assert _from_okx_symbol("BTC-USDT") == "BTCUSDT"
        assert _from_okx_symbol("BTC-USDT-SWAP") == "BTCUSDT"

    def test_khu_troi_ve_va_lai(self):
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            for inst_type in ("SPOT", "SWAP"):
                assert _from_okx_symbol(_to_okx_symbol(sym, inst_type)) == sym


class TestKhungGio:
    def test_phut(self):
        assert _interval_ms_okx("240") == 240 * 60 * 1000

    def test_ngay(self):
        assert _interval_ms_okx("D") == 1440 * 60 * 1000


# ---------- khoi tao: doc CATEGORY dung chung voi Bybit, khong tach rieng ----------
class TestKhoiTao:
    def test_category_spot_thanh_inst_type_spot(self):
        c = make_client(CATEGORY="spot")
        assert c.inst_type == "SPOT"
        assert c.td_mode == "cash"

    def test_category_linear_thanh_inst_type_swap(self):
        c = make_client(CATEGORY="linear", OKX_TD_MODE="isolated")
        assert c.inst_type == "SWAP"
        assert c.td_mode == "isolated"


# ---------- dich response OKX -> dinh dang Bybit ma cac module khac dang doc ----------
class TestDichInstrumentInfo:
    def test_shape_giong_bybit(self, monkeypatch):
        c = make_client()
        monkeypatch.setattr(c, "_request", lambda *a, **k: {
            "code": "0", "data": [{"instId": "BTC-USDT", "lotSz": "0.00001",
                                   "minSz": "0.00001", "tickSz": "0.1"}]})
        info = c.get_instrument_info("BTCUSDT")
        # executor._round_qty() doc dung hai truong nay - sai ten la lam tron sai lang le.
        assert info["lotSizeFilter"]["qtyStep"] == "0.00001"
        assert info["lotSizeFilter"]["minOrderQty"] == "0.00001"

    def test_rong_khi_khong_co_du_lieu(self, monkeypatch):
        c = make_client()
        monkeypatch.setattr(c, "_request", lambda *a, **k: {"code": "0", "data": []})
        assert c.get_instrument_info("BTCUSDT") is None


class TestDatLenh:
    def _client_voi_response(self, monkeypatch, response):
        c = make_client()
        monkeypatch.setattr(c, "_request", lambda *a, **k: response)
        return c

    def test_thanh_cong_tra_ret_code_0(self, monkeypatch):
        c = self._client_voi_response(monkeypatch, {
            "code": "0", "msg": "",
            "data": [{"ordId": "1", "sCode": "0", "sMsg": ""}]})
        resp = c.place_order("BTCUSDT", "Buy", 0.01, order_link_id="bot_abc")
        assert resp["retCode"] == 0

    def test_that_bai_cap_lenh_van_bi_bat_du_top_level_ok(self, monkeypatch):
        # Day la cai bay OKX: code tong the co the la "0" (yeu cau hop le) trong
        # khi tung lenh cu the van that bai (vd het so du) qua sCode rieng.
        # Executor chi doc retCode nen phai gop ca hai lop lai dung.
        c = self._client_voi_response(monkeypatch, {
            "code": "0", "msg": "",
            "data": [{"ordId": "", "sCode": "51008", "sMsg": "khong du so du"}]})
        resp = c.place_order("BTCUSDT", "Buy", 0.01)
        assert resp["retCode"] != 0
        assert "so du" in resp["retMsg"]

    def test_loi_cap_request_cung_bi_bat(self, monkeypatch):
        c = self._client_voi_response(monkeypatch, {
            "code": "50113", "msg": "chu ky khong hop le", "data": []})
        resp = c.place_order("BTCUSDT", "Buy", 0.01)
        assert resp["retCode"] != 0

    def test_side_va_order_type_duoc_ha_thuong(self, monkeypatch):
        """Bybit dung 'Buy'/'Market' (hoa dau) - OKX can chu thuong. Client
        phai tu chuyen, khong duoc bat executor.py tu doi quy uoc.
        """
        goi = {}

        def fake_request(method, path, params=None, body=None, **kw):
            goi["body"] = body
            return {"code": "0", "data": [{"sCode": "0"}]}

        c = make_client()
        monkeypatch.setattr(c, "_request", fake_request)
        c.place_order("BTCUSDT", "Buy", 0.01, order_type="Market")
        assert goi["body"]["side"] == "buy"
        assert goi["body"]["ordType"] == "market"

    def test_spot_dat_tgt_ccy_de_sz_la_so_luong_coin(self, monkeypatch):
        """Neu thieu tgtCcy, OKX hieu sz cua lenh market-buy spot la SO USDT
        muon chi chu khong phai so coin - khac ngu nghia qty ma risk_manager
        tinh ra. Thieu dong nay se lam khoi luong lenh thuc te sai lech rat xa.
        """
        goi = {}
        c = make_client(CATEGORY="spot")
        monkeypatch.setattr(c, "_request",
                            lambda m, p, params=None, body=None, **k:
                            goi.setdefault("body", body) or {"code": "0", "data": [{"sCode": "0"}]})
        c.place_order("BTCUSDT", "Buy", 0.01)
        assert goi["body"]["tgtCcy"] == "base_ccy"


class TestViThe:
    def test_che_do_net_doc_theo_dau_pos(self, monkeypatch):
        c = make_client(CATEGORY="linear")
        monkeypatch.setattr(c, "_request", lambda *a, **k: {"data": [
            {"instId": "BTC-USDT-SWAP", "pos": "-0.5", "avgPx": "60000", "posSide": "net"},
        ]})
        vt = c.get_open_positions()
        assert len(vt) == 1
        assert vt[0]["side"] == "Sell"
        assert vt[0]["size"] == "0.5"
        assert vt[0]["symbol"] == "BTCUSDT"

    def test_che_do_hedge_doc_theo_pos_side(self, monkeypatch):
        c = make_client(CATEGORY="linear")
        monkeypatch.setattr(c, "_request", lambda *a, **k: {"data": [
            {"instId": "ETH-USDT-SWAP", "pos": "2", "avgPx": "3000", "posSide": "long"},
        ]})
        vt = c.get_open_positions()
        assert vt[0]["side"] == "Buy"

    def test_khong_co_tp_sl_gan_tren_vi_the(self, monkeypatch):
        # Day la khac biet kien truc co y voi Bybit - reconciliation.py se luon
        # canh bao "khong co stop-loss" cho vi the OKX. Test nay khoa hanh vi
        # do lai de khong ai vo tinh "sua" no thanh gia tri gia bang cach doan.
        c = make_client(CATEGORY="linear")
        monkeypatch.setattr(c, "_request", lambda *a, **k: {"data": [
            {"instId": "BTC-USDT-SWAP", "pos": "1", "avgPx": "60000", "posSide": "net"},
        ]})
        vt = c.get_open_positions()
        assert vt[0]["stopLoss"] is None
        assert vt[0]["takeProfit"] is None

    def test_vi_the_dong_khong_xuat_hien(self, monkeypatch):
        c = make_client(CATEGORY="linear")
        monkeypatch.setattr(c, "_request", lambda *a, **k: {"data": [
            {"instId": "BTC-USDT-SWAP", "pos": "0", "avgPx": "0", "posSide": "net"},
        ]})
        assert c.get_open_positions() == []


class TestGetKlines:
    def _rows(self, closes, confirms):
        base_ts = 1_700_000_000_000
        return [[str(base_ts + i * 240 * 60_000), "100", "101", "99", str(c), "10",
                "0", "0", conf]
               for i, (c, conf) in enumerate(zip(closes, confirms))]

    def test_bo_nen_dang_chay_qua_truong_confirm(self, monkeypatch):
        c = make_client()
        monkeypatch.setattr(c, "_raw_candles",
                            lambda *a, **k: self._rows([100, 101, 102], ["1", "1", "0"]))
        df = c.get_klines("BTCUSDT")
        assert len(df) == 2
        assert df["close"].iloc[-1] == 101.0

    def test_giu_nguyen_khi_nen_cuoi_da_dong(self, monkeypatch):
        c = make_client()
        monkeypatch.setattr(c, "_raw_candles",
                            lambda *a, **k: self._rows([100, 101, 102], ["1", "1", "1"]))
        df = c.get_klines("BTCUSDT")
        assert len(df) == 3

    def test_rong_khi_khong_co_nen(self, monkeypatch):
        c = make_client()
        monkeypatch.setattr(c, "_raw_candles", lambda *a, **k: [])
        df = c.get_klines("BTCUSDT")
        assert df.empty
        assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]


class TestSessionShim:
    """datafeed.download_history() goi client.session.get_kline(**params) truc
    tiep (khong qua get_klines()) de phan trang qua 1000 nen - xem
    tests/test_datafeed.py::FakeSession cho dung contract can khop.
    """

    def test_tra_ve_dung_shape_result_list(self, monkeypatch):
        c = make_client()
        monkeypatch.setattr(c, "_raw_candles", lambda *a, **k: [
            ["1700000000000", "100", "101", "99", "100.5", "10", "0", "0", "1"],
        ])
        resp = c.session.get_kline(symbol="BTCUSDT", interval="240", limit=200)
        rows = resp["result"]["list"]
        assert len(rows) == 1
        assert len(rows[0]) == 7  # ts,o,h,l,c,vol,turnover - khop so cot Bybit tra ve

    def test_truyen_end_thanh_after_ts(self, monkeypatch):
        nhan = {}
        c = make_client()

        def fake_raw(symbol, interval, limit=100, after_ts=None):
            nhan["after_ts"] = after_ts
            return []

        monkeypatch.setattr(c, "_raw_candles", fake_raw)
        c.session.get_kline(symbol="BTCUSDT", interval="240", limit=200, end=123456)
        assert nhan["after_ts"] == 123456


class TestKiemTraKetNoi:
    """Nut 'Thu ket noi' o web UI song bang ham nay.

    Diem cot loi: no phai PHAN BIET duoc khoa sai voi tai khoan rong. Hai
    truong hop nay deu lam get_equity() tra None, nhung mot cai bao nguoi dung
    di tao lai khoa, cai kia bao ho di nap tien - khuyen nham la lam mat thoi
    gian cua ho.
    """

    def _client(self, monkeypatch, response):
        c = make_client()
        monkeypatch.setattr(c, "_request", lambda *a, **k: response)
        return c

    def test_khoa_dung_thi_bao_so_du(self, monkeypatch):
        c = self._client(monkeypatch, {"code": "0", "data": [{"totalEq": "1234.5"}]})
        kq = c.kiem_tra_ket_noi()
        assert kq["ok"] is True
        assert "1234.50" in kq["chi_tiet"]

    def test_khoa_sai_thi_bao_ma_loi_cua_san(self, monkeypatch):
        """50111 = sai API key. Ma loi la thu nguoi dung tra cuu duoc."""
        c = self._client(monkeypatch, {"code": "50111", "msg": "Invalid ApiKey", "data": []})
        kq = c.kiem_tra_ket_noi()
        assert kq["ok"] is False
        assert "50111" in kq["chi_tiet"]
        assert "Invalid ApiKey" in kq["chi_tiet"]

    def test_sai_passphrase_bao_khac_sai_key(self, monkeypatch):
        """OKX bat buoc passphrase ma Bybit khong co - day la loi rieng cua OKX
        va nguoi chuyen tu Bybit sang rat de dinh."""
        c = self._client(monkeypatch, {"code": "50105", "msg": "Passphrase incorrect", "data": []})
        assert "50105" in c.kiem_tra_ket_noi()["chi_tiet"]

    def test_tai_khoan_rong_khong_bi_nham_thanh_khoa_sai(self, monkeypatch):
        c = self._client(monkeypatch, {"code": "0", "data": []})
        kq = c.kiem_tra_ket_noi()
        assert kq["ok"] is False
        assert "khoa dung" in kq["chi_tiet"]

    def test_so_du_bang_khong_van_la_ket_noi_thanh_cong(self, monkeypatch):
        """Tai khoan demo moi tao co totalEq = 0. Do la ket noi TOT."""
        c = self._client(monkeypatch, {"code": "0", "data": [{"totalEq": "0"}]})
        assert c.kiem_tra_ket_noi()["ok"] is True

    def test_loi_mang_khong_lam_no_ham(self, monkeypatch):
        c = make_client()
        def no(*a, **k):
            raise ConnectionError("mat mang")
        monkeypatch.setattr(c, "_request", no)
        kq = c.kiem_tra_ket_noi()
        assert kq["ok"] is False
        assert "mat mang" in kq["chi_tiet"]
