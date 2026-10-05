"""
Huan luyen policy bang LightGBM + do chat luong mot cach khong tu lua.

BA QUYET DINH THIET KE DANG CHU Y:

1. HAI MO HINH NHI PHAN, KHONG PHAI MOT MO HINH BA LOP.
   "Nen mua / nen ban / nen dung yen" nghe tu nhien nhung sai ve mat thong ke:
   HOLD khong phai mot trang thai cua thi truong, no la ket qua cua viec CA HAI
   lenh deu khong dang. Mo hinh hoa no thanh mot lop rieng buoc mo hinh phai hoc
   chinh nguong quyet dinh cua ta - va nguong do doi moi khi phi thay doi.
   Hai cau hoi "lenh mua o day co lai khong" va "lenh ban o day co lai khong"
   la hai cau doc lap, deu co nhan khach quan, va HOLD sinh ra tu ca hai.

2. MUC TIEU LA `ret_net > 0`, KHONG PHAI HUONG GIA.
   `ret_net` da tru phi taker va slippage ca hai chieu. Du bao huong gia dung
   55% van thua tien neu bien do thang khong bu noi 0.3% chi phi moi vong.
   Du bao truc tiep "co lai sau phi khong" thi phi nam trong nhan, va mo hinh
   tu hoc rang cac tin hieu yeu khong dang vao lenh.

3. MO HINH NHO CO CHU DICH (num_leaves 15, depth 4, min_child_samples 300).
   Voi 200.000 dong va IC do duoc ~0, mot mo hinh lon se tim ra cau truc trong
   nhieu va bao cao AUC dep tren train. Rang buoc kich thuoc la cach re nhat de
   phan biet "khong co tin hieu" voi "co tin hieu nhung mo hinh chua du to".

CANH BAO DOC SO: AUC tren du lieu tai chinh cao hon ~0.75 gan nhu luon la RO RI
chu khong phai ky nang. Cong thang cap chan ca hai dau vi ly do do.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import config
from . import validation as val_mod
from .strategies.base import BUY, HOLD, SELL

logger = logging.getLogger(__name__)

THAM_SO_LGB = {
    "objective": "binary",
    "metric": "auc",
    "learning_rate": 0.03,
    "num_leaves": 15,
    "max_depth": 4,
    "min_child_samples": 300,
    "feature_fraction": 0.7,
    "bagging_fraction": 0.7,
    "bagging_freq": 1,
    "lambda_l2": 5.0,
    "verbosity": -1,
    "num_threads": 0,
}
SO_VONG_TOI_DA = 400
DUNG_SOM = 40


@dataclass
class KetQuaHuanLuyen:
    booster_long: object = None
    booster_short: object = None
    chi_so: Dict[str, float] = field(default_factory=dict)
    chi_so_xao: Dict[str, float] = field(default_factory=dict)
    bien_do: Dict[str, float] = field(default_factory=dict)
    so_dong: Dict[str, int] = field(default_factory=dict)
    loi: List[str] = field(default_factory=list)

    @property
    def thanh_cong(self) -> bool:
        return self.booster_long is not None and not self.loi


def them_muc_tieu(panel: pd.DataFrame) -> pd.DataFrame:
    """y_long / y_short = lenh theo chieu do co LAI SAU PHI khong."""
    out = panel.copy()
    out["y_long"] = (out["ret_long"] > 0).astype(np.int8)
    out["y_short"] = (out["ret_short"] > 0).astype(np.int8)
    return out


def _bo_dong_thieu(df: pd.DataFrame, cot: List[str]) -> pd.DataFrame:
    return df.dropna(subset=cot + ["ret_long", "ret_short"])


def _huan_luyen_mot_ben(tr: pd.DataFrame, ca: pd.DataFrame, cot: List[str],
                        cot_y: str, w_tr: np.ndarray, w_ca: np.ndarray,
                        seed: int) -> object:
    import lightgbm as lgb

    tham_so = dict(THAM_SO_LGB)
    tham_so["seed"] = seed
    # Chuan hoa ve trung binh 1.0: giu ty le giua cac mau nhung khong lam doi
    # cuong do cua lambda_l2 / min_sum_hessian_in_leaf. Xem chuan_hoa_trong_so().
    w_tr = val_mod.chuan_hoa_trong_so(w_tr)
    w_ca = val_mod.chuan_hoa_trong_so(w_ca)
    bo_train = lgb.Dataset(tr[cot].to_numpy(dtype=float), label=tr[cot_y].to_numpy(),
                           weight=w_tr, feature_name=list(cot), free_raw_data=False)
    bo_calib = lgb.Dataset(ca[cot].to_numpy(dtype=float), label=ca[cot_y].to_numpy(),
                           weight=w_ca, reference=bo_train, free_raw_data=False)
    return lgb.train(
        tham_so, bo_train, num_boost_round=SO_VONG_TOI_DA,
        valid_sets=[bo_calib], valid_names=["calib"],
        callbacks=[lgb.early_stopping(DUNG_SOM, verbose=False), lgb.log_evaluation(0)],
    )


def bien_do_lai_lo(df: pd.DataFrame) -> Dict[str, float]:
    """Lai/lo trung binh moi lenh, do tren khoi HIEU CHUAN.

    Day la hai so bien xac suat thanh tien. Chung phai do o khoi hieu chuan, vi
    do tren train se lac quan va do tren kiem dinh se lam hong chinh phep kiem
    dinh do.
    """
    ra = {}
    for ben, cot in (("long", "ret_long"), ("short", "ret_short")):
        v = df[cot].dropna().to_numpy()
        thang, thua = v[v > 0], v[v <= 0]
        ra["lai_%s" % ben] = float(thang.mean()) if len(thang) else 0.0
        ra["lo_%s" % ben] = float(thua.mean()) if len(thua) else 0.0
    return ra


def _ev(p: np.ndarray, lai: float, lo: float) -> np.ndarray:
    return p * lai + (1.0 - p) * lo


def mo_phong_quyet_dinh(p_long: np.ndarray, p_short: np.ndarray, df: pd.DataFrame,
                        bien_do: Dict[str, float], cfg=config) -> Dict[str, float]:
    """Chay lai dung logic quyet dinh cua policy tren mot khoi va do ket qua that.

    Day la con so co nghia kinh te duy nhat trong bo chi so: AUC 0.53 nghe on
    nhung neu quyet dinh sinh ra tu no van lo sau phi thi mo hinh vo dung.

    KHONG PHAI BACKTEST DANH MUC: khong co gioi han so vi the mo cung luc, khong
    co heat, khong co tuong quan giua cac ma. No do KY VONG MOI TIN HIEU, tuc
    chat luong cua nguon tin hieu. Backtest danh muc that van la viec cua
    backtest/engine.py sau khi mo hinh duoc thang cap.
    """
    ev_l = _ev(p_long, bien_do["lai_long"], bien_do["lo_long"])
    ev_s = _ev(p_short, bien_do["lai_short"], bien_do["lo_short"])
    nguong = getattr(cfg, "POLICY_EV_MIN", 0.001)

    mua = (ev_l > nguong) & (ev_s <= nguong)
    ban = (ev_s > nguong) & (ev_l <= nguong)
    loi_nhuan = np.where(mua, df["ret_long"].to_numpy(),
                         np.where(ban, df["ret_short"].to_numpy(), np.nan))
    vao_lenh = mua | ban
    r = loi_nhuan[vao_lenh]
    r = r[np.isfinite(r)]

    if len(r) == 0:
        return {"so_lenh": 0, "ty_le_vao_lenh": 0.0, "loi_nhuan_tb": 0.0,
                "ty_le_thang": 0.0, "profit_factor": 0.0, "tong_loi_nhuan": 0.0,
                "so_lenh_mua": 0, "so_lenh_ban": 0}

    thang, thua = r[r > 0], r[r <= 0]
    return {
        "so_lenh": int(len(r)),
        "ty_le_vao_lenh": float(vao_lenh.mean()),
        "loi_nhuan_tb": float(r.mean()),
        "ty_le_thang": float(len(thang) / len(r)),
        "profit_factor": float(thang.sum() / -thua.sum()) if len(thua) and thua.sum() < 0 else float("inf"),
        "tong_loi_nhuan": float(r.sum()),
        "so_lenh_mua": int(mua.sum()),
        "so_lenh_ban": int(ban.sum()),
    }


def danh_gia(booster_long, booster_short, te: pd.DataFrame, cot: List[str],
             bien_do: Dict[str, float], w: np.ndarray = None, cfg=config,
             max_horizon: int = 60) -> Dict[str, float]:
    """Bo chi so tren mot khoi mo hinh CHUA TUNG THAY."""
    from sklearn.metrics import roc_auc_score

    X = te[cot].to_numpy(dtype=float)
    p_long = booster_long.predict(X)
    p_short = booster_short.predict(X)

    ra: Dict[str, float] = {}
    for ben, p in (("long", p_long), ("short", p_short)):
        y = te["y_%s" % ben].to_numpy()
        if len(np.unique(y)) < 2:
            ra["auc_%s" % ben] = float("nan")
            continue
        ra["auc_%s" % ben] = float(roc_auc_score(y, p, sample_weight=w))

    # IC do tren CHENH LECH hai chieu: do la dai luong policy dung de xep hang,
    # va no phai duoc do cat ngang tai tung moc (xem validation.ic_theo_moc).
    du_doan = _ev(p_long, bien_do["lai_long"], bien_do["lo_long"]) - \
        _ev(p_short, bien_do["lai_short"], bien_do["lo_short"])
    thuc = (te["ret_long"] - te["ret_short"]).to_numpy()
    hop_le = np.isfinite(du_doan) & np.isfinite(thuc)
    chuoi_ic = val_mod.ic_theo_moc(du_doan[hop_le], thuc[hop_le],
                                   te["timestamp"].to_numpy()[hop_le],
                                   min_ma=getattr(cfg, "POLICY_MIN_MA", 8))
    ra["ic"] = float(np.mean(chuoi_ic)) if len(chuoi_ic) else float("nan")
    # `ic_t` la con so cong thang cap dung, va no PHAI la ban da hieu chinh tu
    # tuong quan: cac moc canh nhau dung chung toi max_horizon nen tuong lai nen
    # khong doc lap. Giu lai ban tho ben canh de nguoi doc thay chenh lech - do
    # chenh lech do chinh la muc do mot bao cao ngay tho se noi doi.
    ra["ic_t"] = val_mod.t_stat_newey_west(chuoi_ic, max_horizon)
    ra["ic_t_tho"] = val_mod.t_stat(chuoi_ic)
    ra["so_moc_ic"] = int(len(chuoi_ic))

    ra.update(mo_phong_quyet_dinh(p_long, p_short, te, bien_do, cfg))
    ra["auc_tb"] = float(np.nanmean([ra.get("auc_long", np.nan),
                                     ra.get("auc_short", np.nan)]))
    return ra


def huan_luyen(panel: pd.DataFrame, cot: List[str], ba_khoi: val_mod.BaKhoi,
               cfg=config, seed: int = 0, kiem_tra_xao: bool = True,
               max_horizon: int = 60) -> KetQuaHuanLuyen:
    """Huan luyen challenger + do tren khoi kiem dinh + chay doi chung ro ri.

    `kiem_tra_xao=True` huan luyen them mot mo hinh tren NHAN DA XAO TRON. Neu
    mo hinh do cung dat AUC cao thi pipeline dang ro ri o dau do va MOI so lieu
    con lai deu vo nghia. Day la phep thu duy nhat trong ca quy trinh co the
    chung minh rang bo do van con hoat dong.
    """
    kq = KetQuaHuanLuyen()
    panel = val_mod.them_vi_tri(panel)
    panel = them_muc_tieu(panel)
    so_moc = int(panel["_i"].max()) + 1

    khoi_calib, khoi_val = ba_khoi.khoi_calib(), ba_khoi.khoi_val()
    tr = _bo_dong_thieu(val_mod.lay_train(panel, khoi_calib), cot)
    ca = _bo_dong_thieu(val_mod.lay_test(panel, khoi_calib), cot)
    te = _bo_dong_thieu(val_mod.lay_test(panel, khoi_val), cot)
    kq.so_dong = {"train": len(tr), "calib": len(ca), "val": len(te)}

    # Soi DUNG hai tap sap di vao LightGBM, sau khi da dropna - khong phai soi
    # lai panel goc. Purge phai dung ca voi khoi calib va khoi val.
    for ten, khoi, tap_test in (("calib", khoi_calib, ca), ("val", khoi_val, te)):
        loi = val_mod.kiem_tra_khong_ro_ri(tr, tap_test, khoi)
        if loi:
            kq.loi += ["[%s] %s" % (ten, l) for l in loi]
    if kq.loi:
        logger.error("Phep chia du lieu KHONG dat: %s", "; ".join(kq.loi))
        return kq

    toi_thieu = getattr(cfg, "GATE_POLICY_MIN_MAU_TRAIN", 5000)
    if len(tr) < toi_thieu or len(ca) < 500 or len(te) < 500:
        kq.loi.append("khong du du lieu: train=%d (can >= %d), calib=%d, val=%d"
                      % (len(tr), toi_thieu, len(ca), len(te)))
        return kq

    # Trong so duy nhat: 60 mau chong lan nhau la ~1 quan sat, khong phai 60.
    w_tr = val_mod.trong_so_duy_nhat_panel(tr, so_moc)
    w_ca = val_mod.trong_so_duy_nhat_panel(ca, so_moc)
    w_te = val_mod.trong_so_duy_nhat_panel(te, so_moc)
    kq.so_dong["train_hieu_dung"] = int(round(w_tr.sum()))
    kq.so_dong["val_hieu_dung"] = int(round(w_te.sum()))

    t0 = time.time()
    kq.booster_long = _huan_luyen_mot_ben(tr, ca, cot, "y_long", w_tr, w_ca, seed)
    kq.booster_short = _huan_luyen_mot_ben(tr, ca, cot, "y_short", w_tr, w_ca, seed + 1)
    logger.info("Huan luyen xong trong %.1fs (long %d vong, short %d vong)",
                time.time() - t0, kq.booster_long.best_iteration,
                kq.booster_short.best_iteration)

    kq.bien_do = bien_do_lai_lo(ca)
    kq.chi_so = danh_gia(kq.booster_long, kq.booster_short, te, cot, kq.bien_do,
                         w_te, cfg, max_horizon)

    if kiem_tra_xao:
        kq.chi_so_xao = _doi_chung_xao(tr, ca, te, cot, kq.bien_do, w_tr, w_ca, w_te,
                                       seed, cfg, max_horizon)
    return kq


def _doi_chung_xao(tr, ca, te, cot, bien_do, w_tr, w_ca, w_te, seed, cfg,
                   max_horizon) -> Dict[str, float]:
    """Huan luyen lai tren nhan da xao tron. Ket qua PHAI la khong co ky nang.

    Xao tron pha lien ket dac trung-nhan nhung giu nguyen moi thu khac: cung so
    dong, cung phan bo dac trung, cung phep chia, cung trong so. Neu AUC van cao
    thi cai cao do den tu cau truc cua pipeline chu khong tu thi truong.
    """
    rng = np.random.default_rng(seed + 99)
    tr_x, ca_x = tr.copy(), ca.copy()
    for d in (tr_x, ca_x):
        for cot_y in ("y_long", "y_short"):
            d[cot_y] = rng.permutation(d[cot_y].to_numpy())

    bl = _huan_luyen_mot_ben(tr_x, ca_x, cot, "y_long", w_tr, w_ca, seed)
    bs = _huan_luyen_mot_ben(tr_x, ca_x, cot, "y_short", w_tr, w_ca, seed + 1)
    return danh_gia(bl, bs, te, cot, bien_do, w_te, cfg, max_horizon)


def tam_quan_trong(booster, cot: List[str], top: int = 12) -> List[Tuple[str, float]]:
    """Dac trung nao duoc dung nhieu nhat - de nguoi doc phat hien dieu vo ly.

    Vi du: neu `funding` bong nhien chiem 60% do quan trong trong khi IC cua no
    do duoc bang 0, do la dau hieu mo hinh dang bam vao mot dac diem ky thuat
    cua du lieu chu khong phai mot quan he kinh te.
    """
    gt = booster.feature_importance(importance_type="gain")
    tong = float(gt.sum()) or 1.0
    cap = sorted(zip(cot, gt / tong), key=lambda x: -x[1])
    return [(c, float(v)) for c, v in cap[:top]]
