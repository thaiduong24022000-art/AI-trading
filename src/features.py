"""
Dac trung cho AI policy - gom dac trung TUNG MA va XEP HANG CAT NGANG.

VI SAO CAN XEP HANG CAT NGANG:
Phan lon phuong sai cua mot dong coin la bien dong CHUNG cua ca thi truong -
khi BTC do thi gan nhu moi thu do. Do la phan khong ai du bao duoc, va no lan
at moi tin hieu rieng. Hoi "BTC se len hay xuong" la hoi thang vao phan nhieu
do. Hoi "trong 23 ma, cai nao se manh hon trung vi" thi phan chung bi triet
tieu, va cai con lai moi la thu co the hoc duoc.

CHONG LOOKAHEAD:
- Dac trung tung ma dung indicators.add_indicators (da co test bat bien).
- Xep hang cat ngang chi dung du lieu CUNG MOT MOC THOI GIAN tren cac ma khac,
  khong dung moc nao ve sau. Day la diem de sai nhat khi ghep panel: neu cac
  ma bi lech moc thoi gian thi mot ma co the "nhin thay" tuong lai cua ma khac.
  Vi vay panel duoc ghep theo timestamp CHINH XAC, khong forward-fill.
"""
from typing import Dict, List

import numpy as np
import pandas as pd

import config
from . import indicators, labeling

# Dac trung tung ma. Giu NHO co chu dich: cang nhieu dac trung tren cung mot
# luong du lieu thi xac suat tim duoc mau ngau nhien dep cang cao.
FEATURES: List[str] = [
    "mom_6", "mom_24", "mom_72",        # dong luong nhieu do dai
    "atr_pct", "vol_24",                # bien dong
    "adx", "ema_spread", "gia_tren_ema200",   # xu huong
    "rsi", "bb_pos", "dc_pos",          # vi tri trong bien do
    "vol_ratio",                        # khoi luong
]

# Dac trung tu du lieu PHAI SINH - thu ma OHLCV khong nhin thay.
# Giu it (6 cot) co chu dich: 12 dac trung gia/khoi luong da cho IC ~ 0, va
# them cang nhieu cot tren cung luong du lieu thi cang de tim thay mau ngau nhien.
FEATURES_DERIV: List[str] = [
    "funding", "funding_ma", "funding_z",   # ai dang tra tien cho ai
    "oi_chg_6", "oi_chg_24",                # tien don bay vao hay ra
    "oi_gia_phan_ky",                       # OI tang khi gia giam = short xay vi the
]

# Dac trung duoc xep hang cat ngang (them hau to _r)
RANKED: List[str] = ["mom_6", "mom_24", "mom_72", "atr_pct", "vol_24",
                     "adx", "ema_spread", "rsi", "bb_pos", "dc_pos", "vol_ratio"]
RANKED_DERIV: List[str] = ["funding", "funding_z", "oi_chg_24", "oi_gia_phan_ky"]


def dac_trung_mot_ma(df: pd.DataFrame) -> pd.DataFrame:
    """Them cot dac trung cho mot ma. Chi dung toan tu nhan qua."""
    if "atr" not in df.columns:
        df = indicators.add_indicators(df)
    out = df.copy()
    close = out["close"]

    out["mom_6"] = close.pct_change(6)
    out["mom_24"] = close.pct_change(24)
    out["mom_72"] = close.pct_change(72)

    ret1 = close.pct_change()
    out["vol_24"] = ret1.rolling(24, min_periods=24).std()

    # Chuan hoa theo gia de so sanh duoc giua cac ma co gia khac nhau hoan toan
    out["ema_spread"] = (out["ema_fast"] - out["ema_slow"]) / close
    out["gia_tren_ema200"] = close / out["ema_trend"] - 1.0

    bb_rong = (out["bb_high"] - out["bb_low"]).replace(0.0, np.nan)
    out["bb_pos"] = (close - out["bb_low"]) / bb_rong

    dc_rong = (out["dc_high"] - out["dc_low"]).replace(0.0, np.nan)
    out["dc_pos"] = (close - out["dc_low"]) / dc_rong

    return out


def them_dac_trung_phai_sinh(df: pd.DataFrame, deriv: pd.DataFrame) -> pd.DataFrame:
    """Ghep funding/open interest vao nen va sinh dac trung.

    deriv da duoc ghep LUI tu luc tai (merge_asof backward), nen moi dong chi
    chua gia tri cong bo truoc khi nen do mo - khong co lookahead.
    """
    out = df.copy()
    out["timestamp"] = out["timestamp"].astype("int64")
    d = deriv.copy()
    d["timestamp"] = d["timestamp"].astype("int64")
    out = out.merge(d[["timestamp", "funding", "open_interest"]], on="timestamp", how="left")

    f = out["funding"]
    out["funding_ma"] = f.rolling(9, min_periods=5).mean()      # ~3 ngay funding
    sd = f.rolling(60, min_periods=30).std().replace(0.0, np.nan)
    out["funding_z"] = (f - f.rolling(60, min_periods=30).mean()) / sd

    oi = out["open_interest"]
    out["oi_chg_6"] = oi.pct_change(6)
    out["oi_chg_24"] = oi.pct_change(24)

    # OI tang trong khi gia giam => phe short dang xay vi the (va nguoc lai).
    # Tich cua hai chieu bat duoc dieu do trong mot con so.
    out["oi_gia_phan_ky"] = out["oi_chg_24"] * (-out["mom_24"])

    return out


def xay_panel(frames: Dict[str, pd.DataFrame], cfg=config,
              max_horizon: int = 60, gan_nhan: bool = True,
              derivs: Dict[str, pd.DataFrame] = None) -> pd.DataFrame:
    """Ghep nhieu ma thanh mot panel (timestamp, symbol) kem nhan va xep hang.

    gan_nhan=False dung khi chay LIVE: luc do khong co tuong lai de gan nhan,
    ta chi can dac trung.
    derivs: {symbol: DataFrame funding/open_interest} - neu None thi bo qua.
    """
    phan = []
    for sym, df in frames.items():
        d = dac_trung_mot_ma(df)
        if derivs and sym in derivs:
            d = them_dac_trung_phai_sinh(d, derivs[sym])
        if gan_nhan:
            d = pd.concat([d, labeling.gan_nhan_hai_chieu(d, cfg, max_horizon)], axis=1)
        d["symbol"] = sym
        phan.append(d)

    panel = pd.concat(phan, ignore_index=True)
    panel = panel.dropna(subset=["timestamp"])
    panel["timestamp"] = panel["timestamp"].astype("int64")

    # Xep hang cat ngang tai TUNG moc thoi gian.
    # pct=True cho ra vi tri tuong doi 0..1, khong phu thuoc so ma co mat o moc
    # do - quan trong vi cac ma len san vao nhung thoi diem khac nhau.
    nhom = panel.groupby("timestamp", sort=False)
    for col in RANKED + [c for c in RANKED_DERIV if c in panel.columns]:
        panel[col + "_r"] = nhom[col].rank(pct=True)

    # So ma co mat tai moc do. Xep hang tren 3 ma gan nhu vo nghia, tren 20 ma
    # thi co y nghia - nghien cuu phia sau se loc theo cot nay.
    panel["n_ma"] = nhom["close"].transform("size")

    return panel.sort_values(["timestamp", "symbol"]).reset_index(drop=True)


def cot_dac_trung(co_xep_hang: bool = True, co_phai_sinh: bool = False) -> List[str]:
    cols = list(FEATURES)
    ranked = list(RANKED)
    if co_phai_sinh:
        cols += FEATURES_DERIV
        ranked += RANKED_DERIV
    return cols + ([c + "_r" for c in ranked] if co_xep_hang else [])
