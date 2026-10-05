"""
Vong hoc cho bo loc meta-label: huan luyen -> cong -> thang cap -> theo doi.

KHAC BIET DUY NHAT NHUNG QUAN TRONG SO VOI `continual.py`: moc so sanh.

Ben AI policy, cau hoi la "mo hinh co ky nang khong" va moc la ngau nhien
(AUC 0.5, IC 0). Ben nay cau hoi la "bo loc co lam ra tien hon viec khong loc
gi khong", va moc la CHINH CHIEN LUOC LUAT DANG CHAY. Mot bo loc AUC 0.60 ma
sau khi loc van lo hon breakout tho thi khong phai la tien bo - no la mot lop
phuc tap them vao ma khong doi lai duoc gi, va no con lam ta tuong minh dang
duoc bao ve.

Vi vay moi chi so trong cong deu doc theo cap: `ky_vong` di kem
`ky_vong_khong_loc`, `profit_factor` di kem `profit_factor_khong_loc`. Khong
con so nao o day duoc doc mot minh.
"""
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import config
from . import continual, meta_label, meta_train, model_store
from . import validation as val_mod
from .continual import KetQuaCong, _so

logger = logging.getLogger(__name__)


def cong_thang_cap(kq: meta_train.KetQuaMeta,
                   chi_so_champion: Optional[Dict] = None, cfg=config) -> KetQuaCong:
    """Cham diem bo loc. dat=True chi khi TAT CA dieu kien qua."""
    cong = KetQuaCong()
    if not kq.thanh_cong:
        cong.dong.append("  huan luyen that bai: %s" % "; ".join(kq.loi))
        return cong

    cs, xao = kq.chi_so, kq.chi_so_xao
    ket: List[bool] = []

    def kiem(ten, gia_tri, mo_ta, qua):
        ket.append(bool(qua))
        cong.them(ten, gia_tri, mo_ta, qua)

    # --- 1. Doi chung ro ri: truot cai nay thi moi thu khac vo nghia ---
    if xao:
        auc_xao = xao.get("auc", float("nan"))
        tran_xao = getattr(cfg, "GATE_META_XAO_AUC_MAX", 0.58)
        sach = not np.isfinite(auc_xao) or auc_xao <= tran_xao
        kiem("doi chung nhan xao", _so(auc_xao, "%.3f"), "AUC <= %.2f" % tran_xao, sach)
        if not sach:
            cong.canh_bao_ro_ri = True
            cong.dong.append("  !! NHAN XAO TRON VAN CHO AUC CAO -> PIPELINE CO RO RI.")
            return cong

    # --- 2. Du mau de ket luan ---
    n_giu = cs.get("so_lenh_giu", 0)
    min_giu = getattr(cfg, "GATE_META_MIN_LENH_GIU", 30)
    kiem("lenh con lai sau loc", "%d/%d" % (n_giu, cs.get("so_lenh_goc", 0)),
         ">= %d" % min_giu, n_giu >= min_giu)

    # --- 3. Bo loc co thuc su LOC khong ---
    ty_le = cs.get("ty_le_giu", 1.0)
    lo = getattr(cfg, "GATE_META_TY_LE_GIU_MIN", 0.15)
    hi = getattr(cfg, "GATE_META_TY_LE_GIU_MAX", 0.90)
    # Giu 3% la chon vai lenh may man trong so nhieu; giu 98% la khong loc gi.
    kiem("ty le giu lai", _so(ty_le, "%.3f"), "trong [%.2f, %.2f]" % (lo, hi),
         lo <= ty_le <= hi)

    auc = cs.get("auc", float("nan"))
    sao = getattr(cfg, "GATE_META_AUC_MIN", 0.52)
    tran = getattr(cfg, "GATE_META_AUC_MAX", 0.80)
    kiem("AUC", _so(auc, "%.3f"), "trong [%.2f, %.2f]" % (sao, tran),
         np.isfinite(auc) and sao <= auc <= tran)
    if np.isfinite(auc) and auc > tran:
        cong.canh_bao_ro_ri = True
        cong.dong.append("  !! AUC %.3f qua cao cho du lieu gia - nghi ro ri." % auc)

    # --- 4. Co ra tien khong, VA co hon viec khong loc gi khong ---
    kv = cs.get("ky_vong", 0.0)
    kv_goc = cs.get("ky_vong_khong_loc", 0.0)
    kv_min = getattr(cfg, "GATE_META_KY_VONG_MIN", 0.0005)
    kiem("ky vong sau loc", _so(kv), "> %.4f" % kv_min, kv > kv_min)

    cai_thien = cs.get("cai_thien", 0.0)
    ct_min = getattr(cfg, "GATE_META_CAI_THIEN_MIN", 0.002)
    kiem("hon 'nghe het'", "%s vs %s" % (_so(kv), _so(kv_goc)),
         "hon >= %.4f" % ct_min, cai_thien >= ct_min)

    pf = cs.get("profit_factor", 0.0)
    pf_min = getattr(cfg, "GATE_META_PF_MIN", 1.10)
    kiem("profit factor", "%s vs %s" % (_so(pf, "%.2f"),
                                        _so(cs.get("profit_factor_khong_loc"), "%.2f")),
         ">= %.2f" % pf_min, pf >= pf_min)

    # --- 5. Hon champion tren cung khoi ---
    if chi_so_champion:
        kv_c = chi_so_champion.get("ky_vong", float("-inf"))
        bien = getattr(cfg, "GATE_META_CAI_THIEN_MIN", 0.002) / 2.0
        kiem("hon champion", "%s vs %s" % (_so(kv), _so(kv_c)),
             ">= champion + %.4f" % bien, kv >= kv_c + bien)
    else:
        cong.dong.append("  %-22s %-14s %-22s %s"
                         % ("hon champion", "khong co", "chua co bo loc nao", "BO QUA"))

    cong.dat = all(ket)
    return cong


def chay_mot_vong(symbols: List[str], interval: str = None, cfg=config,
                  kho: model_store.KhoModel = None, dung_phai_sinh: bool = True,
                  max_horizon: int = 60, seed: int = 0,
                  ten_chien_luoc: List[str] = None,
                  bo_qua_cong: bool = False) -> Dict:
    """Huan luyen mot bo loc va quyet dinh co thang cap khong."""
    from .strategies import build_ensemble

    interval = interval or cfg.KLINE_INTERVAL
    kho = kho or KhoMeta()
    ten_chien_luoc = ten_chien_luoc or list(getattr(cfg, "META_CHIEN_LUOC", ["breakout"]))
    bat_dau = time.time()

    frames = continual.nap_khung(symbols, interval)
    if len(frames) < 2:
        return {"trang_thai": "thieu_du_lieu",
                "thong_diep": "chi nap duoc %d ma" % len(frames)}

    derivs = continual.nap_phai_sinh(list(frames), interval) if dung_phai_sinh else {}
    if derivs:
        thieu = [s for s in frames if s not in derivs]
        if thieu:
            frames = {k: v for k, v in frames.items() if k in derivs}

    chien_luocs = build_ensemble(ten_chien_luoc)
    logger.info("Xay bo meta tu %d ma, chien luoc: %s ...",
                len(frames), ",".join(ten_chien_luoc))
    bo = meta_label.xay_bo_meta(frames, chien_luocs, cfg, max_horizon, derivs or None)
    if bo.empty:
        return {"trang_thai": "khong_co_tin_hieu",
                "thong_diep": "chien luoc khong phat tin hieu nao tren du lieu nay"}

    cot = meta_label.cot_dac_trung_meta(co_xep_hang=True, co_phai_sinh=bool(derivs))
    so_moc = bo.attrs.get("so_moc") or int(bo["_i"].max()) + 1

    # HAI khoi, khong phai ba: vung train tu hieu chuan bang purged K-fold.
    # Mot khoi hieu chuan lien mach o mat do tin hieu nay chi dai dien cho MOT
    # che do thi truong - lan chay dau tien roi dung mot doan breakout thang 21%
    # thay vi 43%, va ca nguong lan so vong boosting deu bi doan do quyet dinh.
    khoi = val_mod.cat_khoi_cuoi(
        so_moc, val_bars=getattr(cfg, "POLICY_VAL_BARS", 700), embargo=max_horizon)
    if khoi is None:
        return {"trang_thai": "thieu_du_lieu",
                "thong_diep": "chi co %d moc nen, khong du de cat khoi kiem dinh" % so_moc}

    goc = meta_label.bien_do_thuc(bo)
    logger.info("Bo meta %d tin hieu | %d dac trung | %s", len(bo), len(cot), khoi)
    logger.info("Truoc khi loc: ty le lai %.4f | ky vong %+.5f | hoa von can %.4f",
                goc["ty_le_lai_co_so"], goc["ky_vong_khong_loc"], goc["p_hoa_von"])

    kq = meta_train.huan_luyen(bo, cot, khoi, cfg, seed=seed, so_moc=so_moc)
    if not kq.thanh_cong:
        return {"trang_thai": "huan_luyen_that_bai", "thong_diep": "; ".join(kq.loi),
                "loi": kq.loi}

    chi_so_champion = _cham_lai_champion(kho, bo, cot, khoi, kq.nguong,
                                         kq.bien_do, so_moc)
    cong = cong_thang_cap(kq, chi_so_champion, cfg)

    van_tay = model_store.dau_van_tay(cot, cfg, max_horizon)
    meta = {
        "phien_ban": kho.phien_ban_moi(van_tay),
        "loai": model_store.META,
        "dau_van_tay": van_tay,
        "cot_dac_trung": cot,
        "max_horizon": max_horizon,
        "interval": interval,
        "symbols": sorted(frames),
        "chien_luoc_nguon": ten_chien_luoc,
        "huan_luyen_luc": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tham_so_lgb": meta_train.THAM_SO_LGB,
        "tham_so_bai_toan": {t: getattr(cfg, t, None) for t in model_store.THAM_SO_BAI_TOAN},
        "chia_khoi": str(khoi),
        "so_dong": kq.so_dong,
        "bien_do": kq.bien_do,
        "nguong": kq.nguong,
        "cach_chon_nguong": kq.cach_chon_nguong.get("cach_chon"),
        "chi_so_ngoai_mau": kq.chi_so_ngoai_mau,
        "chi_so": kq.chi_so,
        "chi_so_nhan_xao": kq.chi_so_xao,
        "chi_so_champion_cung_khoi": chi_so_champion,
        "goc_toan_bo_lich_su": goc,
        "cong_dat": cong.dat,
        "cong_chi_tiet": cong.dong,
        "tam_quan_trong": meta_train.tam_quan_trong(kq.booster, cot),
        "giay_huan_luyen": round(time.time() - bat_dau, 1),
    }
    pb = kho.luu_meta(kq.booster, meta, the=the_mo_hinh(meta, cong))
    ra = {"phien_ban": pb, "cong": cong, "chi_so": kq.chi_so,
          "chi_so_champion": chi_so_champion, "meta": meta}

    if cong.canh_bao_ro_ri:
        kho.ghi_su_kien("nghi_ro_ri", pb, "; ".join(cong.dong[-2:]))
        ra["trang_thai"] = "nghi_ro_ri"
        return ra

    if cong.dat or bo_qua_cong:
        kho.thang_cap(pb, "qua cong thong ke" if cong.dat
                      else "EP THANG CAP - KHONG qua cong thong ke")
        ra["trang_thai"] = "da_thang_cap" if cong.dat else "ep_thang_cap"
    else:
        kho.ghi_su_kien("tu_choi", pb, "truot cong thong ke")
        ra["trang_thai"] = "tu_choi"
    return ra


def quet_walkforward(symbols: List[str], interval: str = None, cfg=config,
                     max_horizon: int = 60, so_cua_so: int = 6,
                     val_bars: int = 700, cac_seed: List[int] = None,
                     ten_chien_luoc: List[str] = None,
                     dung_phai_sinh: bool = True) -> pd.DataFrame:
    """Chay lai bo loc tren NHIEU cua so kiem dinh truot + nhieu seed.

    VI SAO PHAI CO HAM NAY TRUOC KHI TIN BAT KY CON SO NAO. Mot lan chay cho ra
    mot cua so kiem dinh duy nhat - tuc mot doan thi truong duy nhat. Da thay
    ro dieu do nguy hiem den muc nao: mot khoi 500 nen cua chinh du an nay roi
    dung doan breakout thang 21% trong khi trung binh lich su la 43%. Ket luan
    rut ra tu mot cua so la ket luan ve mot che do, khong phai ve bo loc.

    Neu bo loc that su co ich thi loi the phai xuat hien o DA SO cac cua so, va
    khong phu thuoc vao seed. Neu no chi dep o mot vai cua so thi cai ta dang
    nhin la phuong sai, va con so trung binh dep den may cung khong doi duoc
    dieu do.

    Tra ve mot dong cho moi (cua so, seed) - de nguoi doc tu thay phan tan chu
    khong chi thay trung binh.
    """
    from .strategies import build_ensemble

    interval = interval or cfg.KLINE_INTERVAL
    cac_seed = cac_seed or [0]
    ten_chien_luoc = ten_chien_luoc or list(getattr(cfg, "META_CHIEN_LUOC", ["breakout"]))

    frames = continual.nap_khung(symbols, interval)
    derivs = continual.nap_phai_sinh(list(frames), interval) if dung_phai_sinh else {}
    if derivs:
        frames = {k: v for k, v in frames.items() if k in derivs}

    bo = meta_label.xay_bo_meta(frames, build_ensemble(ten_chien_luoc), cfg,
                                max_horizon, derivs or None)
    if bo.empty:
        return pd.DataFrame()

    cot = meta_label.cot_dac_trung_meta(True, bool(derivs))
    so_moc = bo.attrs.get("so_moc") or int(bo["_i"].max()) + 1

    dong = []
    for k in range(so_cua_so):
        # Cua so gan nhat truoc, roi lui dan ve qua khu.
        val_hi = so_moc - k * val_bars
        val_lo = val_hi - val_bars
        train_hi = val_lo - max_horizon
        if train_hi < 2000:
            break
        khoi = val_mod.KhoiChia(k, 0, train_hi, val_lo, val_hi)

        for seed in cac_seed:
            kq = meta_train.huan_luyen(bo, cot, khoi, cfg, seed=seed,
                                       kiem_tra_xao=False, so_moc=so_moc)
            if not kq.thanh_cong:
                dong.append({"cua_so": k, "seed": seed, "loi": "; ".join(kq.loi)})
                continue
            cs = kq.chi_so
            dong.append({
                "cua_so": k, "seed": seed,
                "n_giu": cs.get("so_lenh_giu"), "n_goc": cs.get("so_lenh_goc"),
                "ty_le_giu": cs.get("ty_le_giu"),
                "ky_vong": cs.get("ky_vong"),
                "ky_vong_khong_loc": cs.get("ky_vong_khong_loc"),
                "cai_thien": cs.get("cai_thien"),
                "pf": cs.get("profit_factor"),
                "pf_khong_loc": cs.get("profit_factor_khong_loc"),
                "auc": cs.get("auc"),
                "nguong": kq.nguong,
            })
            logger.info("cua so %d seed %d: giu %.3f | ky vong %+.5f vs %+.5f | AUC %.3f",
                        k, seed, cs.get("ty_le_giu", 0), cs.get("ky_vong", 0),
                        cs.get("ky_vong_khong_loc", 0), cs.get("auc", float("nan")))
    return pd.DataFrame(dong)


def _cham_lai_champion(kho, bo, cot, khoi, nguong, bien_do, so_moc) -> Optional[Dict]:
    """Cham champion tren DUNG khoi kiem dinh cua challenger.

    Dung lai so lieu cu cua champion la so hai con so do tren hai khoi khac nhau
    - hai thi truong khac nhau - va ket luan tu do khong co nghia gi.
    """
    mh = kho.nap_champion()
    if mh is None or not mh.la_meta:
        return None
    if list(mh.cot_dac_trung) != list(cot):
        logger.warning("Champion dung bo dac trung khac - challenger phai tu vuot "
                       "nguong tuyet doi.")
        return None
    te = bo[(bo["_i"] >= khoi.test_lo) & (bo["_i"] < khoi.test_hi)]
    te = te.dropna(subset=cot + ["y", "ret"])
    if len(te) < 30:
        return None
    w = val_mod.trong_so_duy_nhat_panel(te, so_moc)
    try:
        return meta_train.danh_gia(mh.booster, te, cot, nguong, bien_do, w)
    except Exception as e:
        logger.error("Khong cham lai duoc champion: %s", e)
        return None


class KhoMeta(model_store.KhoModel):
    """Kho rieng cho bo loc meta.

    Tach thu muc thay vi tron chung voi AI policy: hai loai mo hinh tra loi hai
    cau hoi khac nhau, co champion rieng, va gop chung se khien mot lan
    `thang_cap()` cua ben nay am tham go champion cua ben kia.
    """

    def __init__(self, thu_muc: str = None):
        super().__init__(thu_muc or os.path.join(config.BASE_DIR, "models_meta"))


def the_mo_hinh(meta: Dict, cong: KetQuaCong) -> str:
    cs = meta.get("chi_so", {})
    xao = meta.get("chi_so_nhan_xao", {})
    goc = meta.get("goc_toan_bo_lich_su", {})
    d = [
        "# The bo loc %s" % meta.get("phien_ban"),
        "",
        "Bo loc tin hieu cua: **%s** | khung %s | %d ma"
        % (", ".join(meta.get("chien_luoc_nguon", [])), meta.get("interval"),
           len(meta.get("symbols", []))),
        "Huan luyen: %s | %s" % (meta.get("huan_luyen_luc"), meta.get("chia_khoi")),
        "",
        "## Cau hoi mo hinh nay tra loi",
        "",
        "Khong phai *\"nen nay nen mua khong\"* - ma *\"%s vua phat tin hieu, "
        "co dang nghe khong\"*." % ", ".join(meta.get("chien_luoc_nguon", [])),
        "",
        "Tren toan bo lich su, tin hieu tho cua chien luoc nay co ty le lai sau phi "
        "**%s** va ky vong **%s** moi lenh. Hoa von doi **%s** (tinh tu bien do "
        "thang/thua THUC, khong tu ty le barrier)."
        % (_so(goc.get("ty_le_lai_co_so"), "%.4f"),
           _so(goc.get("ky_vong_khong_loc"), "%+.5f"),
           _so(goc.get("p_hoa_von"), "%.4f")),
        "",
        "## Ket qua tren khoi kiem dinh (chua tung thay)",
        "",
        "| Chi so | Co bo loc | Khong loc | Nhan xao tron |",
        "|---|---|---|---|",
        "| Ky vong moi lenh | %s | %s | %s |"
        % (_so(cs.get("ky_vong"), "%+.5f"), _so(cs.get("ky_vong_khong_loc"), "%+.5f"),
           _so(xao.get("ky_vong"), "%+.5f")),
        "| Ty le thang | %s | %s | %s |"
        % (_so(cs.get("ty_le_thang"), "%.4f"), _so(cs.get("ty_le_thang_khong_loc"), "%.4f"),
           _so(xao.get("ty_le_thang"), "%.4f")),
        "| Profit factor | %s | %s | %s |"
        % (_so(cs.get("profit_factor"), "%.2f"),
           _so(cs.get("profit_factor_khong_loc"), "%.2f"),
           _so(xao.get("profit_factor"), "%.2f")),
        "| So lenh | %s | %s | %s |"
        % (cs.get("so_lenh_giu"), cs.get("so_lenh_goc"), xao.get("so_lenh_giu")),
        "| AUC | %s | | %s |" % (_so(cs.get("auc"), "%.3f"), _so(xao.get("auc"), "%.3f")),
        "",
        "Nguong vao lenh: **%s** (hoa von %s + bien an toan)"
        % (_so(meta.get("nguong"), "%.4f"), _so(cs.get("p_hoa_von"), "%.4f")),
        "Xac suat mo hinh du doan trai tu %s den %s."
        % (_so(cs.get("p_min"), "%.4f"), _so(cs.get("p_max"), "%.4f")),
        "",
        "## Cong thang cap: %s" % ("DAT" if cong.dat else "TRUOT"),
        "",
        "```",
        cong.in_ra(),
        "```",
        "",
        "## Dac trung quan trong nhat",
        "",
    ]
    for ten, v in meta.get("tam_quan_trong", [])[:10]:
        d.append("- %-24s %.1f%%" % (ten, v * 100))
    d += [
        "",
        "## Doc so nay the nao",
        "",
        "- Cot **Khong loc** la moc so sanh that. Bo loc chi co gia tri neu cot",
        "  **Co bo loc** hon han no - AUC dep ma ky vong khong hon thi vo dung.",
        "- **Ty le giu lai** %s: giu qua it la chon vai lenh may man trong so nhieu,"
        % _so(cs.get("ty_le_giu"), "%.3f"),
        "  giu qua nhieu la bo loc dang lam nen.",
        "- Cot **Nhan xao tron** phai vo dung. Neu no cung dep thi bo do da hong.",
        "- So lenh o day khong phai so lenh cua danh muc: khong co gioi han vi the",
        "  mo cung luc, khong co heat. No do chat luong BO LOC, khong phai loi nhuan.",
    ]
    return "\n".join(d)
