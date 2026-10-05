"""
Gan nhan triple-barrier - nen tang cho AI policy hoc duoc.

NGUYEN TAC TRUNG TAM: NHAN PHAI KHOP VOI CACH THOAT LENH THAT.

Cach de nhat va sai nhat la lay "loi nhuan cua nen ke tiep" lam nhan. Lam vay
la huan luyen mo hinh du bao MOT thu roi dem di giao dich MOT THU KHAC: bot
khong thoat lenh sau dung mot nen, no thoat khi cham stop-loss hoac take-profit
theo ATR. Neu nhan khong phan anh dieu do thi mo hinh hoc mot bai toan khong
ton tai.

O day nhan duoc dinh nghia dung nhu RiskManager thuc thi:
  vao lenh tai gia MO CUA nen ke tiep (co slippage), stop = ATR_STOP_MULT x ATR,
  take-profit = ATR_TP_MULT x ATR, va neu mot nen cham CA HAI thi tinh STOP -
  cung gia dinh bi quan ma backtest engine dung.

LOOKAHEAD: nhan BAT BUOC nhin ve tuong lai - do la ban chat cua nhan. Dieu cam
tuyet doi la de thong tin do ro sang DAC TRUNG. Ngoai ra, vi mot nhan mat nhieu
nen moi ngã ngũ, cac nhan CHONG LAN nhau theo thoi gian: khi chia train/test
phai loai bo (purge) nhung mau co nhan keo dai sang vung test, neu khong la ro
ri. Cot `bars_held` ton tai chinh de lam viec do.
"""
import numpy as np
import pandas as pd

import config

TP_TRUOC = 1
SL_TRUOC = -1
HET_HAN = 0


def triple_barrier(df: pd.DataFrame, side: str = "Buy", cfg=config,
                   max_horizon: int = 60) -> pd.DataFrame:
    """Nhan cho tung nen: neu vao lenh o day thi cham TP truoc hay SL truoc?

    Tra ve DataFrame cung chi so voi df, gom:
      label      : 1 = TP truoc, -1 = SL truoc, 0 = het han chua cham gi
      ret_net    : loi nhuan % da tru phi va slippage ca hai chieu
      bars_held  : so nen tu luc vao den luc thoat (dung de purge)
      resolved   : nhan da nga ngu trong max_horizon chua

    max_horizon gioi han thoi gian giu lenh. No khong phai tham so tuy y: mot
    lenh khong cham barrier nao sau 60 nen 4h (10 ngay) thi ATR luc vao da khong
    con mo ta thi truong hien tai nua, va giu tiep la mot cuoc dat cuoc khac.
    """
    if "atr" not in df.columns:
        raise ValueError("df phai co cot 'atr' - goi indicators.add_indicators truoc")

    n = len(df)
    open_ = df["open"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    atr = df["atr"].to_numpy(dtype=float)

    la_mua = side == "Buy"
    slip, fee = cfg.SLIPPAGE, cfg.FEE_TAKER

    label = np.zeros(n, dtype=np.int8)
    ret_net = np.full(n, np.nan)
    bars_held = np.zeros(n, dtype=np.int32)
    resolved = np.zeros(n, dtype=bool)

    for i in range(n - 1):
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue

        # Vao lenh tai gia mo cua nen ke tiep, slippage luon lam gia te di
        raw = open_[i + 1]
        entry = raw * (1.0 + slip) if la_mua else raw * (1.0 - slip)
        if entry <= 0:
            continue

        if la_mua:
            stop, tp = entry - cfg.ATR_STOP_MULT * a, entry + cfg.ATR_TP_MULT * a
        else:
            stop, tp = entry + cfg.ATR_STOP_MULT * a, entry - cfg.ATR_TP_MULT * a

        het = min(n - 1, i + max_horizon)
        cham = 0
        gia_thoat = np.nan
        for j in range(i + 1, het + 1):
            if la_mua:
                hit_sl, hit_tp = low[j] <= stop, high[j] >= tp
            else:
                hit_sl, hit_tp = high[j] >= stop, low[j] <= tp
            # Cham ca hai trong mot nen -> tinh STOP (giong engine.py)
            if hit_sl:
                cham, gia_thoat = SL_TRUOC, stop
            elif hit_tp:
                cham, gia_thoat = TP_TRUOC, tp
            if cham:
                bars_held[i] = j - i
                break
        else:
            j = het

        if not cham:
            bars_held[i] = max(1, het - i)
            gia_thoat = df["close"].to_numpy(dtype=float)[het]

        fill = gia_thoat * (1.0 - slip) if la_mua else gia_thoat * (1.0 + slip)
        gross = (fill - entry) / entry if la_mua else (entry - fill) / entry
        label[i] = cham
        resolved[i] = bool(cham)
        ret_net[i] = gross - 2.0 * fee

    return pd.DataFrame({
        "label": label, "ret_net": ret_net,
        "bars_held": bars_held, "resolved": resolved,
    }, index=df.index)


def gan_nhan_hai_chieu(df: pd.DataFrame, cfg=config, max_horizon: int = 60) -> pd.DataFrame:
    """Nhan cho ca hai huong.

    Hai chieu KHONG doi xung: voi stop 2xATR va TP 3xATR, lenh mua va lenh ban
    co barrier dat o cac muc gia khac nhau, nen phai tinh rieng tung chieu.

    `edge` = ret_net cua chieu mua tru chieu ban, la muc tieu lien tuc cho
    policy xep hang: duong nghia la thoi diem nay nghieng ve mua.
    """
    mua = triple_barrier(df, "Buy", cfg, max_horizon)
    ban = triple_barrier(df, "Sell", cfg, max_horizon)
    return pd.DataFrame({
        "label_long": mua["label"], "ret_long": mua["ret_net"],
        "label_short": ban["label"], "ret_short": ban["ret_net"],
        "bars_held": np.maximum(mua["bars_held"], ban["bars_held"]),
        "resolved": mua["resolved"] & ban["resolved"],
        "edge": mua["ret_net"] - ban["ret_net"],
    }, index=df.index)
