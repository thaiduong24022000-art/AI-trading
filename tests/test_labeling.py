"""
Kiem tra gan nhan triple-barrier.

Nhan la thu ma AI policy hoc theo. Nhan sai thi mo hinh hoc dung mot bai toan
sai, va khong co lop nao phia sau phat hien ra dieu do - backtest van chay,
walk-forward van ra so, chi co dieu ca he thong dang toi uu nham muc tieu.

Du lieu o day duoc dung PHANG co chu dich (ATR = 2.0 chinh xac) de moi nguong
barrier deu tinh tay duoc.
"""
import numpy as np
import pandas as pd
import pytest

from src import indicators, labeling
from tests.conftest import make_cfg

CFG = make_cfg(ATR_STOP_MULT=2.0, ATR_TP_MULT=3.0, SLIPPAGE=0.0, FEE_TAKER=0.0)


def _df(n=60, price=100.0):
    ts = pd.date_range("2024-01-01", periods=n, freq="4h")
    df = pd.DataFrame({
        "timestamp": ts.astype("datetime64[ms]").astype("int64"),
        "datetime": ts,
        "open": price, "high": price + 1.0, "low": price - 1.0,
        "close": price, "volume": 1000.0,
    })
    return indicators.add_indicators(df)


def test_atr_bang_2_de_moi_nguong_tinh_tay_duoc():
    df = _df()
    assert df["atr"].iloc[30] == pytest.approx(2.0)


def test_cham_take_profit_thi_nhan_duong():
    df = _df()
    i = 30
    df.loc[i + 2, "high"] = 200.0          # vuot xa TP = 100 + 3*2 = 106
    out = labeling.triple_barrier(df, "Buy", CFG, max_horizon=10)

    assert out["label"].iloc[i] == labeling.TP_TRUOC
    assert out["ret_net"].iloc[i] == pytest.approx(0.06)   # +3xATR tren gia 100
    assert out["bars_held"].iloc[i] == 2


def test_cham_stop_thi_nhan_am():
    df = _df()
    df.loc[32, "low"] = 50.0               # duoi stop = 100 - 2*2 = 96
    out = labeling.triple_barrier(df, "Buy", CFG, max_horizon=10)

    assert out["label"].iloc[30] == labeling.SL_TRUOC
    assert out["ret_net"].iloc[30] == pytest.approx(-0.04)


def test_cham_ca_hai_trong_mot_nen_thi_tinh_STOP():
    """Phai giong gia dinh bi quan cua backtest engine.

    Neu nhan gia dinh cham TP truoc con engine gia dinh cham SL truoc, thi mo
    hinh duoc thuong cho nhung setup ma he thong that su thua tien.
    """
    df = _df()
    df.loc[32, "low"] = 50.0
    df.loc[32, "high"] = 200.0
    out = labeling.triple_barrier(df, "Buy", CFG, max_horizon=10)

    assert out["label"].iloc[30] == labeling.SL_TRUOC


def test_khong_cham_gi_thi_het_han():
    df = _df()
    out = labeling.triple_barrier(df, "Buy", CFG, max_horizon=5)

    assert out["label"].iloc[30] == labeling.HET_HAN
    assert not out["resolved"].iloc[30]
    assert out["bars_held"].iloc[30] == 5


def test_chieu_ban_dao_nguoc_barrier():
    df = _df()
    df.loc[32, "low"] = 50.0               # gia giam manh: tot cho lenh BAN
    mua = labeling.triple_barrier(df, "Buy", CFG, max_horizon=10)
    ban = labeling.triple_barrier(df, "Sell", CFG, max_horizon=10)

    assert mua["label"].iloc[30] == labeling.SL_TRUOC
    assert ban["label"].iloc[30] == labeling.TP_TRUOC
    assert ban["ret_net"].iloc[30] > 0


def test_phi_va_slippage_lam_loi_nhuan_giam():
    df = _df()
    df.loc[32, "high"] = 200.0
    khong_phi = labeling.triple_barrier(df, "Buy", CFG, max_horizon=10)
    co_phi = labeling.triple_barrier(
        df, "Buy", make_cfg(ATR_STOP_MULT=2.0, ATR_TP_MULT=3.0,
                            SLIPPAGE=0.0005, FEE_TAKER=0.001), max_horizon=10)

    assert co_phi["ret_net"].iloc[30] < khong_phi["ret_net"].iloc[30]


def test_vao_lenh_tai_gia_MO_CUA_nen_ke_tiep():
    """Cung quy tac chong lookahead ma engine dung: tin hieu o nen i thi khop
    o gia mo cua nen i+1, khong phai gia dong cua nen i."""
    df = _df()
    # Ca ba nen phai NHAT QUAN quanh 150. Neu chi doi open ma de low=99 thi
    # cay nen do rong 99-151 va cham stop ngay - dung nhung khong kiem duoc
    # dieu ta muon kiem.
    for j in (31, 32, 33):
        df.loc[j, ["open", "high", "low", "close"]] = [150.0, 151.0, 149.0, 150.0]
    df.loc[33, "high"] = 300.0             # cham TP tinh tu gia vao 150

    out = labeling.triple_barrier(df, "Buy", CFG, max_horizon=10)
    # TP = 150 + 3*2 = 156 -> loi nhuan 6/150 = 4%, khong phai 6/100 = 6%
    assert out["ret_net"].iloc[30] == pytest.approx(0.04)
    assert out["bars_held"].iloc[30] == 3


def test_atr_khong_hop_le_thi_bo_qua_khong_vo():
    df = _df()
    df.loc[:, "atr"] = np.nan
    out = labeling.triple_barrier(df, "Buy", CFG, max_horizon=10)

    assert (out["label"] == 0).all()
    assert out["ret_net"].isna().all()


def test_nhan_hai_chieu_tra_ve_du_cot():
    df = _df()
    df.loc[32, "high"] = 200.0
    out = labeling.gan_nhan_hai_chieu(df, CFG, max_horizon=10)

    for c in ("label_long", "ret_long", "label_short", "ret_short",
              "bars_held", "resolved", "edge"):
        assert c in out.columns
    # gia tang manh -> edge (mua tru ban) phai duong
    assert out["edge"].iloc[30] > 0


def test_bars_held_dung_de_purge_duoc():
    """Purge dua vao bars_held: mau nao co nhan keo dai sang vung test phai bi
    loai khoi train. Neu bars_held sai thi purge sai va ro ri du lieu."""
    df = _df()
    df.loc[35, "high"] = 200.0
    out = labeling.triple_barrier(df, "Buy", CFG, max_horizon=20)

    assert out["bars_held"].iloc[30] == 5
    assert (out["bars_held"] >= 0).all()
