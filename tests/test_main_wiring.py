"""
Kiem tra cach cac lop MOI duoc noi vao vong lap giao dich trong main.py.

Cac module ben duoi (position_manager, kho_luat, cham_diem_bong, notifier) deu
da co test rieng. Bo test nay bao ve mot loai loi khac han: MODULE DUNG NHUNG
NOI SAI CHO. Vi du that ma no chan:

  - `dong_bo()` goi SAU cong circuit breaker: khi breaker ngat, lenh dong tren
    san khong bao gio duoc ghi nhan, va trang thai local troi xa khoi san dung
    luc can chinh xac nhat.
  - `thoat_khi_dao_chieu()` goi SAU risk engine: lenh moi bi tu choi vi day vi
    the, roi vi the nguoc chieu moi duoc dong - bot bo lo dung cay nen ma
    backtest gia dinh no vao lenh.
  - Chien luoc luat che do BONG lot vao `self.strategies`: chi viec co mat da
    lam doi trong so cua cac chien luoc that, va bong khong con la bong.

Ca ba loi tren deu de MOI test cap module di qua sach se.
"""
import types

import pandas as pd
import pytest

import main as main_mod
from src.strategies import Breakout
from tests.conftest import make_cfg


class StorageGia:
    def __init__(self):
        self.equity = []
        self.nhip_tim = []
        self.lenh = []
        self.da_danh_dau = []

    def log_equity(self, *a, **k):
        self.equity.append((a, k))

    def ghi_trang_thai_bot(self, **k):
        self.nhip_tim.append(k)

    def lenh_cho_xu_ly(self, han_giay=600):
        return list(self.lenh)

    def danh_dau_lenh(self, id_, trang_thai, ket_qua=""):
        self.da_danh_dau.append((id_, trang_thai, ket_qua))

    def log_shadow_signal(self, *a, **k):
        pass


def _bot(**cfg_kw):
    """TradingBot toi thieu - khong Storage that, khong ket noi san."""
    bot = main_mod.TradingBot.__new__(main_mod.TradingBot)
    bot.storage = StorageGia()
    bot.strategies = [Breakout()]
    bot.luat_bong = []
    bot.policy_strategy = None
    bot.notifier = types.SimpleNamespace(
        da_bao=[], xoa_dedup=lambda k: None,
        breaker_bat=lambda ly_do: bot.notifier.da_bao.append(ly_do))
    bot.breaker = types.SimpleNamespace(tripped=False, reason="",
                                        manual_reset=lambda: None,
                                        record_api_error=lambda: None,
                                        check_equity=lambda e: None)
    bot.risk = types.SimpleNamespace(positions={}, current_heat=lambda e: 0.0)
    bot.positions = types.SimpleNamespace(goi_dong_bo=0)

    def dong_bo(frames=None):
        bot.positions.goi_dong_bo += 1
        return 0
    bot.positions.dong_bo = dong_bo
    bot.client = types.SimpleNamespace(
        get_equity=lambda: 10000.0,
        get_klines=lambda s: pd.DataFrame({"close": [1.0]}))
    return bot


# ==========================================================
# Thu tu trong run_cycle
# ==========================================================
class TestThuTuRunCycle:
    def test_dong_bo_van_chay_KHI_breaker_dang_ngat(self, monkeypatch):
        """'Dung mo lenh moi' khong co nghia la 'ngung ghi so'. Bo qua dong bo
        luc breaker ngat = heat khong bao gio duoc tra ve, va trang thai local
        troi xa khoi san dung luc can chinh xac nhat.
        """
        bot = _bot()
        bot.breaker.tripped = True
        bot.breaker.reason = "drawdown"
        monkeypatch.setattr(main_mod.config, "SYMBOLS", ["BTCUSDT"])
        bot.run_cycle()
        assert bot.positions.goi_dong_bo == 1

    def test_breaker_ngat_thi_khong_xu_ly_symbol_nao(self, monkeypatch):
        bot = _bot()
        bot.breaker.tripped = True
        bot.breaker.reason = "drawdown"
        da_goi = []
        bot.process_symbol = lambda *a, **k: da_goi.append(a)
        monkeypatch.setattr(main_mod.config, "SYMBOLS", ["BTCUSDT"])
        bot.run_cycle()
        assert da_goi == []

    def test_breaker_ngat_thi_co_bao_telegram(self, monkeypatch):
        bot = _bot()
        bot.breaker.tripped = True
        bot.breaker.reason = "5 lenh thua lien tiep"
        monkeypatch.setattr(main_mod.config, "SYMBOLS", ["BTCUSDT"])
        bot.run_cycle()
        assert bot.notifier.da_bao == ["5 lenh thua lien tiep"]

    def test_nhip_tim_duoc_ghi_moi_vong(self, monkeypatch):
        bot = _bot()
        bot.breaker.tripped = True
        monkeypatch.setattr(main_mod.config, "SYMBOLS", ["BTCUSDT"])
        bot.run_cycle()
        assert len(bot.storage.nhip_tim) == 1
        assert bot.storage.nhip_tim[0]["breaker_ngat"] is True

    def test_khong_doc_duoc_von_thi_dung_vong(self, monkeypatch):
        bot = _bot()
        bot.client.get_equity = lambda: None
        monkeypatch.setattr(main_mod.config, "SYMBOLS", ["BTCUSDT"])
        bot.run_cycle()
        assert bot.positions.goi_dong_bo == 0
        assert bot.storage.nhip_tim == []


# ==========================================================
# Kenh dieu khien
# ==========================================================
class TestLenhDieuKhien:
    def test_lenh_ngoai_danh_sach_bi_tu_choi(self):
        bot = _bot()
        bot.storage.lenh = [{"id": 1, "lenh": "dong_het_vi_the"}]
        bot._xu_ly_lenh_dieu_khien()
        assert bot.storage.da_danh_dau[0][1] == "tu_choi"

    def test_reset_breaker_duoc_chay(self):
        bot = _bot()
        da_reset = []
        bot.breaker.manual_reset = lambda: da_reset.append(True)
        bot.breaker.reason = "drawdown"
        bot.storage.lenh = [{"id": 7, "lenh": "reset_breaker"}]
        bot._xu_ly_lenh_dieu_khien()
        assert da_reset == [True]
        assert bot.storage.da_danh_dau[0][:2] == (7, "xong")

    def test_loi_khi_chay_lenh_duoc_ghi_lai_chu_khong_nem(self):
        bot = _bot()
        def no():
            raise RuntimeError("hong")
        bot.breaker.manual_reset = no
        bot.storage.lenh = [{"id": 9, "lenh": "reset_breaker"}]
        bot._xu_ly_lenh_dieu_khien()
        assert bot.storage.da_danh_dau[0][1] == "loi"

    def test_doc_lenh_that_bai_khong_lam_dung_vong(self):
        bot = _bot()
        def no(han_giay=600):
            raise RuntimeError("DB khoa")
        bot.storage.lenh_cho_xu_ly = no
        bot._xu_ly_lenh_dieu_khien()      # khong duoc nem ra ngoai


# ==========================================================
# Chien luoc luat che do bong
# ==========================================================
class TestLuatBong:
    def test_chien_luoc_bong_KHONG_nam_trong_ensemble(self, monkeypatch, tmp_path):
        """Bat bien quan trong nhat - xem docstring dau file va
        tests/test_main_policy.py cho bat bien tuong duong cua AI policy.
        """
        from src.strategies import kho_luat as kl
        kho = kl.KhoLuat(duong_dan=str(tmp_path / "kho.json"))
        kho.them_ung_vien({"ten": "luat_bong_test", "long": [["rsi", "<", 30]]},
                          {"qua_cong": True, "sharpe_min": 1.4, "tong_lenh": 100})
        kho.thang_cap("luat_bong_test")          # -> bong
        monkeypatch.setattr(kl, "DUONG_DAN_MAC_DINH", kho.duong_dan)

        bot = _bot()
        bot.strategies = [Breakout()]
        bot.luat_bong = bot._tao_luat_bong()
        assert [s.name for s in bot.luat_bong] == ["luat_bong_test"]
        assert "luat_bong_test" not in [s.name for s in bot.strategies]

    def test_kho_luat_hong_khong_lam_dung_bot(self, monkeypatch, tmp_path):
        from src.strategies import kho_luat as kl
        p = tmp_path / "hong.json"
        p.write_text("{khong phai json", encoding="utf-8")
        monkeypatch.setattr(kl, "DUONG_DAN_MAC_DINH", str(p))
        bot = _bot()
        assert bot._tao_luat_bong() == []      # bo qua, khong nem

    def test_ghi_tin_hieu_bong_ca_khi_la_HOLD(self, tmp_path):
        """Chi ghi luc no muon vao lenh la thien lech chon mau - luc cham diem
        se thay chien luoc quyet doan hon thuc te.
        """
        from src.strategies.rule_spec import bien_dich
        ghi = []
        bot = _bot()
        bot.storage.log_shadow_signal = lambda *a, **k: ghi.append(a)
        bot.luat_bong = [bien_dich({"ten": "khong_bao_gio",
                                    "long": [["rsi", "<", -999]]})()]
        df = pd.DataFrame({"rsi": [50.0, 50.0], "close": [100.0, 100.0]})
        bot._chay_luat_bong("BTCUSDT", df, 1, 1700000000000)
        assert len(ghi) == 1
        assert ghi[0][2] == "HOLD"

    def test_chien_luoc_bong_loi_khong_lam_dung_vong(self):
        class Hong:
            name = "hong"
            def prepare(self, df):
                raise RuntimeError("vo")
        bot = _bot()
        bot.luat_bong = [Hong()]
        df = pd.DataFrame({"close": [100.0, 100.0]})
        bot._chay_luat_bong("BTCUSDT", df, 1, 0)     # khong duoc nem ra ngoai
