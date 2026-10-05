"""
Kiem tra BON QUY TAC TRUNG THUC ma backtest/engine.py tu dat ra cho minh.

Backtest sai la nguyen nhan so mot khien bot lai tren giay va lo ngoai doi,
va cai nguy hiem la backtest sai van chay tron tru - khong co gi bao loi.
Chi co test moi phat hien duoc.

Du lieu trong file nay duoc dung PHANG mot cach co chu dich: gia co dinh,
bien do moi nen dung bang 2 -> ATR bang dung 2.0. Nho vay moi con so ky vong
deu tinh tay duoc, va khi mot test do that bai thi no chi ra dung mot nguyen
nhan chu khong phai "so lieu khac ky vong".
"""
import pandas as pd
import pytest

from backtest import engine
from src import indicators
from src.strategies.base import BUY, SELL, Strategy
from tests.conftest import make_cfg

WARMUP = max(indicators.warmup_bars(), 60)
FIRE_AT = WARMUP + 10


def _cfg(**overrides):
    base = dict(RISK_PER_TRADE=0.01, ATR_STOP_MULT=2.0, ATR_TP_MULT=3.0,
                MAX_POSITION_NOTIONAL_PCT=1.0, FEE_TAKER=0.001, SLIPPAGE=0.0005,
                ALLOW_SHORT=False, MIN_SIGNAL_STRENGTH=0.15,
                MAX_OPEN_POSITIONS=3, MAX_POSITIONS_PER_CLUSTER=1,
                MAX_PORTFOLIO_HEAT=0.03)
    base.update(overrides)
    return make_cfg(**base)


def _flat_df(n=260, price=100.0, freq="h"):
    """Gia phang: bien do moi nen = 2 => ATR = 2.0 chinh xac.

    Chi bao duoc tinh TRUOC khi test sua open/high/low cua vai nen cu the,
    nen ATR giu nguyen 2.0 va moi ky vong ve stop/take-profit deu tinh tay duoc.
    """
    ts = pd.date_range("2024-01-01", periods=n, freq=freq)
    df = pd.DataFrame({
        "timestamp": ts.astype("datetime64[ms]").astype("int64"),
        "datetime": ts,
        "open": price, "high": price + 1.0, "low": price - 1.0,
        "close": price, "volume": 1000.0,
    })
    return indicators.add_indicators(df)


class FireAt(Strategy):
    """Chien luoc gia: ban tin hieu tai dung mot nen da chon."""
    name = "fire_at"
    preferred_regimes = ("trend", "range", "high_vol")

    def __init__(self, bar: int, action: str = BUY):
        super().__init__()
        self.bar = bar
        self.fixed_action = action

    def generate_at(self, df, i):
        sig = self._base_signal()
        if i == self.bar:
            sig.action, sig.strength = self.fixed_action, 1.0
        sig.reason = "test"
        return sig


class FireAlways(Strategy):
    """Chien luoc gia: luon muon vao lenh. Dung de do cac lop chan."""
    name = "fire_always"
    preferred_regimes = ("trend", "range", "high_vol")

    def generate_at(self, df, i):
        sig = self._base_signal()
        if i >= WARMUP:
            sig.action, sig.strength = BUY, 1.0
        sig.reason = "test"
        return sig


def _run(df, strategies, cfg, equity=10000.0):
    return engine.run(df, strategies, initial_equity=equity, cfg=cfg,
                      use_regime=False, symbol="BACKTEST")


# ==========================================================
# Quy tac 1: khong lookahead - khop tai gia MO CUA cua nen KE TIEP
# ==========================================================
def test_khop_lenh_tai_gia_mo_nen_ke_tiep_khong_phai_gia_dong_nen_tin_hieu():
    """Day la cach tu lua pho bien nhat trong backtest.

    Tin hieu sinh ra tu nen i thi den nen i+1 moi dat duoc lenh. Khop tai gia
    dong cua chinh nen i nghia la gia dinh minh mua duoc o mot muc gia ma luc
    quyet dinh chua ai biet.
    """
    cfg = _cfg()
    df = _flat_df()
    df.loc[FIRE_AT + 1, "open"] = 110.0        # nen ke tiep mo cao han han
    df.loc[FIRE_AT + 1, "high"] = 111.0
    df.loc[FIRE_AT + 2, "low"] = 80.0          # ep cham stop de lenh duoc ghi nhan

    result = _run(df, [FireAt(FIRE_AT)], cfg)

    assert len(result.trades) == 1
    entry = result.trades[0]["entry_price"]
    assert entry == pytest.approx(110.0 * (1 + cfg.SLIPPAGE))
    assert entry != pytest.approx(100.0 * (1 + cfg.SLIPPAGE)), (
        "da khop tai gia dong cua nen sinh tin hieu - do la lookahead")


def test_khong_vao_lenh_truoc_khi_du_warmup():
    cfg = _cfg()
    df = _flat_df()
    result = _run(df, [FireAt(WARMUP - 50)], cfg)
    assert result.trades == []
    assert result.signals_generated == 0


# ==========================================================
# Quy tac 2: phi va slippage ca hai chieu
# ==========================================================
def test_phi_bi_tru_o_ca_hai_chieu():
    cfg = _cfg()
    df = _flat_df()
    df.loc[FIRE_AT + 2, "low"] = 80.0

    t = _run(df, [FireAt(FIRE_AT)], cfg).trades[0]

    phi_ky_vong = (t["entry_price"] + t["exit_price"]) * t["qty"] * cfg.FEE_TAKER
    assert t["fees"] == pytest.approx(phi_ky_vong)

    lai_truoc_phi = (t["exit_price"] - t["entry_price"]) * t["qty"]
    assert t["pnl"] == pytest.approx(lai_truoc_phi - t["fees"])
    assert t["pnl"] < lai_truoc_phi, "phi phai lam ket qua te di, khong duoc bo qua"


def test_slippage_luon_lam_gia_te_di_cho_nguoi_dat_lenh():
    cfg = _cfg()
    df = _flat_df()
    df.loc[FIRE_AT + 2, "low"] = 80.0

    t = _run(df, [FireAt(FIRE_AT)], cfg).trades[0]

    assert t["entry_price"] > 100.0, "lenh mua phai khop cao hon gia niem yet"
    assert t["exit_price"] < t["entry_price"] - 4.0 + 0.01, "lenh ban phai khop thap hon stop"


def test_phi_bang_khong_thi_ket_qua_tot_hon():
    """Kiem chung rang phi thuc su thay doi ket luan, khong chi la con so trang tri."""
    df = _flat_df()
    df.loc[FIRE_AT + 2, "low"] = 80.0

    co_phi = _run(df, [FireAt(FIRE_AT)], _cfg()).trades[0]["pnl"]
    khong_phi = _run(df, [FireAt(FIRE_AT)], _cfg(FEE_TAKER=0.0, SLIPPAGE=0.0)).trades[0]["pnl"]
    assert khong_phi > co_phi


# ==========================================================
# Quy tac 3: cham ca stop lan take-profit trong mot nen -> tinh STOP
# ==========================================================
def test_nen_cham_ca_stop_lan_tp_thi_tinh_stop():
    """Ta khong biet thu tu gia trong nen. Doan theo huong co loi cho minh
    cung la mot dang lookahead, nen phai gia dinh bi quan."""
    cfg = _cfg()
    df = _flat_df()
    df.loc[FIRE_AT + 2, "low"] = 80.0     # duoi stop (96.05)
    df.loc[FIRE_AT + 2, "high"] = 130.0   # tren take-profit (106.05)

    t = _run(df, [FireAt(FIRE_AT)], cfg).trades[0]

    assert t["exit_reason"] == "stop_loss"
    assert t["pnl"] < 0


def test_chi_cham_take_profit_thi_van_an_tp():
    cfg = _cfg()
    df = _flat_df()
    df.loc[FIRE_AT + 2, "high"] = 130.0

    t = _run(df, [FireAt(FIRE_AT)], cfg).trades[0]

    assert t["exit_reason"] == "take_profit"
    assert t["pnl"] > 0


def test_thoat_khi_tin_hieu_dao_chieu():
    cfg = _cfg(ALLOW_SHORT=True)
    df = _flat_df()

    class DaoChieu(Strategy):
        name = "dao_chieu"
        preferred_regimes = ("range",)

        def generate_at(self, df_, i):
            sig = self._base_signal()
            if i == FIRE_AT:
                sig.action, sig.strength = BUY, 1.0
            elif i == FIRE_AT + 3:
                sig.action, sig.strength = SELL, 1.0
            sig.reason = "test"
            return sig

    t = _run(df, [DaoChieu()], cfg).trades[0]
    assert t["exit_reason"] == "signal_reverse"


# ==========================================================
# Quy tac 4: dung chinh RiskManager cua ban live
# ==========================================================
def test_khoi_luong_khop_voi_cong_thuc_rui_ro_cua_ban_live():
    cfg = _cfg()
    df = _flat_df()
    df.loc[FIRE_AT + 2, "low"] = 80.0

    t = _run(df, [FireAt(FIRE_AT)], cfg, equity=10000.0).trades[0]

    # ATR = 2.0 -> stop cach entry 4.0 -> rui ro 1% cua 10000 = 100 -> qty = 25
    rui_ro = abs(t["entry_price"] - (t["entry_price"] - cfg.ATR_STOP_MULT * 2.0)) * t["qty"]
    assert rui_ro == pytest.approx(10000.0 * cfg.RISK_PER_TRADE)
    assert t["qty"] == pytest.approx(25.0)


def test_lenh_ban_bi_chan_khi_khong_cho_short():
    cfg = _cfg(ALLOW_SHORT=False)
    df = _flat_df()
    result = _run(df, [FireAt(FIRE_AT, action=SELL)], cfg)

    assert result.trades == []
    assert result.rejected_by_risk >= 1


def test_moi_lenh_deu_duoc_gan_nhan_regime():
    """Nhan regime la nguyen lieu cho cong 'co lai o >= 2/3 regime'."""
    cfg = _cfg()
    df = _flat_df()
    df.loc[FIRE_AT + 2, "low"] = 80.0

    t = _run(df, [FireAt(FIRE_AT)], cfg).trades[0]
    assert t["regime"], "lenh khong co nhan regime thi cong thong ke khong danh gia duoc"


# ==========================================================
# Circuit breaker trong backtest
# ==========================================================
def _df_giam_deu(n=400, freq="h"):
    """Gia giam deu 1 don vi moi nen -> moi lenh mua deu cham stop."""
    ts = pd.date_range("2024-01-01", periods=n, freq=freq)
    close = pd.Series([1000.0 - i for i in range(n)])
    df = pd.DataFrame({
        "timestamp": ts.astype("datetime64[ms]").astype("int64"),
        "datetime": ts,
        "open": close, "high": close + 1.0, "low": close - 1.0,
        "close": close, "volume": 1000.0,
    })
    return indicators.add_indicators(df)


def test_breaker_reset_theo_ngay_CUA_NEN_khong_theo_dong_ho_may():
    """Test hoi quy cho mot loi lam moi backtest bi cat cut.

    CircuitBreaker.reset_daily() dua vao date.today(). Trong backtest "hom nay"
    khong bao gio doi, nen consecutive_losses khong bao gio ve 0: ca lan chay
    chet vinh vien o chuoi thua dau tien, va moi con so sau do la vo nghia.
    Ngay phai duoc tinh theo timestamp CUA NEN.
    """
    cfg = _cfg(MAX_CONSECUTIVE_LOSSES=5)
    result = _run(_df_giam_deu(n=400, freq="h"), [FireAlways()], cfg)

    assert len(result.trades) > cfg.MAX_CONSECUTIVE_LOSSES, (
        "backtest dung lai o %d lenh - breaker khong duoc reset khi sang ngay moi"
        % len(result.trades))
    assert result.breaker_trips >= 1, "so lan bat breaker phai duoc dem va bao cao"


def test_trong_cung_mot_ngay_breaker_van_dung_han():
    """Mat con lai: trong pham vi mot ngay, chuoi thua VAN phai dung bot lai."""
    cfg = _cfg(MAX_CONSECUTIVE_LOSSES=5)
    result = _run(_df_giam_deu(n=400, freq="min"), [FireAlways()], cfg)

    assert len(result.trades) == cfg.MAX_CONSECUTIVE_LOSSES
    assert result.breaker_trips == 0


def test_du_lieu_qua_ngan_thi_tra_ve_ket_qua_rong_chu_khong_vo():
    result = _run(_flat_df(n=WARMUP + 3), [FireAt(FIRE_AT)], _cfg())
    assert result.trades == []
    assert len(result.equity_curve) >= 1
