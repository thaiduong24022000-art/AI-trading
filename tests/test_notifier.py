"""
Kiem tra lop canh bao Telegram.

Bat bien quan trong nhat KHONG phai la "tin nhan den noi", ma la "lop nay
khong bao gio lam dung vong giao dich". Mot bot ngung giao dich vi Telegram
sap la mot bot te hon bot khong co Telegram - nen moi loi mang, timeout hay
token sai deu phai bi nuot tai day.

Bat bien thu hai la KHONG SPAM: circuit breaker bat thi no bat mai cho den khi
nguoi reset. Bao moi vong 15 phut nghia la 96 tin nhan giong het nhau sau mot
dem, va tin nhan thu 97 se khong con ai doc.
"""
import pytest

from src import notifier as notifier_mod
from src.notifier import Notifier
from tests.conftest import make_cfg


def make_notifier(bat=True, **kw):
    base = {"ENABLE_TELEGRAM": bat, "TELEGRAM_BOT_TOKEN": "token_gia",
            "TELEGRAM_CHAT_ID": "123", "TELEGRAM_TIMEOUT_SECONDS": 5}
    base.update(kw)
    return Notifier(make_cfg(**base))


class GuiGia:
    """Thay cho requests.post - ghi lai loi goi thay vi cham mang."""

    def __init__(self, status=200, nem=None):
        self.status = status
        self.nem = nem
        self.goi = []

    def __call__(self, url, json=None, timeout=None):
        self.goi.append({"url": url, "json": json, "timeout": timeout})
        if self.nem:
            raise self.nem

        class R:
            pass
        r = R()
        r.status_code = self.status
        return r


# ---------- tat la mac dinh ----------
class TestTatLaMacDinh:
    def test_khong_cau_hinh_thi_khong_gui(self, monkeypatch):
        gui = GuiGia()
        monkeypatch.setattr("src.notifier.requests.post", gui)
        n = Notifier(make_cfg(ENABLE_TELEGRAM=False))
        assert n.bao("thu") is False
        assert gui.goi == []

    def test_bat_nhung_thieu_token_thi_khong_gui(self, monkeypatch):
        gui = GuiGia()
        monkeypatch.setattr("src.notifier.requests.post", gui)
        n = make_notifier(bat=True, TELEGRAM_BOT_TOKEN="")
        assert n.bat is False
        assert n.bao("thu") is False
        assert gui.goi == []


# ---------- khong bao gio lam dung vong giao dich ----------
class TestKhongBaoGioNem:
    def test_mang_loi_thi_nuot(self, monkeypatch):
        gui = GuiGia(nem=ConnectionError("mat mang"))
        monkeypatch.setattr("src.notifier.requests.post", gui)
        n = make_notifier()
        assert n.bao("thu") is False        # khong nem ra ngoai

    def test_timeout_thi_nuot(self, monkeypatch):
        gui = GuiGia(nem=TimeoutError("qua han"))
        monkeypatch.setattr("src.notifier.requests.post", gui)
        assert make_notifier().bao("thu") is False

    def test_telegram_tra_loi_401_thi_nuot(self, monkeypatch):
        gui = GuiGia(status=401)
        monkeypatch.setattr("src.notifier.requests.post", gui)
        assert make_notifier().bao("thu") is False

    def test_moi_ham_su_kien_deu_an_toan_khi_mang_hong(self, monkeypatch):
        """Quet toan bo API cong khai - mot ham quen try/except la du de bot chet."""
        monkeypatch.setattr("src.notifier.requests.post",
                            GuiGia(nem=ConnectionError("mat mang")))
        n = make_notifier()
        n.khoi_dong("bybit", True, True, ["BTCUSDT"], ["breakout"])
        n.dung()
        n.doi_soat_that_bai("401")
        n.breaker_bat("drawdown ngay")
        n.mo_lenh("BTCUSDT", "Buy", 0.1, 100, 95, 110, "breakout", True)
        n.dong_lenh("BTCUSDT", "Buy", 0.1, 100, 110, 9.8, "take_profit", True)
        n.nhat_ky("noi dung")      # khong ham nao duoc nem ra ngoai


# ---------- khong spam ----------
class TestDedup:
    def test_cung_khoa_khong_gui_lai_ngay(self, monkeypatch):
        gui = GuiGia()
        monkeypatch.setattr("src.notifier.requests.post", gui)
        n = make_notifier()
        assert n.bao("breaker bat", khoa="breaker") is True
        assert n.bao("breaker bat", khoa="breaker") is False
        assert len(gui.goi) == 1

    def test_khoa_khac_nhau_thi_deu_gui(self, monkeypatch):
        gui = GuiGia()
        monkeypatch.setattr("src.notifier.requests.post", gui)
        n = make_notifier()
        n.bao("a", khoa="mot")
        n.bao("b", khoa="hai")
        assert len(gui.goi) == 2

    def test_khong_co_khoa_thi_luon_gui(self, monkeypatch):
        gui = GuiGia()
        monkeypatch.setattr("src.notifier.requests.post", gui)
        n = make_notifier()
        n.bao("lenh 1")
        n.bao("lenh 2")
        assert len(gui.goi) == 2

    def test_het_han_dedup_thi_gui_lai(self, monkeypatch):
        gui = GuiGia()
        monkeypatch.setattr("src.notifier.requests.post", gui)
        n = make_notifier()
        n.bao("x", khoa="k", lap_lai_sau=0.0)
        n.bao("x", khoa="k", lap_lai_sau=0.0)
        assert len(gui.goi) == 2

    def test_xoa_dedup_cho_phep_bao_lai_ngay(self, monkeypatch):
        """Nguoi vua reset breaker -> lan bat ke tiep la su kien MOI, khong
        phai tieng vang cua lan cu, nen no xung dang mot tin nhan.
        """
        gui = GuiGia()
        monkeypatch.setattr("src.notifier.requests.post", gui)
        n = make_notifier()
        n.breaker_bat("drawdown")
        assert len(gui.goi) == 1
        n.breaker_bat("drawdown")
        assert len(gui.goi) == 1          # con trong cua so dedup
        n.xoa_dedup(notifier_mod.BREAKER)
        n.breaker_bat("thua lien tiep")
        assert len(gui.goi) == 2


# ---------- noi dung tin nhan ----------
class TestNoiDung:
    def test_gui_dung_chat_id_va_timeout(self, monkeypatch):
        gui = GuiGia()
        monkeypatch.setattr("src.notifier.requests.post", gui)
        make_notifier().bao("xin chao")
        assert gui.goi[0]["json"]["chat_id"] == "123"
        assert gui.goi[0]["json"]["text"] == "xin chao"
        assert gui.goi[0]["timeout"] == 5

    def test_che_do_tien_that_duoc_noi_ro(self, monkeypatch):
        gui = GuiGia()
        monkeypatch.setattr("src.notifier.requests.post", gui)
        make_notifier().khoi_dong("okx", False, False, ["BTCUSDT"], ["breakout"])
        assert "TIEN THAT" in gui.goi[0]["json"]["text"]

    def test_dry_run_khong_bi_nham_la_lenh_that(self, monkeypatch):
        gui = GuiGia()
        monkeypatch.setattr("src.notifier.requests.post", gui)
        make_notifier().mo_lenh("BTCUSDT", "Buy", 0.1, 100, 95, 110, "breakout",
                                dry_run=True)
        assert "DRY-RUN" in gui.goi[0]["json"]["text"]

    def test_nhat_ky_dai_bi_cat_theo_gioi_han_telegram(self, monkeypatch):
        gui = GuiGia()
        monkeypatch.setattr("src.notifier.requests.post", gui)
        make_notifier().nhat_ky("x" * 9000)
        assert len(gui.goi[0]["json"]["text"]) < 4096   # gioi han cua Telegram
