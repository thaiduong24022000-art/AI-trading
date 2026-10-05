"""
Kiem tra nhat ky giao dich hang dem (Nang cap 6).

Module nay truoc day khong co test nao, va hon the: no chua bao gio chay duoc
voi du lieu that. Ly do la bang `trades` luon rong cho den khi
src/position_manager.py duoc them vao - nhat ky doc trades_of_day() nen no
luon chi thay mot ngay trong khong.

Bat bien quan trong nhat o day KHONG phai la chat luong ban phe binh, ma la:
nhat ky chi ghi vao bang journal, khong bao gio tu sua tham so. De LLM tu chinh
tham so theo ket qua ngan han la con duong ngan nhat den overfit theo thoi
gian thuc - va la kieu overfit kho phat hien nhat vi no khong de lai backtest.
"""
from datetime import datetime

import pytest

from src.journal import TradingJournal
from tests.conftest import make_cfg


class StorageGia:
    def __init__(self, trades=None, decisions=None):
        self._trades = trades or []
        self._decisions = decisions or []
        self.journal_da_ghi = []

    def trades_of_day(self, a, b):
        return self._trades

    def decisions_of_day(self, a, b):
        return self._decisions

    def log_journal(self, day, content, stats=None):
        self.journal_da_ghi.append({"day": day, "content": content, "stats": stats})


class LLMGia:
    def __init__(self, text="Phe binh: hom nay bot vao 2 lenh...", nem=None):
        self.text = text
        self.nem = nem
        self.so_lan_goi = 0
        self.loi_nhac_cuoi = None
        self.messages = self

    def create(self, **kw):
        self.so_lan_goi += 1
        self.loi_nhac_cuoi = kw["messages"][0]["content"]
        if self.nem:
            raise self.nem

        class B:
            pass
        b = B()
        b.text = self.text

        class R:
            pass
        r = R()
        r.content = [b]
        return r


def lenh(symbol="BTCUSDT", pnl=10.0, ly_do="take_profit"):
    return {"symbol": symbol, "side": "Buy", "qty": 0.1, "entry_price": 100.0,
            "exit_price": 110.0, "pnl": pnl, "exit_reason": ly_do,
            "strategy": "breakout"}


def quyet_dinh(action="BUY", llm_veto=0):
    return {"symbol": "BTCUSDT", "action": action, "strength": 0.6,
            "regime": "trend", "executed": 1, "reason": "breakout",
            "llm_veto": llm_veto}


def make_journal(storage, llm=None, **cfg_kw):
    base = {"ENABLE_NIGHTLY_JOURNAL": True, "ANTHROPIC_API_KEY": "kh"}
    base.update(cfg_kw)
    j = TradingJournal(storage, make_cfg(**base))
    j.client = llm
    return j


class TestThongKe:
    def test_dem_dung_lenh_thang_thua(self):
        st = StorageGia(trades=[lenh(pnl=10), lenh(pnl=-5), lenh(pnl=3)],
                        decisions=[quyet_dinh()])
        tk = make_journal(st).collect_stats(datetime(2026, 9, 6))
        assert tk["so_lenh"] == 3
        assert tk["so_lenh_thang"] == 2
        assert tk["win_rate"] == pytest.approx(2 / 3)
        assert tk["tong_pnl"] == pytest.approx(8.0)

    def test_ngay_trong_khong_vo(self):
        tk = make_journal(StorageGia()).collect_stats(datetime(2026, 9, 6))
        assert tk["so_lenh"] == 0
        assert tk["win_rate"] == 0.0

    def test_dem_so_lan_llm_chan(self):
        st = StorageGia(decisions=[quyet_dinh(llm_veto=1), quyet_dinh(llm_veto=0)])
        assert make_journal(st).collect_stats()["so_lan_bi_llm_chan"] == 1


class TestSinhNhatKy:
    def test_ngay_khong_hoat_dong_thi_khong_goi_llm(self):
        """Khong co quyet dinh nao thi khong co gi de phe binh - va mot lan goi
        LLM cho mot ngay trong khong la tien vut di.
        """
        llm = LLMGia()
        j = make_journal(StorageGia(), llm)
        assert j.generate(datetime(2026, 9, 6)) is None
        assert llm.so_lan_goi == 0

    def test_chua_bat_llm_van_ghi_thong_ke(self):
        st = StorageGia(trades=[lenh()], decisions=[quyet_dinh()])
        j = make_journal(st, llm=None)
        noi_dung = j.generate(datetime(2026, 9, 6))
        assert noi_dung is not None
        assert st.journal_da_ghi[0]["day"] == "2026-09-06"

    def test_co_llm_thi_sinh_va_luu(self):
        st = StorageGia(trades=[lenh()], decisions=[quyet_dinh()])
        llm = LLMGia(text="Ban phe binh")
        assert make_journal(st, llm).generate(datetime(2026, 9, 6)) == "Ban phe binh"
        assert st.journal_da_ghi[0]["content"] == "Ban phe binh"

    def test_loi_nhac_co_chua_lenh_va_ly_do(self):
        st = StorageGia(trades=[lenh(symbol="SOLUSDT", ly_do="stop_loss")],
                        decisions=[quyet_dinh()])
        llm = LLMGia()
        make_journal(st, llm).generate(datetime(2026, 9, 6))
        assert "SOLUSDT" in llm.loi_nhac_cuoi
        assert "stop_loss" in llm.loi_nhac_cuoi

    def test_llm_hong_khong_nem_ra_ngoai(self):
        """Nhat ky chay trong vong lap giao dich - no hong khong duoc lam bot chet."""
        st = StorageGia(trades=[lenh()], decisions=[quyet_dinh()])
        j = make_journal(st, LLMGia(nem=RuntimeError("mat mang")))
        assert j.generate(datetime(2026, 9, 6)) is None

    def test_chi_ghi_vao_journal_khong_dung_gi_khac(self):
        """Nhat ky KHONG duoc tu sua tham so - no chi duoc viet chu.

        StorageGia co dung mot ham log_journal; neu mot ngay nao do nhat ky goi
        them thu gi khac (log_order, ghi config...) thi test nay se vo ngay.
        """
        st = StorageGia(trades=[lenh()], decisions=[quyet_dinh()])
        make_journal(st, LLMGia()).generate(datetime(2026, 9, 6))
        assert len(st.journal_da_ghi) == 1
