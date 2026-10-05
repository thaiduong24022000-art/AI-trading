"""
Kiem tra BAT BIEN QUAN TRONG NHAT cua he thong: khong nhin tuong lai.

Ca thiet ke dua vao mot loi hua duoc viet trong strategies/base.py: chi bao
duoc tinh TRUOC mot lan qua prepare(), roi doc tai dong i - va gia tri doc
duoc phai giong het nhu khi chi co du lieu den dong i.

Neu loi hua do sai, backtest se dep hon thuc te va khong ai phat hien ra,
vi moi con so van "chay dung". Do la ly do file nay ton tai.

Cach kiem: tinh chi bao tren TOAN BO du lieu, roi tinh lai tren du lieu bi
CAT tai dong i. Hai gia tri tai dong i phai bang nhau. Neu mot chi bao nao do
lo dung shift(-1), bfill hay rolling nhin ve sau, hai so nay se lech.
"""
import numpy as np
import pandas as pd
import pytest

from src import indicators
from src import regime as regime_mod

INDICATOR_COLUMNS = (
    "ema_fast", "ema_slow", "ema_trend", "rsi",
    "macd", "macd_signal", "macd_hist",
    "atr", "atr_pct", "adx",
    "bb_low", "bb_mid", "bb_high",
    "dc_low", "dc_high", "vol_ma", "vol_ratio",
)


@pytest.mark.parametrize("i", [250, 400, 699])
def test_chi_bao_khong_nhin_tuong_lai(raw_df, df_ind, i):
    partial = indicators.add_indicators(raw_df.iloc[:i + 1])
    assert len(partial) == i + 1

    for col in INDICATOR_COLUMNS:
        full_val = df_ind[col].iloc[i]
        part_val = partial[col].iloc[i]
        if pd.isna(full_val) and pd.isna(part_val):
            continue
        assert full_val == pytest.approx(part_val, rel=1e-9), (
            "%s tai dong %d doi gia tri khi co them du lieu tuong lai: %s != %s"
            % (col, i, full_val, part_val))


def test_phep_so_sanh_thuc_su_bat_duoc_lookahead(raw_df):
    """Chung minh phep so sanh o tren co rang.

    Mot bo test khong the that bai thi khong chung minh dieu gi. O day ta co y
    tao mot chuoi NHIN VE TUONG LAI (shift(-1)) va xac nhan rang dung phep so
    sanh cua test tren se phat hien ra no.
    """
    i = 300
    full = raw_df["close"].shift(-1)
    partial = raw_df.iloc[:i + 1]["close"].shift(-1)

    assert not pd.isna(full.iloc[i]), "chuoi day du 'biet' gia cua nen ke tiep"
    assert pd.isna(partial.iloc[i]), "chuoi bi cat thi khong the biet - do la khac biet ta can bat"


def test_donchian_khong_bao_gom_nen_hien_tai(raw_df):
    """Kenh Donchian phai tinh tren cac nen TRUOC do (da shift(1)).

    Neu khong, dieu kien 'close > dc_high' bien thanh so sanh gia voi chinh
    dinh cua no - breakout se gan nhu khong bao gio kich hoat, hoac kich hoat sai.
    """
    df = raw_df.iloc[:300].copy()
    _low, high = indicators.donchian(df, 20)
    i = 250
    dinh_20_nen_truoc = df["high"].iloc[i - 20:i].max()
    assert high.iloc[i] == pytest.approx(dinh_20_nen_truoc)


def test_atr_luon_duong_va_hop_ly(df_ind):
    atr = df_ind["atr"].dropna()
    assert len(atr) > 0
    assert (atr > 0).all(), "ATR am hoac bang 0 se lam RiskManager chia cho 0"
    assert (df_ind["atr_pct"].dropna() < 1.0).all(), "ATR lon hon ca gia la vo ly"


def test_rsi_nam_trong_0_100(df_ind):
    rsi = df_ind["rsi"].dropna()
    assert len(rsi) > 0
    assert rsi.between(0, 100).all()


def test_adx_nam_trong_0_100(df_ind):
    adx = df_ind["adx"].dropna()
    assert len(adx) > 0
    assert adx.between(0, 100).all()


def test_thieu_cot_thi_bao_loi_ro_rang(raw_df):
    with pytest.raises(ValueError, match="thieu cot"):
        indicators.add_indicators(raw_df.drop(columns=["volume"]))


@pytest.mark.parametrize("i", [300, 500, 699])
def test_regime_khong_nhin_tuong_lai(raw_df, df_ind, i, cfg):
    """Phan loai regime tai dong i cung khong duoc doi khi biet tuong lai."""
    partial = indicators.add_indicators(raw_df.iloc[:i + 1])
    full_reg = regime_mod.classify_at(df_ind, i, cfg)
    part_reg = regime_mod.classify_at(partial, i, cfg)

    assert full_reg.regime == part_reg.regime
    assert full_reg.confidence == pytest.approx(part_reg.confidence, rel=1e-9)


def test_warmup_du_cho_chi_bao_cham_nhat(df_ind):
    """warmup_bars() phai du cho ema_trend(200) - chi bao cham nhat."""
    i = indicators.warmup_bars()
    for col in INDICATOR_COLUMNS:
        assert not np.isnan(df_ind[col].iloc[i]), (
            "%s van con NaN tai nen warmup %d" % (col, i))
