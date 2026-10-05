"""
Kiem tra vong doi vi the o ban live.

Truoc khi co module nay, bot mo lenh xong la thoi: heat khong bao gio duoc tra
lai, bang trades luon rong, va sau MAX_OPEN_POSITIONS lenh thi risk engine tu
choi moi tin hieu VINH VIEN. Nhin tu ben ngoai, bot chet lang le trong khi log
van chay binh thuong - kieu hong te nhat trong ba kieu.

Hai bat bien duoc khoa o day:
  1. Lenh dong PHAI duoc ghi nhan (log_trade + record_trade_result + tra heat).
  2. KHONG duoc suy ra "lenh da dong" tu mot phep doc san THAT BAI. Nham hai
     cai do nghia la ghi nhan hang loat lenh dong gia va tra heat ve sai, dung
     luc mang chap chon - tuc la dung luc te nhat.
"""
import pandas as pd
import pytest

from src.position_manager import (
    DONG_TREN_SAN, SIGNAL_REVERSE, STOP_LOSS, TAKE_PROFIT, PositionManager,
)
from src.risk_manager import CircuitBreaker, Position, RiskManager
from tests.conftest import make_cfg


class FakeStorage:
    def __init__(self):
        self.trades = []

    def log_trade(self, **kw):
        self.trades.append(kw)


class FakeClient:
    """San gia lap. loi_doc=True mo phong luc mat mang / API tra loi."""

    def __init__(self, positions=None, balances=None, loi_doc=False, price=100.0):
        self._positions = positions or []
        self._balances = balances or {}
        self.loi_doc = loi_doc
        self.price = price

    def get_open_positions(self):
        if self.loi_doc:
            raise RuntimeError("timeout doc vi the")
        return self._positions

    def get_spot_balances(self):
        if self.loi_doc:
            raise RuntimeError("timeout doc so du")
        return self._balances

    def get_last_price(self, symbol):
        return self.price


def make_pm(cfg=None, client=None, storage=None, **cfg_kw):
    base = {"DRY_RUN": True, "CATEGORY": "linear", "FEE_TAKER": 0.001,
            "MAX_OPEN_POSITIONS": 3}
    base.update(cfg_kw)
    cfg = cfg or make_cfg(**base)
    breaker = CircuitBreaker(cfg)
    risk = RiskManager(cfg, breaker)
    storage = storage if storage is not None else FakeStorage()
    pm = PositionManager(client=client, storage=storage, risk=risk,
                         breaker=breaker, cfg=cfg)
    return pm, risk, breaker, storage


def mot_nen(high, low, close=None):
    return pd.DataFrame([{"high": high, "low": low, "close": close or (high + low) / 2,
                          "open": low, "volume": 1.0}])


def vi_the(symbol="BTCUSDT", side="Buy", entry=100.0, sl=95.0, tp=110.0, qty=1.0):
    return Position(symbol=symbol, side=side, qty=qty, entry_price=entry,
                    stop_loss=sl, take_profit=tp, strategy="breakout")


# ---------- che do dry-run: mo phong giong backtest ----------
class TestMoPhongDryRun:
    def test_cham_stop_thi_dong_va_ghi_nhan(self):
        pm, risk, breaker, storage = make_pm()
        risk.register_position(vi_the())
        so = pm.dong_bo({"BTCUSDT": mot_nen(high=101, low=94)})
        assert so == 1
        assert risk.positions == {}                  # heat da duoc tra ve
        assert storage.trades[0]["exit_reason"] == STOP_LOSS
        assert storage.trades[0]["pnl"] < 0
        assert breaker.consecutive_losses == 1       # breaker duoc nuoi so lieu

    def test_cham_tp_thi_lai(self):
        pm, risk, _, storage = make_pm()
        risk.register_position(vi_the())
        pm.dong_bo({"BTCUSDT": mot_nen(high=111, low=99)})
        assert storage.trades[0]["exit_reason"] == TAKE_PROFIT
        assert storage.trades[0]["pnl"] > 0

    def test_cham_ca_hai_trong_mot_nen_thi_tinh_stop_truoc(self):
        """Gia dinh bi quan giong backtest/engine.py - khong duoc phep lac quan
        hon backtest, neu khong ban live se do dep hon thuc te mot cach he thong.
        """
        pm, risk, _, storage = make_pm()
        risk.register_position(vi_the())
        pm.dong_bo({"BTCUSDT": mot_nen(high=111, low=94)})
        assert storage.trades[0]["exit_reason"] == STOP_LOSS

    def test_chua_cham_gi_thi_giu_nguyen(self):
        pm, risk, _, storage = make_pm()
        risk.register_position(vi_the())
        assert pm.dong_bo({"BTCUSDT": mot_nen(high=105, low=97)}) == 0
        assert "BTCUSDT" in risk.positions
        assert storage.trades == []

    def test_vi_the_ban_khong_dao_chieu_nguong(self):
        pm, risk, _, storage = make_pm()
        risk.register_position(vi_the(side="Sell", entry=100, sl=105, tp=90))
        pm.dong_bo({"BTCUSDT": mot_nen(high=106, low=99)})
        assert storage.trades[0]["exit_reason"] == STOP_LOSS

    def test_phi_hai_chieu_duoc_tru(self):
        """Lai gop 10 tren notional 100 voi phi 0.1% moi chieu -> pnl < 10."""
        pm, risk, _, storage = make_pm()
        risk.register_position(vi_the(entry=100.0, tp=110.0, qty=1.0))
        pm.dong_bo({"BTCUSDT": mot_nen(high=110, low=100)})
        pnl = storage.trades[0]["pnl"]
        assert pnl == pytest.approx(10.0 - (100 + 110) * 0.001, rel=1e-6)


# ---------- che do that: san la nguon su that ----------
class TestPhatHienTrenSan:
    def test_vi_the_bien_mat_khoi_san_thi_ghi_nhan_dong(self):
        pm, risk, _, storage = make_pm(DRY_RUN=False,
                                       client=FakeClient(positions=[]))
        risk.register_position(vi_the())
        so = pm.dong_bo({"BTCUSDT": mot_nen(high=110, low=109, close=109.5)})
        assert so == 1
        assert risk.positions == {}
        assert storage.trades[0]["exit_price"] == 109.5

    def test_vi_the_con_tren_san_thi_giu(self):
        san = [{"symbol": "BTCUSDT", "side": "Buy", "size": "1", "avgPrice": "100"}]
        pm, risk, _, storage = make_pm(DRY_RUN=False, client=FakeClient(positions=san))
        risk.register_position(vi_the())
        assert pm.dong_bo({"BTCUSDT": mot_nen(high=105, low=99)}) == 0
        assert "BTCUSDT" in risk.positions

    def test_doc_san_that_bai_KHONG_duoc_coi_la_da_dong(self):
        """Bat bien quan trong nhat cua file nay - xem docstring dau file."""
        pm, risk, breaker, storage = make_pm(DRY_RUN=False,
                                             client=FakeClient(loi_doc=True))
        risk.register_position(vi_the())
        assert pm.dong_bo({"BTCUSDT": mot_nen(high=105, low=99)}) == 0
        assert "BTCUSDT" in risk.positions     # van giu, khong ghi nhan bua
        assert storage.trades == []
        assert breaker.consecutive_api_errors == 1

    def test_doan_ly_do_khi_gia_thoat_gan_stop(self):
        pm, risk, _, storage = make_pm(DRY_RUN=False, client=FakeClient(positions=[]))
        risk.register_position(vi_the(entry=100, sl=95, tp=110))
        pm.dong_bo({"BTCUSDT": mot_nen(high=96, low=94, close=95.2)})
        assert storage.trades[0]["exit_reason"] == STOP_LOSS

    def test_khong_doan_bua_khi_gia_thoat_o_giua(self):
        """Gia thoat lung chung giua SL va TP thi khong ket luan - ghi
        DONG_TREN_SAN. Doan bua o day lam thong ke exit_reason lech.
        """
        pm, risk, _, storage = make_pm(DRY_RUN=False, client=FakeClient(positions=[]))
        risk.register_position(vi_the(entry=100, sl=95, tp=110))
        pm.dong_bo({"BTCUSDT": mot_nen(high=103, low=102, close=102.5)})
        assert storage.trades[0]["exit_reason"] == DONG_TREN_SAN


# ---------- thoat khi tin hieu dao chieu ----------
class TestThoatDaoChieu:
    def test_tin_hieu_nguoc_chieu_thi_dong(self):
        pm, risk, _, storage = make_pm()
        risk.register_position(vi_the(side="Buy"))
        assert pm.thoat_khi_dao_chieu("BTCUSDT", "SELL", 103.0) is True
        assert risk.positions == {}
        assert storage.trades[0]["exit_reason"] == SIGNAL_REVERSE

    def test_tin_hieu_cung_chieu_thi_giu(self):
        pm, risk, _, storage = make_pm()
        risk.register_position(vi_the(side="Buy"))
        assert pm.thoat_khi_dao_chieu("BTCUSDT", "BUY", 103.0) is False
        assert "BTCUSDT" in risk.positions

    def test_khong_co_vi_the_thi_khong_lam_gi(self):
        pm, _, _, storage = make_pm()
        assert pm.thoat_khi_dao_chieu("BTCUSDT", "SELL", 103.0) is False
        assert storage.trades == []

    def test_san_tu_choi_dong_thi_KHONG_ghi_nhan_da_dong(self):
        """Neu ghi bua la da dong trong khi san van giu lenh, bot se tuong minh
        trang tay va mo them lenh chong len vi the cu.
        """
        class ExecutorTuChoi:
            def close_position(self, pos, gia, reason=""):
                class KQ:
                    success = False
                    message = "san tu choi"
                return KQ()

        pm, risk, _, storage = make_pm(DRY_RUN=False, client=FakeClient(positions=[]))
        pm.executor = ExecutorTuChoi()
        risk.register_position(vi_the(side="Buy"))
        assert pm.thoat_khi_dao_chieu("BTCUSDT", "SELL", 103.0) is False
        assert "BTCUSDT" in risk.positions
        assert storage.trades == []


# ---------- bat bien: heat phai duoc tra ve ----------
def test_heat_duoc_tra_ve_sau_khi_dong():
    """Loi goc khien bot chet lang le: heat chi tang, khong bao gio giam, nen
    sau MAX_OPEN_POSITIONS lenh thi moi tin hieu deu bi tu choi vinh vien.
    """
    pm, risk, _, _ = make_pm(MAX_OPEN_POSITIONS=1)
    risk.register_position(vi_the())
    assert risk.current_heat(equity=10000) > 0
    pm.dong_bo({"BTCUSDT": mot_nen(high=101, low=94)})
    assert risk.current_heat(equity=10000) == 0
    # va cho mo lenh moi tro lai
    assert len(risk.positions) < 1


# ---------- lưới an toàn: stop của sàn không chạy ----------
class TestEpStopPhiaBot:
    """Kịch bản: lệnh gửi kèm stop-loss, sàn nhận lệnh chính nhưng ÂM THẦM bỏ
    qua phần stop (sai tên tham số, lệnh algo bị từ chối, lỗi sàn). Giá xuyên
    qua stop mà vị thế vẫn mở — bot phải tự đóng, không được ngồi chờ một cái
    stop không tồn tại.
    """

    class ExecutorGhiNhan:
        def __init__(self, thanh_cong=True):
            self.thanh_cong = thanh_cong
            self.da_goi = []

        def close_position(self, pos, gia, reason="", bar_timestamp=None):
            self.da_goi.append({"symbol": pos.symbol, "gia": gia, "reason": reason,
                                "bar_timestamp": bar_timestamp})

            class KQ:
                pass
            k = KQ()
            k.success = self.thanh_cong
            k.message = "" if self.thanh_cong else "san tu choi"
            return k

    def _dung_len(self, san_con_vi_the=True, thanh_cong=True):
        san = ([{"symbol": "BTCUSDT", "side": "Buy", "size": "1", "avgPrice": "100"}]
               if san_con_vi_the else [])
        pm, risk, breaker, storage = make_pm(DRY_RUN=False,
                                             client=FakeClient(positions=san))
        pm.executor = self.ExecutorGhiNhan(thanh_cong)
        risk.register_position(vi_the(entry=100, sl=95, tp=110))
        return pm, risk, breaker, storage

    def test_gia_xuyen_stop_ma_san_van_giu_thi_bot_tu_dong(self):
        pm, risk, _, storage = self._dung_len()
        so = pm.dong_bo({"BTCUSDT": mot_nen(high=96, low=93, close=94)})
        assert so == 1
        assert pm.executor.da_goi[0]["reason"] == "stop_phia_bot"
        assert risk.positions == {}
        assert storage.trades[0]["exit_reason"] == "stop_phia_bot"

    def test_gia_chua_xuyen_stop_thi_khong_dong(self):
        pm, risk, _, _ = self._dung_len()
        assert pm.dong_bo({"BTCUSDT": mot_nen(high=105, low=97, close=99)}) == 0
        assert pm.executor.da_goi == []
        assert "BTCUSDT" in risk.positions

    def test_vi_the_ban_khong_dung_nguong_nguoc_lai(self):
        san = [{"symbol": "BTCUSDT", "side": "Sell", "size": "1", "avgPrice": "100"}]
        pm, risk, _, _ = make_pm(DRY_RUN=False, client=FakeClient(positions=san))
        pm.executor = self.ExecutorGhiNhan()
        risk.register_position(vi_the(side="Sell", entry=100, sl=105, tp=90))
        pm.dong_bo({"BTCUSDT": mot_nen(high=107, low=104, close=106)})
        assert pm.executor.da_goi[0]["reason"] == "stop_phia_bot"

    def test_san_tu_choi_dong_thi_KHONG_ghi_nhan_da_dong(self):
        """Ghi bừa là đã đóng trong khi sàn vẫn giữ lệnh = bot tưởng mình trắng
        tay và mở thêm lệnh chồng lên vị thế cũ.
        """
        pm, risk, _, storage = self._dung_len(thanh_cong=False)
        assert pm.dong_bo({"BTCUSDT": mot_nen(high=96, low=93, close=94)}) == 0
        assert "BTCUSDT" in risk.positions
        assert storage.trades == []

    def test_vi_the_da_dong_tren_san_thi_khong_ep_stop_nua(self):
        """Sàn đã đóng đúng stop rồi -> chỉ ghi nhận, KHÔNG gửi thêm lệnh đóng."""
        pm, risk, _, storage = self._dung_len(san_con_vi_the=False)
        so = pm.dong_bo({"BTCUSDT": mot_nen(high=96, low=93, close=94)})
        assert so == 1
        assert pm.executor.da_goi == []            # khong gui lenh dong thua
        assert storage.trades[0]["exit_reason"] == "stop_loss"

    def test_tat_duoc_bang_cau_hinh(self):
        san = [{"symbol": "BTCUSDT", "side": "Buy", "size": "1", "avgPrice": "100"}]
        pm, risk, _, _ = make_pm(DRY_RUN=False, EP_STOP_PHIA_BOT=False,
                                 client=FakeClient(positions=san))
        pm.executor = self.ExecutorGhiNhan()
        risk.register_position(vi_the(entry=100, sl=95, tp=110))
        pm.dong_bo({"BTCUSDT": mot_nen(high=96, low=93, close=94)})
        assert pm.executor.da_goi == []

    def test_dung_moc_nen_lam_orderLinkId_de_thu_lai_khong_tao_lenh_trung(self):
        """Lần thử lại trong cùng cây nến phải mang đúng ID cũ — nếu dùng đồng
        hồ thì mỗi lần thử sinh một ID mới, và một timeout mạng thành hai lệnh.
        """
        pm, risk, _, _ = self._dung_len(thanh_cong=False)
        df = mot_nen(high=96, low=93, close=94)
        df["timestamp"] = [1700000000000]
        pm.dong_bo({"BTCUSDT": df})
        pm.dong_bo({"BTCUSDT": df})
        assert len(pm.executor.da_goi) == 2
        assert pm.executor.da_goi[0]["bar_timestamp"] == pm.executor.da_goi[1]["bar_timestamp"]

    def test_khong_ep_stop_khi_KHONG_doc_duoc_san(self):
        """Đọc sàn thất bại = đang mù. Trạng thái local lúc đó có thể đã cũ —
        vị thế có thể vừa được sàn đóng đúng stop mà ta chưa biết. Gửi lệnh
        đóng dựa trên trạng thái cũ là hành động lên một thứ có thể không còn.
        """
        pm, risk, _, storage = make_pm(DRY_RUN=False, client=FakeClient(loi_doc=True))
        pm.executor = self.ExecutorGhiNhan()
        risk.register_position(vi_the(entry=100, sl=95, tp=110))
        assert pm.dong_bo({"BTCUSDT": mot_nen(high=96, low=93, close=94)}) == 0
        assert pm.executor.da_goi == []      # khong gui lenh dong khi dang mu
        assert "BTCUSDT" in risk.positions
        assert storage.trades == []
