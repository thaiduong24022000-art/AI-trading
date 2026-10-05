"""
Huan luyen bo loc meta-label + do xem no co that su lam ra tien khong.

MOC SO SANH O DAY KHONG PHAI AUC 0.5, MA LA "NGHE HET MOI TIN HIEU".
Do la khac biet quan trong nhat giua file nay va `policy_train.py`. Mot bo loc
co AUC 0.58 nghe nhu co ky nang, nhung neu sau khi loc no van lo it hon viec
khong loc gi thi no vo dung - va con te hon vo dung, vi no lam ta tuong minh
dang duoc bao ve. Vi vay moi chi so o day deu duoc bao cao KEM ban doi chung
"khong loc": ky vong, profit factor, ty le thang.

BA CACH MOT BO LOC CO THE TU LUA, VA CHO CHAN CHUNG:

  1. Loc gan het.   Giu lai 3% tin hieu tot nhat thi ky vong dep la duong nhien
                    - do la chon 3 lenh may man trong 100, khong phai ky nang.
                    Cong doi ty le giu nam trong khoang hop ly.
  2. Loc gan khong. Giu 98% thi ky vong gan y het khong loc; bo loc chi dang
                    lam nen. Cong doi phai HON ban khong loc mot bien du lon.
  3. Ro ri.         Nhan xao tron van cho AUC cao. Cung phep doi chung nhu ben
                    AI policy, va no cung dung lam dieu kien chan dau tien.

NGUONG QUYET DINH KHONG DAT TAY. No la xac suat hoa von tinh tu bien do thang/
thua THUC do tren khoi hieu chuan, cong mot bien an toan. Nho vay khi phi doi,
khi barrier doi, hay khi thi truong doi bien do, nguong tu dich theo - thay vi
tro thanh mot con so ma nua nam sau khong ai nho vi sao lai la 0.55.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import config
from . import meta_label
from . import validation as val_mod

logger = logging.getLogger(__name__)

# Nho hon ca mo hinh cua AI policy: bo meta chi co vai nghin dong thay vi vai
# tram nghin, nen so bac tu do phai giam theo. num_leaves 7 = toi da 7 vung
# quyet dinh; nhieu hon nua tren 4.000 mau la hoc thuoc long.
THAM_SO_LGB = {
    "objective": "binary",
    "metric": "auc",
    "learning_rate": 0.03,
    "num_leaves": 7,
    "max_depth": 3,
    "min_child_samples": 80,
    "feature_fraction": 0.6,
    "bagging_fraction": 0.7,
    "bagging_freq": 1,
    "lambda_l2": 10.0,
    "verbosity": -1,
    "num_threads": 0,
}
# So vong mac dinh khi khong co gi de chot tu K-fold.
SO_VONG_MAC_DINH = 120


@dataclass
class KetQuaMeta:
    booster: object = None
    chi_so: Dict[str, float] = field(default_factory=dict)
    chi_so_xao: Dict[str, float] = field(default_factory=dict)
    bien_do: Dict[str, float] = field(default_factory=dict)
    so_dong: Dict[str, int] = field(default_factory=dict)
    nguong: float = 0.5
    cach_chon_nguong: Dict = field(default_factory=dict)
    chi_so_ngoai_mau: Dict = field(default_factory=dict)
    loi: List[str] = field(default_factory=list)

    @property
    def thanh_cong(self) -> bool:
        return self.booster is not None and not self.loi


def _sach(df: pd.DataFrame, cot: List[str]) -> pd.DataFrame:
    return df.dropna(subset=cot + ["y", "ret"])


def _huan_luyen_co_nhan(tr: pd.DataFrame, y: np.ndarray, cot: List[str],
                        w: np.ndarray, seed: int, so_vong: int = None):
    """Huan luyen mot booster voi so vong CO DINH, khong dung early stopping.

    Khong dung early stopping co chu dich: no doi mot tap kiem dinh, va moi tap
    kiem dinh o day deu la mot doan thi truong lien mach - dung no de chon so
    vong nghia la chon theo mot che do duy nhat. So vong duoc chot tu trung vi
    cua cac fold thay vao do, xem `huan_luyen()`.
    """
    import lightgbm as lgb

    tham_so = dict(THAM_SO_LGB)
    tham_so["seed"] = seed
    # Chuan hoa trong so ve trung binh 1.0 - xem validation.chuan_hoa_trong_so().
    # Khong lam buoc nay thi lambda_l2 manh len gap nghich dao do duy nhat.
    bo_tr = lgb.Dataset(tr[cot].to_numpy(dtype=float), label=y,
                        weight=val_mod.chuan_hoa_trong_so(w),
                        feature_name=list(cot), free_raw_data=False)
    return lgb.train(tham_so, bo_tr,
                     num_boost_round=int(so_vong or SO_VONG_MAC_DINH),
                     callbacks=[lgb.log_evaluation(0)])


def nguong_hoa_von(bien_do: Dict[str, float], cfg=config) -> float:
    """Nguong ly thuyet: xac suat hoa von + bien an toan.

    Dung lam DUONG LUI khi khong quet duoc nguong tot hon tren du lieu.
    """
    bien = getattr(cfg, "META_BIEN_AN_TOAN", 0.01)
    return float(min(0.95, bien_do["p_hoa_von"] + bien))


def chon_nguong(p: np.ndarray, ret: np.ndarray, bien_do: Dict[str, float],
                cfg=config) -> Tuple[float, Dict]:
    """Quet nguong tren khoi HIEU CHUAN, chon cai cho TONG loi nhuan cao nhat.

    VI SAO TOI DA HOA TONG CHU KHONG PHAI KY VONG MOI LENH: hai muc tieu nay
    keo ve hai huong nguoc nhau, va chi mot cai la thu ta thuc su muon.
    Giu 5% tin hieu voi ky vong 1.78% moi lenh nghe dep hon giu 40% voi ky vong
    0.40%, nhung tren 1.000 co hoi thi cai dau lam ra 0.089% con cai sau lam ra
    0.160% - gan gap doi. Toi da hoa ky vong moi lenh luon day nguong len cao
    nhat co the, tuc luon chon vai lenh may man nhat, va do la mot dang overfit
    doi lot ky luat.

    HAI RANG BUOC:
      - Tap giu lai phai THUC SU CO LAI tren khoi hieu chuan (tong > 0). Do la
        phep kiem khong phu thuoc vao viec mo hinh hieu chinh xac suat tot hay
        khong: LightGBM bi phat nang (nhu o day) se cho ra p co cum quanh ty le
        co so, va mot nguong suy tu p se loc qua tay ma khong ai biet. Doi tren
        KET QUA THUC thi khong dinh phai van de do.

        Chu y: dieu kien la TONG DUONG, khong phai "ty le thang >= hoa von".
        Hai cai nghe giong nhau nhung khac han: hoa von duoc tinh tren bien do
        thang/thua cua TOAN BO tin hieu, con tap giu lai co bien do rieng cua no
        - neu bo loc giu duoc nhung lenh thang dam hon thi no can it lan thang
        hon de co lai. Ap nguong hoa von cua tap lon len tap con la tron thong
        ke cua hai tap khac nhau, va no loai oan dung nhung bo loc lam duoc viec.
      - Ty le giu lai phai nam trong DUNG khoang ma cong thang cap chap nhan.
        Rang buoc nay khong phai de cho dep: neu bo chon nguong duoc tu do chon
        mot nguong giu 4% trong khi cong doi 15-90%, thi no dang toi uu ngoai
        vung kha thi - lan nao cung sinh ra mot bo loc ma cong chac chan tu choi,
        va khong ai doc ra duoc rang hai lop dang bat dong voi nhau.

    Quet tren du doan NGOAI MAU chu khong phai tren khoi kiem dinh: day la mot
    tham so duoc CHON tu du lieu, nen no phai chon o noi khong dung de cham diem.
    Chon mot so vo huong tu ~39 ung vien la mot bac tu do - it, nhung khong phai
    khong co, va vung train ton tai chinh de tra gia cho no.
    """
    p = np.asarray(p, dtype=float)
    ret = np.asarray(ret, dtype=float)
    lui = nguong_hoa_von(bien_do, cfg)
    # Cung khoang ma cong thang cap doi - hai lop phai dong y ve vung kha thi.
    giu_min = getattr(cfg, "GATE_META_TY_LE_GIU_MIN", 0.15)
    giu_max = getattr(cfg, "GATE_META_TY_LE_GIU_MAX", 0.90)
    n_toi_thieu = max(20, int(len(p) * giu_min))
    n_toi_da = int(len(p) * giu_max)

    ung_vien = np.unique(np.quantile(p, np.linspace(0.0, 0.95, 39)))
    tot_nhat, diem_tot_nhat = None, 0.0     # 0.0 = phai co lai that su moi duoc chon
    quet = []

    for thr in ung_vien:
        giu = p >= thr
        n = int(giu.sum())
        if n < n_toi_thieu or n > n_toi_da:
            continue
        r = ret[giu]
        tong = float(r.sum())
        quet.append({"nguong": float(thr), "n": n, "tong": tong,
                     "ty_le_thang": float((r > 0).mean()), "ky_vong": float(r.mean())})
        if tong > diem_tot_nhat:
            diem_tot_nhat, tot_nhat = tong, float(thr)

    if tot_nhat is None:
        logger.info("Khong nguong nao vua rang buoc tren khoi hieu chuan - "
                    "dung nguong hoa von ly thuyet %.4f", lui)
        return lui, {"cach_chon": "hoa_von_ly_thuyet", "quet": quet}

    return tot_nhat, {"cach_chon": "toi_da_tong_loi_nhuan", "quet": quet,
                      "nguong_hoa_von_ly_thuyet": lui}


def du_doan_ngoai_mau(bo: pd.DataFrame, cot: List[str], train_lo: int, train_hi: int,
                      embargo: int, so_moc: int, seed: int = 0,
                      so_fold: int = 5, xao_nhan: bool = False) -> Tuple[np.ndarray, List[int]]:
    """Purged K-fold tren vung train -> du doan NGOAI MAU cho tung tin hieu.

    VI SAO KHONG DUNG MOT KHOI HIEU CHUAN LIEN MACH. Da thu, va no hong theo
    mot cach rat de tin nham. Voi mat do tin hieu thap (8.304 tin hieu tren
    11.330 nen), mot khoi 500 nen chi chua ~370 tin hieu, va ca 370 cai do den
    tu MOT doan thi truong lien tuc. Lan chay dau tien roi dung vao mot doan
    83 ngay ma breakout thang 21% thay vi 43% - khong nguong nao lai duoc o do,
    vi khong co gi dang giu. Ngưong, so vong boosting va bien do thang/thua deu
    duoc rut ra tu chinh doan do, tuc ca ba deu mo ta mot che do duy nhat.

    K-fold co purge cho ra du doan ngoai mau tren TOAN BO lich su train: hang
    nghin tin hieu, tri khap moi che do. Moi fold la mot doan lien mach theo
    thoi gian (khong xao tron ngau nhien - lam vay se cho mo hinh nhin thay
    tuong lai cua chinh no), va vung train cua tung fold bi purge + embargo
    khoi doan test cua fold do.

    Tra ve (p_ngoai_mau, cac_so_vong). `p` la NaN o nhung dong khong fold nao
    du du lieu de du doan.
    """
    trong_train = (bo["_i"] >= train_lo) & (bo["_i"] < train_hi)
    idx_train = np.flatnonzero(trong_train.to_numpy())
    p_oos = np.full(len(bo), np.nan)
    so_vong: List[int] = []
    if len(idx_train) == 0:
        return p_oos, so_vong

    vi_tri = bo["_i"].to_numpy()
    span = bo["bars_held"].fillna(0).to_numpy().astype("int64")
    y_goc = bo["y"].to_numpy().copy()
    if xao_nhan:
        y_goc = np.random.default_rng(seed + 99).permutation(y_goc)

    bien = np.linspace(train_lo, train_hi, so_fold + 1).astype(int)
    for k in range(so_fold):
        lo, hi = bien[k], bien[k + 1]
        mat_na_test = trong_train.to_numpy() & (vi_tri >= lo) & (vi_tri < hi)
        # Purge: bo mau co nhan cham vao fold test. Embargo: bo them mot khoang
        # sau fold test de tuong quan chuoi khong lot qua.
        truoc = (vi_tri + span) < lo
        sau = vi_tri >= hi + embargo
        mat_na_tr = trong_train.to_numpy() & (truoc | sau)
        if mat_na_test.sum() < 20 or mat_na_tr.sum() < 200:
            continue

        tr_k = bo[mat_na_tr]
        te_k = bo[mat_na_test]
        y_tr = y_goc[mat_na_tr]
        if len(np.unique(y_tr)) < 2:
            continue

        b = _huan_luyen_co_nhan(tr_k, y_tr, cot,
                                val_mod.trong_so_duy_nhat_panel(tr_k, so_moc),
                                seed + k)
        p_oos[mat_na_test] = b.predict(te_k[cot].to_numpy(dtype=float))
        so_vong.append(int(b.num_trees()))

    return p_oos, so_vong


def mo_phong_loc(p: np.ndarray, te: pd.DataFrame, nguong: float,
                 bien_do: Dict[str, float]) -> Dict[str, float]:
    """Cho bo loc chay tren khoi kiem dinh va so voi viec khong loc gi.

    Day la con so quyet dinh. Moi chi so deu di kem ban `_khong_loc` de khong
    bao gio doc mot minh: mot bo loc chi co gia tri neu no HON viec nghe het.
    """
    r = te["ret"].to_numpy(dtype=float)
    giu = p >= nguong
    r_giu = r[giu]

    def _tom(v: np.ndarray) -> Dict[str, float]:
        if len(v) == 0:
            return {"n": 0, "ky_vong": 0.0, "ty_le_thang": 0.0,
                    "profit_factor": 0.0, "tong": 0.0}
        thang, thua = v[v > 0], v[v <= 0]
        tong_thua = -thua.sum()
        return {
            "n": int(len(v)),
            "ky_vong": float(v.mean()),
            "ty_le_thang": float(len(thang) / len(v)),
            "profit_factor": float(thang.sum() / tong_thua) if tong_thua > 0 else float("inf"),
            "tong": float(v.sum()),
        }

    co_loc, khong_loc = _tom(r_giu), _tom(r)
    return {
        "so_lenh_giu": co_loc["n"],
        "so_lenh_goc": khong_loc["n"],
        "ty_le_giu": float(giu.mean()) if len(giu) else 0.0,
        "ky_vong": co_loc["ky_vong"],
        "ky_vong_khong_loc": khong_loc["ky_vong"],
        "cai_thien": co_loc["ky_vong"] - khong_loc["ky_vong"],
        "ty_le_thang": co_loc["ty_le_thang"],
        "ty_le_thang_khong_loc": khong_loc["ty_le_thang"],
        "profit_factor": co_loc["profit_factor"],
        "profit_factor_khong_loc": khong_loc["profit_factor"],
        "tong_loi_nhuan": co_loc["tong"],
        "tong_khong_loc": khong_loc["tong"],
        "nguong": float(nguong),
        "p_hoa_von": bien_do["p_hoa_von"],
    }


def danh_gia(booster, te: pd.DataFrame, cot: List[str], nguong: float,
             bien_do: Dict[str, float], w: np.ndarray = None) -> Dict[str, float]:
    from sklearn.metrics import roc_auc_score

    p = booster.predict(te[cot].to_numpy(dtype=float))
    ra: Dict[str, float] = {}
    y = te["y"].to_numpy()
    ra["auc"] = (float(roc_auc_score(y, p, sample_weight=w))
                 if len(np.unique(y)) > 1 else float("nan"))
    ra["p_min"] = float(p.min())
    ra["p_max"] = float(p.max())
    ra["p_tb"] = float(p.mean())
    ra.update(mo_phong_loc(p, te, nguong, bien_do))
    return ra


def huan_luyen(bo: pd.DataFrame, cot: List[str], khoi: val_mod.KhoiChia,
               cfg=config, seed: int = 0, kiem_tra_xao: bool = True,
               so_moc: int = None, so_fold: int = 5) -> KetQuaMeta:
    """Huan luyen bo loc tren tin hieu cua chien luoc luat.

    HAI KHOI, KHONG PHAI BA. Vung train tu hieu chuan chinh no bang purged
    K-fold (xem `du_doan_ngoai_mau`), nen khong can cat rieng mot khoi hieu
    chuan lien mach - va do la dieu tot, vi mot khoi lien mach o mat do tin
    hieu nay chi dai dien cho mot che do thi truong.

    `so_moc` la tong so NEN cua lich su day du, khong phai so tin hieu. Purge va
    embargo dem theo don vi do; truyen nham so tin hieu se lam embargo ngan di
    khoang 25 lan ma khong co gi bao loi.
    """
    kq = KetQuaMeta()
    so_moc = so_moc or bo.attrs.get("so_moc") or int(bo["_i"].max()) + 1
    embargo = khoi.test_lo - khoi.train_hi

    tr = _sach(val_mod.lay_train(bo, khoi), cot)
    te = _sach(val_mod.lay_test(bo, khoi), cot)
    kq.so_dong = {"train": len(tr), "val": len(te), "tong_tin_hieu": len(bo)}

    loi = val_mod.kiem_tra_khong_ro_ri(tr, te, khoi)
    if loi:
        kq.loi += loi
        logger.error("Phep chia KHONG dat: %s", "; ".join(loi))
        return kq

    toi_thieu = getattr(cfg, "GATE_META_MIN_MAU_TRAIN", 600)
    if len(tr) < toi_thieu or len(te) < 60:
        kq.loi.append("khong du tin hieu: train=%d (can >= %d), val=%d"
                      % (len(tr), toi_thieu, len(te)))
        return kq

    w_tr = val_mod.trong_so_duy_nhat_panel(tr, so_moc)
    w_te = val_mod.trong_so_duy_nhat_panel(te, so_moc)
    kq.so_dong["train_hieu_dung"] = int(round(w_tr.sum()))
    kq.so_dong["val_hieu_dung"] = int(round(w_te.sum()))

    # --- 1. Du doan ngoai mau tren toan vung train (purged K-fold) ---
    t0 = time.time()
    tr = tr.reset_index(drop=True)
    p_oos, cac_vong = du_doan_ngoai_mau(tr, cot, khoi.train_lo, khoi.train_hi,
                                        embargo, so_moc, seed, so_fold)
    co = np.isfinite(p_oos)
    kq.so_dong["ngoai_mau"] = int(co.sum())
    if co.sum() < 200:
        kq.loi.append("K-fold chi cho %d du doan ngoai mau - khong du de chon nguong"
                      % int(co.sum()))
        return kq

    # --- 2. Nguong + bien do, ca hai deu tu du doan NGOAI MAU ---
    kq.bien_do = meta_label.bien_do_thuc(tr[co])
    kq.nguong, kq.cach_chon_nguong = chon_nguong(
        p_oos[co], tr["ret"].to_numpy(dtype=float)[co], kq.bien_do, cfg)
    kq.chi_so_ngoai_mau = mo_phong_loc(p_oos[co], tr[co], kq.nguong, kq.bien_do)
    logger.info("K-fold: %d du doan ngoai mau tu %d fold | nguong %.4f (%s)",
                int(co.sum()), len(cac_vong), kq.nguong,
                kq.cach_chon_nguong.get("cach_chon"))

    # --- 3. Mo hinh cuoi cung tren toan vung train ---
    so_vong = int(np.median(cac_vong)) if cac_vong else SO_VONG_MAC_DINH
    kq.booster = _huan_luyen_co_nhan(tr, tr["y"].to_numpy(), cot, w_tr, seed, so_vong)
    logger.info("Huan luyen bo loc xong trong %.1fs (%d vong)",
                time.time() - t0, so_vong)

    kq.chi_so = danh_gia(kq.booster, te, cot, kq.nguong, kq.bien_do, w_te)

    if kiem_tra_xao:
        kq.chi_so_xao = _doi_chung_xao(tr, te, cot, kq.nguong, kq.bien_do,
                                       w_tr, w_te, seed, so_vong)
    return kq


def _doi_chung_xao(tr, te, cot, nguong, bien_do, w_tr, w_te, seed, so_vong):
    """Huan luyen lai tren nhan da xao tron - ket qua PHAI vo dung.

    Xao tron pha lien ket dac trung-nhan nhung giu nguyen moi thu khac: cung so
    dong, cung phan bo dac trung, cung phep chia, cung trong so, cung so vong.
    Neu AUC van cao thi cai cao do den tu cau truc cua duong ong chu khong tu
    thi truong.
    """
    rng = np.random.default_rng(seed + 99)
    y_xao = rng.permutation(tr["y"].to_numpy())
    b = _huan_luyen_co_nhan(tr, y_xao, cot, w_tr, seed, so_vong)
    return danh_gia(b, te, cot, nguong, bien_do, w_te)


def tam_quan_trong(booster, cot: List[str], top: int = 12) -> List[Tuple[str, float]]:
    gt = booster.feature_importance(importance_type="gain")
    tong = float(gt.sum()) or 1.0
    return [(c, float(v)) for c, v in
            sorted(zip(cot, gt / tong), key=lambda x: -x[1])[:top]]
