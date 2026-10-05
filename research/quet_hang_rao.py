"""
Quet hinh hoc barrier x muc chi phi - tim cau hinh ma KY NANG VUOT HANG RAO.

BOI CANH: vong hoc dau tien cho ket qua ro rang va kho chiu - mo hinh XEP HANG
DUOC (AUC 0.627, IC 0.078 t=2.61) nhung KHONG CO NEN NAO dang vao lenh:

    ty le co so ret_long > 0    0.3949
    p_long mo hinh du doan      0.3951 ... 0.4195
    p can de hoa von sau phi    0.432
    => thieu 1,3 diem phan tram

Ky nang la that. Van de la HANG RAO CHI PHI CAO HON KY NANG. Nguong hoa von:

    p* = (nguong_EV - lo) / (lai - lo)

`lai` va `lo` deu do bang boi so ATR va deu bi tru chi phi, nen co HAI don bay:

  1. CHI PHI: spot taker 0.10% -> futures taker 0.055% -> futures maker 0.02%.
     Chi phi thap thi `lai` to len va `lo` nho di -> p* tut xuong.

  2. HINH HOC BARRIER: TP/SL = 3/2 cho p* co so 0.40. TP/SL = 4/2 cho 0.333.
     Nhung barrier rong hon cung lam xac suat thang GIAM - khong co bua an mien
     phi. Chi co do moi biet ben nao thang.

CANH BAO VE CHINH PHEP QUET NAY: thu 18 cau hinh roi chon cai dep nhat LA MOT
DANG TIM KIEM, va no overfit y het viec quet tham so chien luoc. Cau hinh nao
"thang" o day mới chi la GIA THUYET - no phai di qua `run_policy.py hoc` day du
voi cong thang cap truoc khi duoc coi la co that. Ket qua o day khong bao gio
duoc dung de bien minh cho viec ha cong.

    python -m research.quet_hang_rao
    python -m research.quet_hang_rao --nhanh    # luoi nho, de thu duong ong
"""
import argparse
import copy
import os
import sys
import time
import types
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

import config
from src import continual, features, policy_train
from src import validation as val_mod

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "reports")

# (ten, ATR_STOP_MULT, ATR_TP_MULT)
HINH_HOC: List[Tuple[str, float, float]] = [
    ("2.0 / 3.0  (hien tai)", 2.0, 3.0),
    ("2.0 / 4.0", 2.0, 4.0),
    ("2.0 / 5.0", 2.0, 5.0),
    ("1.5 / 3.0", 1.5, 3.0),
    ("2.5 / 5.0", 2.5, 5.0),
    ("3.0 / 6.0", 3.0, 6.0),
]

# (ten, FEE_TAKER moi chieu)
CHI_PHI: List[Tuple[str, float]] = [
    ("spot taker  0.100%", 0.0010),
    ("fut taker   0.055%", 0.00055),
    ("fut maker   0.020%", 0.00020),
]

FEE_THAM_CHIEU = 0.0010


def cfg_voi(stop: float, tp: float, fee: float):
    c = types.SimpleNamespace(**{k: getattr(config, k) for k in dir(config) if k.isupper()})
    c.ATR_STOP_MULT, c.ATR_TP_MULT = stop, tp
    c.FEE_TAKER = c.FEE_MAKER = fee
    return c


def doi_chi_phi(panel: pd.DataFrame, fee_moi: float) -> pd.DataFrame:
    """Dieu chinh ret_net sang muc phi khac ma KHONG phai gan nhan lai.

    ret_net = gross - 2*fee, trong do `gross` da gom slippage vao gia. Giu
    slippage co dinh thi doi phi chi la mot phep tinh tien - chinh xac tuyet doi,
    va tiet kiem duoc phan cham nhat cua ca quy trinh (gan nhan triple-barrier).
    """
    out = panel.copy()
    bu = 2.0 * (FEE_THAM_CHIEU - fee_moi)
    for cot in ("ret_long", "ret_short"):
        out[cot] = out[cot] + bu
    out["edge"] = out["ret_long"] - out["ret_short"]
    return out


def nguong_hoa_von(lai: float, lo: float, nguong_ev: float) -> float:
    """p* = xac suat thang toi thieu de mot lenh dang vao."""
    if lai <= lo:
        return float("nan")
    return (nguong_ev - lo) / (lai - lo)


def do_mot_cau_hinh(panel: pd.DataFrame, cot: List[str], ba_khoi, cfg,
                    max_horizon: int, seed: int) -> Dict:
    kq = policy_train.huan_luyen(panel, cot, ba_khoi, cfg, seed=seed,
                                 kiem_tra_xao=False, max_horizon=max_horizon)
    if not kq.thanh_cong:
        return {"loi": "; ".join(kq.loi)}

    te = policy_train.them_muc_tieu(val_mod.lay_test(
        val_mod.them_vi_tri(panel), ba_khoi.khoi_val())).dropna(
        subset=cot + ["ret_long", "ret_short"])
    X = te[cot].to_numpy(dtype=float)
    p_long = kq.booster_long.predict(X)

    bd = kq.bien_do
    nguong_ev = getattr(cfg, "POLICY_EV_MIN", 0.0015)
    p_sao = nguong_hoa_von(bd["lai_long"], bd["lo_long"], nguong_ev)

    ra = dict(kq.chi_so)
    ra.update({
        "ty_le_co_so": float((te["ret_long"] > 0).mean()),
        "p_max": float(p_long.max()),
        "p_tb": float(p_long.mean()),
        "p_sao": float(p_sao),
        "khoang_cach": float(p_long.max() - p_sao),
        "lai_long": bd["lai_long"], "lo_long": bd["lo_long"],
    })
    return ra


def main() -> int:
    ap = argparse.ArgumentParser(description="Quet barrier x chi phi")
    ap.add_argument("--symbols", default=None)
    ap.add_argument("--interval", default=None)
    ap.add_argument("--max-horizon", type=int, default=60)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--nhanh", action="store_true", help="chi 2 hinh hoc x 2 chi phi")
    args = ap.parse_args()

    interval = args.interval or config.KLINE_INTERVAL
    if args.symbols:
        syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        tep = [f for f in os.listdir(config.CACHE_DIR)
               if f.endswith("_%s.csv" % interval) and "_deriv_" not in f]
        syms = sorted(f.rsplit("_", 1)[0] for f in tep)

    hinh_hoc = HINH_HOC[:2] if args.nhanh else HINH_HOC
    chi_phi = CHI_PHI[:2] if args.nhanh else CHI_PHI

    print("=" * 104)
    print("QUET HANG RAO - tim cau hinh ma ky nang xep hang vuot duoc chi phi")
    print("Ma: %d | khung: %s | %d hinh hoc x %d muc chi phi = %d cau hinh"
          % (len(syms), interval, len(hinh_hoc), len(chi_phi),
             len(hinh_hoc) * len(chi_phi)))
    print("=" * 104)

    frames = continual.nap_khung(syms, interval)
    derivs = continual.nap_phai_sinh(list(frames), interval)
    if derivs:
        frames = {k: v for k, v in frames.items() if k in derivs}
    cot = features.cot_dac_trung(co_xep_hang=True, co_phai_sinh=bool(derivs))
    print("Nap %d ma, %d dac trung\n" % (len(frames), len(cot)))

    ket_qua = []
    for ten_hh, stop, tp in hinh_hoc:
        t0 = time.time()
        cfg_goc = cfg_voi(stop, tp, FEE_THAM_CHIEU)
        # Gan nhan MOT LAN cho moi hinh hoc; cac muc phi chi la phep tinh tien.
        panel_goc = features.xay_panel(frames, cfg_goc, max_horizon=args.max_horizon,
                                       derivs=derivs or None)
        so_moc = panel_goc["timestamp"].nunique()
        ba_khoi = val_mod.cat_ba_khoi(
            so_moc, calib_bars=getattr(config, "POLICY_CALIB_BARS", 500),
            val_bars=getattr(config, "POLICY_VAL_BARS", 700), embargo=args.max_horizon)
        if ba_khoi is None:
            print("%-22s  khong du moc thoi gian de cat 3 khoi" % ten_hh)
            continue
        print("%-22s  panel %d dong, %d moc  (gan nhan %.0fs)"
              % (ten_hh, len(panel_goc), so_moc, time.time() - t0))

        for ten_cp, fee in chi_phi:
            cfg = cfg_voi(stop, tp, fee)
            panel = doi_chi_phi(panel_goc, fee)
            r = do_mot_cau_hinh(panel, cot, ba_khoi, cfg, args.max_horizon, args.seed)
            if "loi" in r:
                print("    %-20s LOI: %s" % (ten_cp, r["loi"][:60]))
                continue
            r.update({"hinh_hoc": ten_hh, "chi_phi": ten_cp,
                      "stop": stop, "tp": tp, "fee": fee})
            ket_qua.append(r)
            print("    %-20s p_max %.4f | p* %.4f | cach %+.4f | lenh %5d | ky vong %+.5f"
                  % (ten_cp, r["p_max"], r["p_sao"], r["khoang_cach"],
                     r["so_lenh"], r["loi_nhuan_tb"]))

    if not ket_qua:
        print("\nKhong cau hinh nao chay duoc.")
        return 1

    df = pd.DataFrame(ket_qua).sort_values("khoang_cach", ascending=False)
    print("\n" + "=" * 104)
    print("XEP HANG THEO KHOANG CACH DEN NGUONG HOA VON")
    print("=" * 104)
    print("%-22s %-20s %8s %8s %9s %7s %10s %6s"
          % ("Hinh hoc", "Chi phi", "p_max", "p*", "Cach", "Lenh", "Ky vong", "PF"))
    print("-" * 104)
    for _, r in df.iterrows():
        pf = r["profit_factor"]
        print("%-22s %-20s %8.4f %8.4f %+9.4f %7d %+10.5f %6s"
              % (r["hinh_hoc"], r["chi_phi"], r["p_max"], r["p_sao"],
                 r["khoang_cach"], r["so_lenh"], r["loi_nhuan_tb"],
                 "inf" if not np.isfinite(pf) else "%.2f" % pf))

    co_lenh = df[df["so_lenh"] > 0]
    print("\n" + "=" * 104)
    if len(co_lenh) == 0:
        print("KHONG cau hinh nao sinh ra lenh. Hang rao chi phi van cao hon ky nang")
        print("o MOI hinh hoc va MOI muc phi da thu. Ket luan: phai NANG XEP HANG")
        print("bang du lieu moi, khong the ha hang rao them nua.")
    else:
        tot = co_lenh.iloc[0]
        print("%d/%d cau hinh sinh ra lenh. Tot nhat: %s + %s"
              % (len(co_lenh), len(df), tot["hinh_hoc"], tot["chi_phi"]))
        print("  %d lenh | ky vong %+.5f/lenh | PF %.2f | AUC %.3f | IC %.4f (t=%.2f)"
              % (tot["so_lenh"], tot["loi_nhuan_tb"], tot["profit_factor"],
                 tot.get("auc_tb", float("nan")), tot.get("ic", float("nan")),
                 tot.get("ic_t", float("nan"))))
        print("\nDAY MOI LA GIA THUYET. Da thu %d cau hinh va chon cai dep nhat -" % len(df))
        print("do la mot phep tim kiem va no overfit y nhu quet tham so chien luoc.")
        print("Buoc bat buoc tiep theo: dat tham so do vao .env roi chay")
        print("  python run_policy.py hoc")
        print("de no di qua cong thang cap day du (co doi chung nhan xao tron).")
    print("=" * 104)

    os.makedirs(OUT_DIR, exist_ok=True)
    p = os.path.join(OUT_DIR, "quet_hang_rao.csv")
    df.to_csv(p, index=False)
    print("\nDa luu %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
