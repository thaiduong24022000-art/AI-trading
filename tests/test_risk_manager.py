"""
Kiem tra risk engine - module quan trong nhat cua he thong.

Tieu chi danh gia ban dau khong phai loi nhuan, ma la: bot co tuan thu risk
limit khong. File nay la cach duy nhat tra loi cau hoi do ma khong phai doi
mat tien that de biet.

Trong tam la mot khang dinh cua Nang cap 3: RUI RO moi lenh la hang so, con
KHOI LUONG thi thay doi theo bien dong. Rat de viet code trong nhu the ma
thuc te lai khong phai, nen no duoc kiem truc tiep bang so.
"""
import math
import time

import pytest

from src.risk_manager import CircuitBreaker, Position, RiskManager
from tests.conftest import make_cfg


def _pos(symbol="BTCUSDT", side="Buy", qty=7.5, entry=100.0, stop=90.0):
    return Position(symbol=symbol, side=side, qty=qty, entry_price=entry,
                    stop_loss=stop, take_profit=115.0)


# ==========================================================
# Sizing: co dinh RUI RO, khong co dinh gia tri lenh
# ==========================================================
def test_sizing_mat_dung_R_phan_tram_khi_cham_stop():
    cfg = make_cfg(RISK_PER_TRADE=0.01, ATR_STOP_MULT=2.0, MAX_POSITION_NOTIONAL_PCT=1.0)
    rm = RiskManager(cfg)
    equity = 10000.0

    d = rm.evaluate("BTCUSDT", "Buy", entry_price=100.0, atr_value=5.0,
                    equity=equity, strength=1.0)

    assert d.approved, d.reasons
    assert d.stop_loss == pytest.approx(90.0)          # 100 - 2*5
    assert d.risk_amount == pytest.approx(equity * 0.01)
    assert d.qty == pytest.approx(10.0)                # 100 USDT rui ro / 10 USDT moi don vi


def test_bien_dong_cao_thi_khoi_luong_tu_dong_nho_lai():
    """Khang dinh trung tam cua Nang cap 3.

    Cung mot so von va cung mot muc rui ro, ma bien dong gap doi thi khoi luong
    phai giam mot nua - trong khi so tien rui ro giu nguyen. Day chinh la thu
    ma cach 'moi lenh 5% von' cua ban v1 khong lam duoc.
    """
    cfg = make_cfg(RISK_PER_TRADE=0.01, ATR_STOP_MULT=2.0, MAX_POSITION_NOTIONAL_PCT=1.0)
    rm = RiskManager(cfg)

    yen_tinh = rm.evaluate("BTCUSDT", "Buy", 100.0, atr_value=5.0, equity=10000.0)
    rm.remove_position("BTCUSDT")
    bien_dong = rm.evaluate("BTCUSDT", "Buy", 100.0, atr_value=10.0, equity=10000.0)

    assert bien_dong.qty == pytest.approx(yen_tinh.qty / 2.0)
    assert bien_dong.risk_amount == pytest.approx(yen_tinh.risk_amount)


def test_tin_hieu_yeu_thi_giam_quy_mo_chu_khong_tang():
    cfg = make_cfg(RISK_PER_TRADE=0.01, MAX_POSITION_NOTIONAL_PCT=1.0)
    rm = RiskManager(cfg)

    manh = rm.evaluate("BTCUSDT", "Buy", 100.0, 5.0, 10000.0, strength=1.0)
    rm.remove_position("BTCUSDT")
    yeu = rm.evaluate("BTCUSDT", "Buy", 100.0, 5.0, 10000.0, strength=0.5)
    rm.remove_position("BTCUSDT")
    qua_manh = rm.evaluate("BTCUSDT", "Buy", 100.0, 5.0, 10000.0, strength=5.0)

    assert yeu.qty == pytest.approx(manh.qty * 0.5)
    assert qua_manh.qty == pytest.approx(manh.qty), "strength > 1 khong duoc phep tang rui ro"


def test_tran_gia_tri_lenh_chan_khoi_luong_khi_bien_dong_qua_thap():
    """Khi ATR rat nho, cong thuc sizing cho ra khoi luong khong lo.

    Luc do tran MAX_POSITION_NOTIONAL_PCT phai cat bot - va he qua la lenh do
    rui ro IT hon R%, khong phai nhieu hon. Chan theo huong an toan.
    """
    cfg = make_cfg(RISK_PER_TRADE=0.0075, ATR_STOP_MULT=2.0, MAX_POSITION_NOTIONAL_PCT=0.25)
    rm = RiskManager(cfg)
    equity = 10000.0

    d = rm.evaluate("BTCUSDT", "Buy", 100.0, atr_value=0.1, equity=equity)

    assert d.approved
    assert d.qty * 100.0 == pytest.approx(equity * 0.25)
    assert d.risk_amount < equity * cfg.RISK_PER_TRADE


def test_stop_va_take_profit_dat_dung_huong():
    cfg = make_cfg(ATR_STOP_MULT=2.0, ATR_TP_MULT=3.0, ALLOW_SHORT=True,
                   MAX_POSITION_NOTIONAL_PCT=1.0)
    rm = RiskManager(cfg)

    mua = rm.evaluate("BTCUSDT", "Buy", 100.0, 5.0, 10000.0)
    assert mua.stop_loss < 100.0 < mua.take_profit

    ban = rm.evaluate("ETHUSDT", "Sell", 100.0, 5.0, 10000.0)
    assert ban.take_profit < 100.0 < ban.stop_loss

    rr = abs(mua.take_profit - 100.0) / abs(100.0 - mua.stop_loss)
    assert rr == pytest.approx(cfg.ATR_TP_MULT / cfg.ATR_STOP_MULT)


# ==========================================================
# Cac lop chan cap danh muc
# ==========================================================
def test_portfolio_heat_chan_lenh_lam_vuot_tran():
    cfg = make_cfg(MAX_PORTFOLIO_HEAT=0.02, RISK_PER_TRADE=0.0075,
                   MAX_OPEN_POSITIONS=10, MAX_POSITIONS_PER_CLUSTER=10,
                   MAX_POSITION_NOTIONAL_PCT=1.0)
    rm = RiskManager(cfg)
    equity = 10000.0

    # Hai vi the san co, moi cai rui ro 75 USDT = 0.75% von
    rm.register_position(_pos("AAAUSDT"))
    rm.register_position(_pos("BBBUSDT"))
    assert rm.current_heat(equity) == pytest.approx(0.015)

    # Lenh thu ba se day heat len 2.25% > tran 2%
    d = rm.evaluate("CCCUSDT", "Buy", 100.0, 5.0, equity)
    assert not d.approved
    assert any("heat" in r for r in d.reasons), d.reasons


def test_tran_tuong_quan_coi_cung_cum_la_mot_lenh():
    """BTC va ETH tuong quan ~0.85-0.9: mo ca hai khong phai da dang hoa."""
    cfg = make_cfg(MAX_POSITIONS_PER_CLUSTER=1, MAX_OPEN_POSITIONS=5,
                   MAX_POSITION_NOTIONAL_PCT=1.0)
    rm = RiskManager(cfg)
    rm.register_position(_pos("BTCUSDT"))

    cung_cum = rm.evaluate("ETHUSDT", "Buy", 100.0, 5.0, 10000.0)
    assert not cung_cum.approved
    assert any("cum" in r for r in cung_cum.reasons), cung_cum.reasons

    khac_cum = rm.evaluate("DOGEUSDT", "Buy", 100.0, 5.0, 10000.0)
    assert khac_cum.approved, khac_cum.reasons


def test_khong_mo_them_khi_da_co_vi_the_cung_ma():
    rm = RiskManager(make_cfg(MAX_POSITION_NOTIONAL_PCT=1.0))
    rm.register_position(_pos("BTCUSDT"))
    d = rm.evaluate("BTCUSDT", "Buy", 100.0, 5.0, 10000.0)
    assert not d.approved
    assert any("da co vi the" in r for r in d.reasons)


def test_gioi_han_so_vi_the_mo():
    cfg = make_cfg(MAX_OPEN_POSITIONS=2, MAX_POSITIONS_PER_CLUSTER=10,
                   MAX_POSITION_NOTIONAL_PCT=1.0, MAX_PORTFOLIO_HEAT=1.0)
    rm = RiskManager(cfg)
    rm.register_position(_pos("AAAUSDT"))
    rm.register_position(_pos("BBBUSDT"))

    d = rm.evaluate("CCCUSDT", "Buy", 100.0, 5.0, 10000.0)
    assert not d.approved
    assert any("toi da" in r for r in d.reasons)


def test_chan_ban_khong_khi_chay_spot():
    rm = RiskManager(make_cfg(ALLOW_SHORT=False))
    d = rm.evaluate("BTCUSDT", "Sell", 100.0, 5.0, 10000.0)
    assert not d.approved
    assert any("ALLOW_SHORT" in r for r in d.reasons)


@pytest.mark.parametrize("atr_value", [0.0, -1.0, float("nan"), None])
def test_atr_khong_hop_le_thi_tu_choi(atr_value):
    """Khong co ATR hop le thi khong the dat stop an toan - tu choi con hon doan."""
    rm = RiskManager(make_cfg())
    d = rm.evaluate("BTCUSDT", "Buy", 100.0, atr_value, 10000.0)
    assert not d.approved
    assert any("ATR" in r for r in d.reasons)


def test_von_khong_hop_le_thi_tu_choi():
    rm = RiskManager(make_cfg())
    assert not rm.evaluate("BTCUSDT", "Buy", 100.0, 5.0, 0.0).approved
    assert not rm.evaluate("BTCUSDT", "Buy", 100.0, 5.0, -100.0).approved


def test_breaker_bat_thi_moi_lenh_deu_bi_chan():
    breaker = CircuitBreaker(make_cfg())
    breaker.trip("test")
    rm = RiskManager(make_cfg(), breaker)

    d = rm.evaluate("BTCUSDT", "Buy", 100.0, 5.0, 10000.0)
    assert not d.approved
    assert any("circuit breaker" in r for r in d.reasons)


def test_heat_tinh_dung_tren_nhieu_vi_the():
    rm = RiskManager(make_cfg())
    assert rm.current_heat(10000.0) == 0.0
    rm.register_position(_pos("AAAUSDT", qty=10.0, entry=100.0, stop=90.0))   # rui ro 100
    rm.register_position(_pos("BBBUSDT", qty=5.0, entry=100.0, stop=90.0))    # rui ro 50
    assert rm.current_heat(10000.0) == pytest.approx(0.015)


def test_sync_positions_thay_the_toan_bo_trang_thai():
    """Sau doi soat, nguon su that la SAN - trang thai local phai bi ghi de."""
    rm = RiskManager(make_cfg())
    rm.register_position(_pos("CUUSDT"))
    rm.sync_positions({"MOIUSDT": _pos("MOIUSDT")})
    assert set(rm.positions) == {"MOIUSDT"}


# ==========================================================
# Circuit breakers
# ==========================================================
def test_thua_lien_tiep_bat_breaker_va_mot_lenh_thang_xoa_chuoi():
    cfg = make_cfg(MAX_CONSECUTIVE_LOSSES=3)
    b = CircuitBreaker(cfg)

    b.record_trade_result(-10.0)
    b.record_trade_result(-10.0)
    assert not b.tripped

    b.record_trade_result(+5.0)          # thang -> chuoi ve 0
    assert b.consecutive_losses == 0

    b.record_trade_result(-10.0)
    b.record_trade_result(-10.0)
    assert not b.tripped
    b.record_trade_result(-10.0)
    assert b.tripped
    assert "consecutive_losses" in b.reason


def test_drawdown_ngay_bat_breaker():
    cfg = make_cfg(MAX_DAILY_DRAWDOWN=0.05)
    b = CircuitBreaker(cfg)
    b.reset_daily(10000.0)

    b.check_equity(9600.0)               # -4%
    assert not b.tripped
    b.check_equity(9400.0)               # -6%
    assert b.tripped
    assert b.reason.startswith("drawdown")


def test_sang_ngay_moi_xoa_trip_do_drawdown_nhung_khong_xoa_trip_khac():
    """reset_daily chi go trip do drawdown.

    Trip vi thua lien tiep hay loi API la dau hieu co the co van de he thong,
    nen no doi NGUOI xem - khong tu het khi sang ngay moi.
    """
    b = CircuitBreaker(make_cfg(MAX_DAILY_DRAWDOWN=0.05))
    b.reset_daily(10000.0)
    b.check_equity(9000.0)
    assert b.tripped
    b.reset_daily(9000.0)
    assert not b.tripped

    b.trip("api_errors: 3 loi lien tiep")
    b.reset_daily(9000.0)
    assert b.tripped, "trip khong phai drawdown phai giu nguyen cho nguoi kiem tra"


def test_du_lieu_cu_bat_breaker():
    cfg = make_cfg(MAX_DATA_STALENESS_SECONDS=900)
    b = CircuitBreaker(cfg)

    b.check_data_freshness(time.time() - 60)
    assert not b.tripped
    b.check_data_freshness(time.time() - 1800)
    assert b.tripped
    assert "du lieu cu" in b.reason


def test_gia_nhay_bat_thuong_bat_breaker():
    cfg = make_cfg(MAX_BAR_JUMP_ATR=5.0)
    b = CircuitBreaker(cfg)

    b.check_price_jump(bar_range=20.0, atr_value=10.0)   # 2x ATR - binh thuong
    assert not b.tripped
    b.check_price_jump(bar_range=60.0, atr_value=10.0)   # 6x ATR
    assert b.tripped


def test_atr_bang_khong_khong_lam_vo_check_price_jump():
    b = CircuitBreaker(make_cfg())
    b.check_price_jump(bar_range=100.0, atr_value=0.0)
    assert not b.tripped, "chia cho 0 phai duoc bo qua, khong duoc trip nham"


def test_loi_api_lien_tiep_bat_breaker_va_thanh_cong_xoa_dem():
    cfg = make_cfg(MAX_CONSECUTIVE_API_ERRORS=3)
    b = CircuitBreaker(cfg)

    b.record_api_error()
    b.record_api_error()
    b.record_api_success()
    assert b.consecutive_api_errors == 0
    assert not b.tripped

    for _ in range(3):
        b.record_api_error()
    assert b.tripped


def test_manual_reset_xoa_moi_trang_thai():
    b = CircuitBreaker(make_cfg())
    b.record_api_error()
    b.trip("bat ky ly do gi")
    b.manual_reset()

    assert not b.tripped
    assert b.reason == ""
    assert b.consecutive_api_errors == 0
    assert b.consecutive_losses == 0


def test_position_tinh_dung_rui_ro_va_gia_tri():
    p = _pos(qty=2.0, entry=100.0, stop=95.0)
    assert p.risk_amount == pytest.approx(10.0)
    assert p.notional == pytest.approx(200.0)


def test_heat_bang_1_khi_von_khong_duong():
    """Von <= 0 phai coi nhu het room, khong duoc chia cho 0."""
    rm = RiskManager(make_cfg())
    assert rm.current_heat(0.0) == 1.0
    assert not math.isnan(rm.current_heat(-5.0))
