"""
Vong hoc lien tuc: huan luyen challenger -> cong thang cap -> theo doi -> ha cap.

DIEU QUAN TRONG NHAT VE FILE NAY: gia tri cua no nam o cho no BIET NOI KHONG.
Mot vong hoc lien tuc ma lan nao cung thang cap mo hinh moi thi khong phai la
he thong hoc - do la he thong duoi theo nhieu. Tren du lieu tai chinh, ket qua
DUNG cua hau het cac vong la "challenger khong hon champion, giu nguyen".

BON CUA AI PHAI QUA:

  1. PHEP CHIA SACH        - purge + embargo phai dat truoc khi huan luyen.
  2. DOI CHUNG NHAN XAO    - mo hinh tren nhan xao tron phai KHONG co ky nang.
                             Neu no cung dep thi ro ri, va moi so con lai la rac.
  3. NGUONG TUYET DOI      - AUC, IC, t-stat, ky vong sau phi, so lenh toi thieu.
                             Co ca tran TREN cho AUC: > 0.75 tren du lieu tai
                             chinh gan nhu luon la ro ri chu khong phai ky nang.
  4. HON CHAMPION          - phai tot hon mo hinh dang chay tren CUNG khoi kiem
                             dinh, hon mot bien du lon de khong doi mo hinh vi
                             nhieu ngau nhien.

CHIEU NGUOC LAI - HA CAP: `theo_doi_champion()` so ket qua THAT cua mo hinh dang
chay voi chinh so lieu kiem dinh cua no. Xuong qua nguong thi tu dong lui ve
phien ban truoc, hoac ve khong dung mo hinh nao. Duong lui phai chay tu dong,
vi luc can no nhat la luc khong ai dang nhin man hinh.

MOT DIEU CO Y KHONG LAM: khong huan luyen tren KET QUA LENH CUA CHINH BOT.
Nghe hop ly nhung do la cai bay: ta chi co ket qua cua nhung lenh DA VAO, tuc
mau bi loc boi chinh mo hinh cu. Mo hinh moi se hoc cach cung co thoi quen cua
mo hinh cu thay vi hoc thi truong, va sai lech tu khuech dai qua moi vong. Thay
vao do, nhan huan luyen luon la triple-barrier tinh cho MOI cay nen - co san du
ta co vao lenh hay khong. Ket qua lenh that chi dung de THEO DOI (muc 4 va phan
ha cap), khong bao gio de huan luyen.
"""
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import config
from . import datafeed, features, labeling, model_store, policy_train
from . import validation as val_mod

logger = logging.getLogger(__name__)


@dataclass
class KetQuaCong:
    dat: bool = False
    dong: List[str] = field(default_factory=list)
    canh_bao_ro_ri: bool = False

    def them(self, ten: str, gia_tri, dieu_kien: str, qua: bool) -> None:
        self.dong.append("  %-22s %-14s %-22s %s"
                         % (ten, gia_tri, dieu_kien, "DAT" if qua else "TRUOT"))

    def in_ra(self) -> str:
        return "\n".join(self.dong)


def _so(v, dinh_dang="%.4f") -> str:
    try:
        if v is None or (isinstance(v, float) and not np.isfinite(v)):
            return "n/a"
        return dinh_dang % v
    except (TypeError, ValueError):
        return str(v)


def cong_thang_cap(kq: policy_train.KetQuaHuanLuyen,
                   chi_so_champion: Optional[Dict] = None, cfg=config) -> KetQuaCong:
    """Cham diem challenger. Chi tra ve dat=True khi TAT CA dieu kien deu qua."""
    cong = KetQuaCong()
    if not kq.thanh_cong:
        cong.dong.append("  huan luyen that bai: %s" % "; ".join(kq.loi))
        return cong

    cs, xao = kq.chi_so, kq.chi_so_xao
    ket: List[bool] = []

    def kiem(ten, gia_tri, mo_ta, qua):
        ket.append(bool(qua))
        cong.them(ten, gia_tri, mo_ta, qua)

    # --- 1. Doi chung ro ri. Cai nay truot thi moi thu khac vo nghia. ---
    auc_xao = xao.get("auc_tb", float("nan")) if xao else float("nan")
    tran_xao = getattr(cfg, "GATE_POLICY_XAO_AUC_MAX", 0.55)
    if xao:
        sach = not np.isfinite(auc_xao) or auc_xao <= tran_xao
        kiem("doi chung nhan xao", _so(auc_xao, "%.3f"), "AUC <= %.2f" % tran_xao, sach)
        if not sach:
            cong.canh_bao_ro_ri = True
            cong.dong.append("  !! NHAN XAO TRON VAN CHO AUC CAO -> PIPELINE CO RO RI."
                             " Moi so lieu con lai deu khong dung duoc.")
            return cong

    # --- 2. Du lieu du de ket luan ---
    n_hd = kq.so_dong.get("val_hieu_dung", 0)
    min_hd = getattr(cfg, "GATE_POLICY_MIN_MAU_VAL", 300)
    kiem("mau kiem dinh", "%d" % n_hd, "hieu dung >= %d" % min_hd, n_hd >= min_hd)

    n_moc = cs.get("so_moc_ic", 0)
    kiem("so moc do IC", "%d" % n_moc, "moc >= 30", n_moc >= 30)

    # --- 3. Nguong tuyet doi: co ky nang khong? ---
    auc = cs.get("auc_tb", float("nan"))
    sao = getattr(cfg, "GATE_POLICY_AUC_MIN", 0.52)
    tran = getattr(cfg, "GATE_POLICY_AUC_MAX", 0.75)
    kiem("AUC trung binh", _so(auc, "%.3f"), "trong [%.2f, %.2f]" % (sao, tran),
         np.isfinite(auc) and sao <= auc <= tran)
    if np.isfinite(auc) and auc > tran:
        cong.canh_bao_ro_ri = True
        cong.dong.append("  !! AUC %.3f qua cao cho du lieu gia. Gan nhu chac chan"
                         " co dac trung nhin thay tuong lai - KHONG thang cap." % auc)

    ic, ic_t = cs.get("ic", float("nan")), cs.get("ic_t", float("nan"))
    ic_min = getattr(cfg, "GATE_POLICY_IC_MIN", 0.01)
    t_min = getattr(cfg, "GATE_POLICY_IC_T_MIN", 2.0)
    kiem("IC cat ngang", _so(ic), ">= %.3f" % ic_min, np.isfinite(ic) and ic >= ic_min)
    kiem("t-stat cua IC", _so(ic_t, "%.2f"), ">= %.1f" % t_min,
         np.isfinite(ic_t) and ic_t >= t_min)

    # --- 4. Co ra tien sau phi khong? ---
    so_lenh = cs.get("so_lenh", 0)
    min_lenh = getattr(cfg, "GATE_POLICY_MIN_LENH", 50)
    kiem("so lenh tren val", "%d" % so_lenh, ">= %d" % min_lenh, so_lenh >= min_lenh)

    ky_vong = cs.get("loi_nhuan_tb", 0.0)
    ky_vong_min = getattr(cfg, "GATE_POLICY_KY_VONG_MIN", 0.0005)
    kiem("ky vong moi lenh", _so(ky_vong), "> %.4f sau phi" % ky_vong_min,
         ky_vong > ky_vong_min)

    pf = cs.get("profit_factor", 0.0)
    pf_min = getattr(cfg, "GATE_POLICY_PF_MIN", 1.15)
    kiem("profit factor", _so(pf, "%.2f"), ">= %.2f" % pf_min, pf >= pf_min)

    ty_le = cs.get("ty_le_vao_lenh", 1.0)
    tran_ty_le = getattr(cfg, "GATE_POLICY_TY_LE_VAO_MAX", 0.35)
    # Mo hinh doi vao lenh o phan lon so nen la mo hinh chua hoc duoc rang phan
    # lon thoi diem khong dang giao dich sau khi tru phi.
    kiem("ty le vao lenh", _so(ty_le, "%.3f"), "<= %.2f" % tran_ty_le,
         ty_le <= tran_ty_le)

    # --- 5. Hon champion tren CUNG khoi kiem dinh ---
    if chi_so_champion:
        bien = getattr(cfg, "GATE_POLICY_CAI_THIEN_AUC", 0.005)
        auc_c = chi_so_champion.get("auc_tb", float("nan"))
        hon = np.isfinite(auc) and (not np.isfinite(auc_c) or auc >= auc_c + bien)
        kiem("hon champion (AUC)", "%s vs %s" % (_so(auc, "%.3f"), _so(auc_c, "%.3f")),
             ">= champion + %.3f" % bien, hon)

        kv_c = chi_so_champion.get("loi_nhuan_tb", float("-inf"))
        kiem("hon champion (ky vong)", "%s vs %s" % (_so(ky_vong), _so(kv_c)),
             ">= champion", ky_vong >= kv_c)
    else:
        cong.dong.append("  %-22s %-14s %-22s %s"
                         % ("hon champion", "khong co", "chua co mo hinh nao", "BO QUA"))

    cong.dat = all(ket)
    return cong


# ==========================================================
# Nap du lieu
# ==========================================================
def nap_khung(symbols: List[str], interval: str) -> Dict[str, pd.DataFrame]:
    ra = {}
    for s in symbols:
        df = datafeed.load_cache(s, interval)
        if df is None or len(df) < 500:
            logger.warning("Bo qua %s: khong co cache hoac qua ngan", s)
            continue
        ra[s] = df
    return ra


def nap_phai_sinh(symbols: List[str], interval: str) -> Dict[str, pd.DataFrame]:
    try:
        from research.download_derivatives import duong_dan
    except ImportError:
        return {}
    ra = {}
    for s in symbols:
        p = duong_dan(s, interval)
        if os.path.exists(p):
            ra[s] = pd.read_csv(p)
    return ra


# ==========================================================
# Mot vong hoc
# ==========================================================
def chay_mot_vong(symbols: List[str], interval: str = None, cfg=config,
                  kho: model_store.KhoModel = None, dung_phai_sinh: bool = True,
                  max_horizon: int = 60, seed: int = 0,
                  bo_qua_cong: bool = False) -> Dict:
    """Huan luyen mot challenger va quyet dinh co thang cap khong.

    bo_qua_cong=True chi dung khi nguoi van hanh CO Y muon ep mot mo hinh len
    lam champion (vi du de thu nghiem duong ong tren testnet). No duoc ghi vao
    nhat ky su kien de sau nay khong ai nham lan mo hinh do voi mot mo hinh
    da qua kiem dinh.
    """
    interval = interval or cfg.KLINE_INTERVAL
    kho = kho or model_store.KhoModel()
    bat_dau = time.time()

    frames = nap_khung(symbols, interval)
    if len(frames) < 2:
        return {"trang_thai": "thieu_du_lieu",
                "thong_diep": "chi nap duoc %d ma" % len(frames)}

    derivs = nap_phai_sinh(list(frames), interval) if dung_phai_sinh else {}
    if derivs:
        thieu = [s for s in frames if s not in derivs]
        if thieu:
            logger.info("Bo %d ma khong co du lieu phai sinh: %s",
                        len(thieu), ",".join(thieu))
            frames = {k: v for k, v in frames.items() if k in derivs}

    logger.info("Xay panel tu %d ma (co the mat vai phut) ...", len(frames))
    panel = features.xay_panel(frames, cfg, max_horizon=max_horizon,
                              derivs=derivs or None)
    cot = features.cot_dac_trung(co_xep_hang=True, co_phai_sinh=bool(derivs))
    so_moc = panel["timestamp"].nunique()

    ba_khoi = val_mod.cat_ba_khoi(
        so_moc,
        calib_bars=getattr(cfg, "POLICY_CALIB_BARS", 500),
        val_bars=getattr(cfg, "POLICY_VAL_BARS", 700),
        embargo=max_horizon,
    )
    if ba_khoi is None:
        return {"trang_thai": "thieu_du_lieu",
                "thong_diep": "chi co %d moc thoi gian, khong du de cat 3 khoi" % so_moc}

    logger.info("Panel %d dong | %d dac trung | %d moc | %s",
                len(panel), len(cot), so_moc, ba_khoi)

    kq = policy_train.huan_luyen(panel, cot, ba_khoi, cfg, seed=seed,
                                 max_horizon=max_horizon)
    if not kq.thanh_cong:
        return {"trang_thai": "huan_luyen_that_bai", "thong_diep": "; ".join(kq.loi)}

    # Champion phai duoc cham lai tren DUNG khoi kiem dinh nay, khong dung lai
    # so lieu cu cua no: hai khoi khac nhau thi hai con so khong so sanh duoc.
    chi_so_champion = _cham_lai_champion(kho, panel, cot, ba_khoi, kq.bien_do, cfg,
                                         max_horizon)

    cong = cong_thang_cap(kq, chi_so_champion, cfg)
    van_tay = model_store.dau_van_tay(cot, cfg, max_horizon)
    meta = {
        "phien_ban": kho.phien_ban_moi(van_tay),
        "dau_van_tay": van_tay,
        "cot_dac_trung": cot,
        "max_horizon": max_horizon,
        "interval": interval,
        "symbols": sorted(frames),
        "huan_luyen_luc": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tham_so_lgb": policy_train.THAM_SO_LGB,
        "tham_so_bai_toan": {t: getattr(cfg, t, None) for t in model_store.THAM_SO_BAI_TOAN},
        "chia_khoi": str(ba_khoi),
        "so_dong": kq.so_dong,
        "bien_do": kq.bien_do,
        "chi_so": kq.chi_so,
        "chi_so_nhan_xao": kq.chi_so_xao,
        "chi_so_champion_cung_khoi": chi_so_champion,
        "cong_dat": cong.dat,
        "cong_chi_tiet": cong.dong,
        "tam_quan_trong_long": policy_train.tam_quan_trong(kq.booster_long, cot),
        "tam_quan_trong_short": policy_train.tam_quan_trong(kq.booster_short, cot),
        "giay_huan_luyen": round(time.time() - bat_dau, 1),
    }
    pb = kho.luu(kq.booster_long, kq.booster_short, meta, the=the_mo_hinh(meta, cong))

    ra = {"phien_ban": pb, "cong": cong, "chi_so": kq.chi_so,
          "chi_so_champion": chi_so_champion, "meta": meta}

    if cong.canh_bao_ro_ri:
        kho.ghi_su_kien("nghi_ro_ri", pb, "; ".join(cong.dong[-2:]))
        ra["trang_thai"] = "nghi_ro_ri"
        logger.error("CANH BAO RO RI o phien ban %s - KHONG thang cap", pb)
        return ra

    if cong.dat or bo_qua_cong:
        ly_do = ("qua cong thong ke" if cong.dat
                 else "EP THANG CAP - KHONG qua cong thong ke")
        kho.thang_cap(pb, ly_do)
        ra["trang_thai"] = "da_thang_cap" if cong.dat else "ep_thang_cap"
    else:
        kho.ghi_su_kien("tu_choi", pb, "truot cong thong ke")
        ra["trang_thai"] = "tu_choi"
        logger.info("Challenger %s KHONG qua cong - giu nguyen champion", pb)
    return ra


def _cham_lai_champion(kho: model_store.KhoModel, panel: pd.DataFrame, cot: List[str],
                       ba_khoi: val_mod.BaKhoi, bien_do: Dict, cfg,
                       max_horizon: int = 60) -> Optional[Dict]:
    """Cham champion tren cung khoi kiem dinh voi challenger."""
    mh = kho.nap_champion()
    if mh is None:
        return None
    if list(mh.cot_dac_trung) != list(cot):
        logger.warning("Champion %s dung bo dac trung khac - khong so sanh truc tiep"
                       " duoc, challenger phai tu vuot nguong tuyet doi.", mh.phien_ban)
        return None
    p = val_mod.them_vi_tri(panel)
    p = policy_train.them_muc_tieu(p)
    te = val_mod.lay_test(p, ba_khoi.khoi_val()).dropna(subset=cot + ["ret_long", "ret_short"])
    if len(te) < 200:
        return None
    w = val_mod.trong_so_duy_nhat_panel(te, int(p["_i"].max()) + 1)
    try:
        return policy_train.danh_gia(mh.booster_long, mh.booster_short, te, cot,
                                     bien_do, w, cfg, max_horizon)
    except Exception as e:
        logger.error("Khong cham lai duoc champion: %s", e)
        return None


def the_mo_hinh(meta: Dict, cong: KetQuaCong) -> str:
    """The mo hinh - trang nguoi doc truoc khi quyet dinh co tin mo hinh nay khong."""
    cs = meta.get("chi_so", {})
    xao = meta.get("chi_so_nhan_xao", {})
    d = [
        "# The mo hinh %s" % meta.get("phien_ban", "(chua dat ten)"),
        "",
        "Huan luyen: %s | khung %s | %d ma" % (meta.get("huan_luyen_luc"),
                                               meta.get("interval"),
                                               len(meta.get("symbols", []))),
        "Chia khoi: %s (embargo = max_horizon = %s nen)" % (meta.get("chia_khoi"),
                                                            meta.get("max_horizon")),
        "Dau van tay bai toan: %s" % meta.get("dau_van_tay"),
        "",
        "## Ket qua tren khoi kiem dinh (mo hinh chua tung thay)",
        "",
        "| Chi so | Gia tri | Nhan xao tron (phai ~0 ky nang) |",
        "|---|---|---|",
        "| AUC trung binh | %s | %s |" % (_so(cs.get("auc_tb"), "%.3f"),
                                          _so(xao.get("auc_tb"), "%.3f")),
        "| IC cat ngang | %s | %s |" % (_so(cs.get("ic")), _so(xao.get("ic"))),
        "| t-stat IC (da hieu chinh) | %s | %s |" % (_so(cs.get("ic_t"), "%.2f"),
                                                     _so(xao.get("ic_t"), "%.2f")),
        "| t-stat IC (tho - KHONG dung de ket luan) | %s | |"
        % _so(cs.get("ic_t_tho"), "%.2f"),
        "| Ky vong moi lenh | %s | %s |" % (_so(cs.get("loi_nhuan_tb")),
                                            _so(xao.get("loi_nhuan_tb"))),
        "| Profit factor | %s | %s |" % (_so(cs.get("profit_factor"), "%.2f"),
                                         _so(xao.get("profit_factor"), "%.2f")),
        "| So lenh | %s | %s |" % (cs.get("so_lenh"), xao.get("so_lenh")),
        "| Ty le vao lenh | %s | |" % _so(cs.get("ty_le_vao_lenh"), "%.3f"),
        "",
        "## Cong thang cap: %s" % ("DAT" if cong.dat else "TRUOT"),
        "",
        "```",
        cong.in_ra(),
        "```",
        "",
        "## Dac trung quan trong nhat (chieu mua)",
        "",
    ]
    for ten, v in meta.get("tam_quan_trong_long", [])[:10]:
        d.append("- %-24s %.1f%%" % (ten, v * 100))
    d += [
        "",
        "## Doc so nay the nao",
        "",
        "- AUC 0.50 = khong biet gi. 0.52-0.56 la muc thuc te tren du lieu gia.",
        "  Tren 0.75 gan nhu chac chan la ro ri chu khong phai ky nang.",
        "- Hai dong t-stat: ban THO gia dinh cac moc thoi gian doc lap, dieu do SAI",
        "  vi nhan keo dai %s nen nen cac moc canh nhau chong lan nhau."
        % meta.get("max_horizon"),
        "  Chenh lech giua hai dong chinh la muc do mot bao cao ngay tho se noi doi.",
        "  Cong thang cap chi dung ban da hieu chinh.",
        "- Cot 'nhan xao tron' la doi chung: mo hinh huan luyen tren nhan da xao.",
        "  No PHAI vo dung. Neu no cung dep thi bo do da hong.",
        "- 'Ky vong moi lenh' da tru phi taker va slippage ca hai chieu.",
        "- So lenh o day KHONG phai so lenh cua danh muc: khong co gioi han vi the",
        "  mo cung luc. No do chat luong nguon tin hieu, khong phai loi nhuan cuoi.",
    ]
    return "\n".join(d)


# ==========================================================
# Dong vong phan hoi: dien ket qua that cho cac du doan cu
# ==========================================================
def dong_ket_qua(storage, symbols: List[str], interval: str = None, cfg=config,
                 max_horizon: int = 60) -> int:
    """Dien ket qua triple-barrier cho cac du doan da du gia. Tra ve so ban ghi.

    Ket qua nay tinh tu DU LIEU THI TRUONG, khong tu lenh cua bot. Nho vay ca
    nhung lan policy bao HOLD cung co ket qua phan thuc te ("neu vao lenh luc do
    thi sao"), va so ghi chep khong bi thien lech ve phia nhung quyet dinh da
    duoc chon.
    """
    interval = interval or cfg.KLINE_INTERVAL
    ms_moi_nen = int(interval) * 60_000 if str(interval).isdigit() else 86_400_000
    han = int(time.time() * 1000) - max_horizon * ms_moi_nen

    cho = storage.policy_chua_co_ket_qua(han)
    if not cho:
        return 0

    theo_ma: Dict[str, List] = {}
    for r in cho:
        theo_ma.setdefault(r["symbol"], []).append(r)

    xong = 0
    for sym, rows in theo_ma.items():
        if symbols and sym not in symbols:
            continue
        df = datafeed.load_cache(sym, interval)
        if df is None or len(df) < 250:
            continue
        from . import indicators
        df = indicators.add_indicators(df)
        nhan = labeling.gan_nhan_hai_chieu(df, cfg, max_horizon)
        theo_ts = {int(t): i for i, t in enumerate(df["timestamp"].to_numpy())}

        with storage.conn() as con:
            hanh_dong = {r["id"]: con.execute(
                "SELECT action FROM policy_predictions WHERE id = ?",
                (r["id"],)).fetchone()["action"] for r in rows}

        for r in rows:
            i = theo_ts.get(int(r["bar_ts"]))
            if i is None or i >= len(nhan):
                continue
            rl = nhan["ret_long"].iloc[i]
            rs = nhan["ret_short"].iloc[i]
            if not (np.isfinite(rl) and np.isfinite(rs)):
                continue
            storage.cap_nhat_ket_qua_policy(r["id"], float(rl), float(rs),
                                            hanh_dong.get(r["id"], "HOLD"))
            xong += 1

    if xong:
        logger.info("Da dien ket qua that cho %d du doan cua policy", xong)
    return xong


def theo_doi_champion(storage, kho: model_store.KhoModel = None, cfg=config) -> Dict:
    """So ket qua THAT cua champion voi so lieu kiem dinh cua chinh no.

    Day la duong ha cap tu dong. No chi chay khi da du so lenh co ket qua - mot
    mo hinh khong duoc ha cap vi ba lenh dau tien xau, va cung khong duoc giu
    lai chi vi chua ai kip nhin.
    """
    kho = kho or model_store.KhoModel()
    pb = kho.champion_hien_tai()
    if not pb:
        return {"trang_thai": "khong_co_champion"}

    that = storage.thong_ke_policy(pb)
    toi_thieu = getattr(cfg, "GATE_POLICY_MIN_LENH_THEO_DOI", 40)
    if that.get("so_lenh", 0) < toi_thieu:
        return {"trang_thai": "chua_du_du_lieu", "so_lenh": that.get("so_lenh", 0),
                "can": toi_thieu, "phien_ban": pb}

    goc = kho.doc_meta(pb).get("chi_so", {})
    ky_vong_goc = goc.get("loi_nhuan_tb", 0.0)
    ky_vong_that = that["loi_nhuan_tb"]
    nguong_suy_giam = getattr(cfg, "GATE_POLICY_SUY_GIAM", 0.5)

    # Hai dieu kien ha cap khac nhau ve ban chat:
    #   - lo tien: du kiem dinh noi gi thi mat tien that van la mat tien that.
    #   - suy giam manh: van co lai nhung kem xa muc da duoc kiem dinh, tuc mo
    #     hinh khong con mo ta thi truong hien tai.
    lo_that = ky_vong_that <= 0
    suy_giam = ky_vong_goc > 0 and ky_vong_that < ky_vong_goc * (1.0 - nguong_suy_giam)

    ra = {"phien_ban": pb, "thuc_te": that, "kiem_dinh": goc,
          "suy_giam": suy_giam, "lo_that": lo_that}
    if lo_that or suy_giam:
        ly_do = ("ket qua that %.4f/lenh tren %d lenh, kiem dinh la %.4f"
                 % (ky_vong_that, that["so_lenh"], ky_vong_goc))
        moi = kho.ha_cap(ly_do)
        ra["trang_thai"] = "da_ha_cap"
        ra["champion_moi"] = moi
    else:
        ra["trang_thai"] = "binh_thuong"
    return ra
