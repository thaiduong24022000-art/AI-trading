"""
Kiem tra lop LLM veto - lop DUY NHAT ngoai risk engine co quyen chan mot lenh.

Hai module goi LLM (sentiment.py va journal.py) truoc day khong co test nao,
du sentiment.py nam thang tren duong ra lenh. Mot bug o day khong bao gio
trong giong bug: no trong giong "hom nay thi truong khong co tin hieu".

Ba nhom bat bien:
  1. TAT LA TAT. Khong bat ENABLE_LLM_VETO thi khong goi mang, khong chan gi.
  2. LLM HONG KHONG DUOC AM THAM DOI HANH VI. Fail-open hay fail-close deu
     phai dung theo cau hinh, va phai noi ro minh dang lam gi.
  3. KHONG DINH BAY CHUOI. "veto": "false" tra ve tu LLM phai duoc hieu la
     KHONG chan - bool("false") trong Python la True.
"""
import json

import pytest

from src.sentiment import VetoFilter, VetoResult, _bool_an_toan, _extract_json
from tests.conftest import make_cfg


class LLMGia:
    """Thay cho anthropic.Anthropic - tra ve van ban dat san."""

    def __init__(self, text=None, nem=None):
        self.text = text
        self.nem = nem
        self.so_lan_goi = 0
        self.messages = self

    def create(self, **kw):
        self.so_lan_goi += 1
        if self.nem:
            raise self.nem

        class Block:
            pass
        b = Block()
        b.text = self.text

        class Resp:
            pass
        r = Resp()
        r.content = [b]
        return r


def make_veto(text=None, nem=None, **cfg_kw):
    base = {"ENABLE_LLM_VETO": True, "ANTHROPIC_API_KEY": "kh", "LLM_FAIL_OPEN": True,
            "LLM_VETO_CACHE_SECONDS": 0}
    base.update(cfg_kw)
    v = VetoFilter(make_cfg(**base))
    v.client = LLMGia(text=text, nem=nem)
    return v


class TestTatLaTat:
    def test_khong_bat_thi_khong_goi_llm(self):
        v = VetoFilter(make_cfg(ENABLE_LLM_VETO=False))
        v.client = LLMGia(text='{"veto": true}')
        kq = v.check("BTCUSDT", "Buy", 100.0, "breakout")
        assert kq.allows_trade is True
        assert v.client.so_lan_goi == 0

    def test_thieu_api_key_thi_cho_qua(self):
        v = VetoFilter(make_cfg(ENABLE_LLM_VETO=True, ANTHROPIC_API_KEY=""))
        assert v.check("BTCUSDT", "Buy", 100.0, "x").allows_trade is True


class TestDocKetQua:
    def test_veto_true_thi_chan(self):
        v = make_veto('{"veto": true, "size_multiplier": 0.0, "reason": "san bi hack"}')
        kq = v.check("BTCUSDT", "Buy", 100.0, "breakout")
        assert kq.allows_trade is False
        assert "hack" in kq.reason

    def test_veto_false_thi_cho_qua(self):
        v = make_veto('{"veto": false, "size_multiplier": 1.0, "reason": "binh thuong"}')
        assert v.check("BTCUSDT", "Buy", 100.0, "x").allows_trade is True

    def test_chuoi_false_KHONG_bi_hieu_thanh_chan(self):
        """bool("false") trong Python la True. Neu khong ep kieu an toan thi
        bot chan sach moi lenh trong khi log van bao LLM chay binh thuong.
        """
        v = make_veto('{"veto": "false", "size_multiplier": 1.0}')
        assert v.check("BTCUSDT", "Buy", 100.0, "x").allows_trade is True

    def test_chuoi_true_van_duoc_hieu_la_chan(self):
        v = make_veto('{"veto": "true", "size_multiplier": 0.0}')
        assert v.check("BTCUSDT", "Buy", 100.0, "x").allows_trade is False

    def test_giam_quy_mo(self):
        v = make_veto('{"veto": false, "size_multiplier": 0.5, "reason": "bien dong cao"}')
        kq = v.check("BTCUSDT", "Buy", 100.0, "x")
        assert kq.allows_trade is True
        assert kq.size_multiplier == 0.5

    def test_size_multiplier_bi_kep_trong_khoang(self):
        v = make_veto('{"veto": false, "size_multiplier": 7.5}')
        assert v.check("BTCUSDT", "Buy", 100.0, "x").size_multiplier == 1.0

    def test_size_multiplier_0_tuong_duong_chan(self):
        v = make_veto('{"veto": false, "size_multiplier": 0.0}')
        assert v.check("BTCUSDT", "Buy", 100.0, "x").allows_trade is False

    def test_json_lan_trong_van_ban_van_doc_duoc(self):
        v = make_veto('Toi nghi rang:\n{"veto": false, "size_multiplier": 1.0}\nHet.')
        assert v.check("BTCUSDT", "Buy", 100.0, "x").llm_used is True


class TestLLMHong:
    def test_fail_open_cho_giao_dich(self):
        v = make_veto(nem=RuntimeError("mat mang"), LLM_FAIL_OPEN=True)
        kq = v.check("BTCUSDT", "Buy", 100.0, "x")
        assert kq.allows_trade is True
        assert kq.llm_used is False

    def test_fail_close_chan_giao_dich(self):
        v = make_veto(nem=RuntimeError("mat mang"), LLM_FAIL_OPEN=False)
        assert v.check("BTCUSDT", "Buy", 100.0, "x").allows_trade is False

    def test_json_hong_theo_dung_chinh_sach_fail(self):
        assert make_veto("khong phai json", LLM_FAIL_OPEN=True).check(
            "BTCUSDT", "Buy", 100.0, "x").allows_trade is True
        assert make_veto("khong phai json", LLM_FAIL_OPEN=False).check(
            "BTCUSDT", "Buy", 100.0, "x").allows_trade is False

    def test_loi_llm_khong_bao_gio_nem_ra_ngoai(self):
        """Vong giao dich khong duoc chet vi lop loc phu."""
        for loi in (RuntimeError("x"), TimeoutError("y"), ValueError("z")):
            make_veto(nem=loi).check("BTCUSDT", "Buy", 100.0, "x")


class TestCache:
    def test_cache_cat_bot_so_lan_goi(self):
        v = make_veto('{"veto": false, "size_multiplier": 1.0}',
                      LLM_VETO_CACHE_SECONDS=900)
        for _ in range(5):
            v.check("BTCUSDT", "Buy", 100.0, "x")
        assert v.client.so_lan_goi == 1

    def test_ma_khac_nhau_thi_hoi_rieng(self):
        v = make_veto('{"veto": false, "size_multiplier": 1.0}',
                      LLM_VETO_CACHE_SECONDS=900)
        v.check("BTCUSDT", "Buy", 100.0, "x")
        v.check("ETHUSDT", "Buy", 100.0, "x")
        assert v.client.so_lan_goi == 2

    def test_chieu_khac_nhau_thi_hoi_rieng(self):
        v = make_veto('{"veto": false, "size_multiplier": 1.0}',
                      LLM_VETO_CACHE_SECONDS=900)
        v.check("BTCUSDT", "Buy", 100.0, "x")
        v.check("BTCUSDT", "Sell", 100.0, "x")
        assert v.client.so_lan_goi == 2

    def test_tat_cache_thi_hoi_moi_lan(self):
        v = make_veto('{"veto": false}', LLM_VETO_CACHE_SECONDS=0)
        v.check("BTCUSDT", "Buy", 100.0, "x")
        v.check("BTCUSDT", "Buy", 100.0, "x")
        assert v.client.so_lan_goi == 2

    def test_ket_qua_hong_khong_duoc_cache(self):
        """Cache mot lan LLM hong se keo dai loi do suot TTL."""
        v = make_veto(nem=RuntimeError("mat mang"), LLM_VETO_CACHE_SECONDS=900)
        v.check("BTCUSDT", "Buy", 100.0, "x")
        v.check("BTCUSDT", "Buy", 100.0, "x")
        assert v.client.so_lan_goi == 2


class TestTienIch:
    def test_bool_an_toan(self):
        assert _bool_an_toan("false") is False
        assert _bool_an_toan("False") is False
        assert _bool_an_toan("no") is False
        assert _bool_an_toan("true") is True
        assert _bool_an_toan(True) is True
        assert _bool_an_toan(0) is False

    def test_extract_json(self):
        assert _extract_json('rac {"a": 1} rac') == {"a": 1}
        assert _extract_json("khong co gi") is None
        assert _extract_json("{hong}") is None
