"""
Meta-label: day khong phai "nen nao dang mua", ma "tin hieu nay co dang nghe khong".

VI SAO DOI CAU HOI. Ban policy dau tien hoi mo hinh mot cau qua kho: trong moi
cay nen cua moi ma, cai nao dang vao lenh? Do la mot cau hoi ma ty le co so da
nam DUOI hang rao chi phi, nen mo hinh phai tu minh sinh ra toan bo loi the.
No khong lam duoc: du doan tu tin nhat cua no dat 0.4195 trong khi hoa von doi
0.432, nen tren 15.096 nen kiem dinh no vao dung 0 lenh.

Do tren cung du lieu mainnet 4H, 12 ma, 4.5 nam:

    moi nen                 : 126.873 mau, ty le lai sau phi 39.53%
    nen breakout da phat    :   4.979 mau, ty le lai sau phi 42.86%

Chi rieng viec DUNG YEN cho den khi mot chien luoc luat len tieng da keo ty le
co so len 3.3 diem phan tram. Bai toan con lai nho hon han: khong phai tu sinh
ra loi the, ma chi phai tach nhung tin hieu te ra khoi nhung tin hieu on.

HOA VON THUC LA 43.5%, KHONG PHAI 40%. Cong thuc barrier noi TP 3xATR / SL
2xATR nen chi can thang 40% la hoa. Nhung lenh khong phai luc nao cung cham
barrier - nhieu lenh het han giua chung - nen bien do THUC do duoc la thang
+6.95% / thua -5.35%, ty le 1.30 chu khong phai 1.50. Hoa von thuc:

    p = |thua| / (thang + |thua|) = 0.0535 / (0.0695 + 0.0535) = 0.4350

Breakout tho dat 42.86% => ky vong -0.00080 moi tin hieu. Viec cua bo loc nay
la keo 42.86% len qua 43.5%. Do la 0.64 diem phan tram - kha thi - chu khong
phai 3.7 diem nhu ban policy cu phai gong.

DIEM DE SAI NHAT TRONG FILE NAY: vi tri nen. Purge va embargo dem theo NEN cua
lich su day du, khong theo so thu tu cua cac tin hieu. Tin hieu breakout thua
thot (4.979 tren 126.873 nen, khoang 4%), nen neu danh so 0,1,2... tren rieng
cac tin hieu thi "embargo 60" se thanh embargo 60 TIN HIEU - tuc khoang 1.500
nen that. Vi vay `_i` luon duoc gan tren panel DAY DU roi moi loc xuong.
"""
import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import config
from . import features, indicators
from . import regime as regime_mod
from . import validation as val_mod
from .strategies.base import BUY, SELL, Strategy

logger = logging.getLogger(__name__)

# Dac trung rieng cua lop meta - mo ta CHINH TIN HIEU, khong phai thi truong.
# Giu it co chu dich: bo dac trung thi truong da co san 33 cot, va moi cot them
# vao mot mau 5.000 dong la mot bac tu do nua de khop nham voi qua khu.
COT_TIN_HIEU: List[str] = [
    "la_mua",          # huong luat de xuat (1 = mua)
    "suc_manh_luat",   # do tu tin cua chinh chien luoc
    "regime_trend",    # bo canh luc phat tin hieu
    "regime_range",
    "regime_bien_dong",
]


def cot_dac_trung_meta(co_xep_hang: bool = True, co_phai_sinh: bool = False) -> List[str]:
    """Dac trung thi truong (dung chung voi AI policy) + dac trung cua tin hieu."""
    return features.cot_dac_trung(co_xep_hang, co_phai_sinh) + COT_TIN_HIEU


def _ma_regime(ten: str) -> Dict[str, float]:
    return {
        "regime_trend": 1.0 if ten == regime_mod.TREND else 0.0,
        "regime_range": 1.0 if ten == regime_mod.RANGE else 0.0,
        "regime_bien_dong": 1.0 if ten == regime_mod.HIGH_VOL else 0.0,
    }


def tin_hieu_cua_mot_ma(df: pd.DataFrame, chien_luoc: Strategy, symbol: str,
                        cfg=config, chua_du_nen: int = None) -> pd.DataFrame:
    """Chay chien luoc luat qua toan bo lich su, ghi lai moi lan no len tieng.

    Dung dung `prepare()` + `generate_at()` ma bot that dung, khong viet lai
    dieu kien. Neu viet lai thi mo hinh se hoc loc mot chien luoc HOI GIONG
    cai dang chay - va sai lech do khong lo ra o bat ky test nao.
    """
    warmup = chua_du_nen or indicators.warmup_bars()
    d = chien_luoc.prepare(df)
    ra = []
    for i in range(warmup, len(d)):
        sig = chien_luoc.generate_at(d, i)
        if sig.action not in (BUY, SELL):
            continue
        reg = regime_mod.classify_at(d, i, cfg)
        hang = {
            "timestamp": int(d["timestamp"].iloc[i]),
            "symbol": symbol,
            "chien_luoc": chien_luoc.name,
            "huong": sig.action,
            "la_mua": 1.0 if sig.action == BUY else 0.0,
            "suc_manh_luat": float(sig.strength),
            "regime": reg.regime,
        }
        hang.update(_ma_regime(reg.regime))
        ra.append(hang)
    return pd.DataFrame(ra)


def xay_bo_meta(frames: Dict[str, pd.DataFrame], chien_luocs: List[Strategy],
                cfg=config, max_horizon: int = 60,
                derivs: Dict[str, pd.DataFrame] = None) -> pd.DataFrame:
    """Bo du lieu huan luyen bo loc: mot dong = mot lan chien luoc luat len tieng.

    Tra ve DataFrame co:
      - toan bo dac trung thi truong (ke ca xep hang cat ngang) tai nen do
      - dac trung cua tin hieu (huong, do tu tin, regime)
      - `y`      : lenh nay co lai sau phi khong (1/0)
      - `ret`    : loi nhuan rong thuc te cua chieu ma luat de xuat
      - `_i`     : vi tri nen tren LICH SU DAY DU (de purge/embargo dung)
      - `bars_held`, `timestamp`, `symbol`, `chien_luoc`
    """
    panel = features.xay_panel(frames, cfg, max_horizon=max_horizon,
                              gan_nhan=True, derivs=derivs)
    panel = val_mod.them_vi_tri(panel)      # `_i` theo nen, tren toan bo lich su
    so_moc = int(panel["_i"].max()) + 1

    phan = []
    for sym, df in frames.items():
        d = indicators.add_indicators(df) if "atr" not in df.columns else df
        for st in chien_luocs:
            th = tin_hieu_cua_mot_ma(d, st, sym, cfg)
            if not th.empty:
                phan.append(th)

    if not phan:
        logger.warning("Khong chien luoc nao phat tin hieu tren du lieu nay")
        return pd.DataFrame()

    tin_hieu = pd.concat(phan, ignore_index=True)
    tin_hieu["timestamp"] = tin_hieu["timestamp"].astype("int64")

    bo = tin_hieu.merge(panel, on=["timestamp", "symbol"], how="inner",
                        suffixes=("", "_panel"))

    # Ket qua THUC cua dung chieu ma luat de xuat. Lay nham chieu o day la mot
    # loi im lang hoan hao: mo hinh van huan luyen duoc, van ra AUC dep, va no
    # hoc chinh xac dieu nguoc lai voi cai ta can.
    la_mua = bo["la_mua"].to_numpy() > 0.5
    bo["ret"] = np.where(la_mua, bo["ret_long"].to_numpy(), bo["ret_short"].to_numpy())
    bo = bo[np.isfinite(bo["ret"])].copy()
    bo["y"] = (bo["ret"] > 0).astype(np.int8)

    bo = bo.sort_values(["_i", "symbol"]).reset_index(drop=True)
    bo.attrs["so_moc"] = so_moc
    logger.info("Bo meta: %d tin hieu tu %d ma | ty le lai co so %.4f | %d moc nen",
                len(bo), bo["symbol"].nunique(), bo["y"].mean(), so_moc)
    return bo


def bien_do_thuc(bo: pd.DataFrame) -> Dict[str, float]:
    """Bien do thang/thua THUC va nguong hoa von suy ra tu no.

    Khong dung ty le barrier (TP/SL) de tinh hoa von: lenh het han giua chung
    khong cham barrier nao, nen ty le thuc luon thap hon ty le danh nghia. Lay
    so danh nghia se cho ra mot nguong de hon thuc te, va bo loc se de lot dung
    nhung tin hieu vua du xau de lam mat tien.
    """
    r = bo["ret"].to_numpy()
    thang, thua = r[r > 0], r[r <= 0]
    lai = float(thang.mean()) if len(thang) else 0.0
    lo = float(thua.mean()) if len(thua) else 0.0
    tong = lai - lo
    return {
        "lai": lai,
        "lo": lo,
        "p_hoa_von": (-lo / tong) if tong > 0 else 1.0,
        "ty_le_lai_co_so": float((r > 0).mean()) if len(r) else 0.0,
        "ky_vong_khong_loc": float(r.mean()) if len(r) else 0.0,
    }


def ky_vong(p: np.ndarray, bien_do: Dict[str, float]) -> np.ndarray:
    """Ky vong loi nhuan rong cua mot tin hieu, tu xac suat thang du doan."""
    return p * bien_do["lai"] + (1.0 - p) * bien_do["lo"]
