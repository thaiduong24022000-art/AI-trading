"""
Do Information Coefficient: bo dac trung hien co chua duoc bao nhieu thong tin?

CAU HOI CHAN TREN: truoc khi xay AI policy, phai biet du lieu dau vao co gi de
hoc khong. Neu IC ~ 0 thi moi kien truc mo hinh tren bo dac trung nay deu vo
vong, va viec phai lam la MO RONG DAU VAO chu khong phai lam mo hinh to hon.
Mot buoi do o day tiet kiem duoc vai thang xay nham.

IC = tuong quan hang (Spearman) giua du doan va ket qua thuc, tinh CAT NGANG
tai tung moc thoi gian roi lay trung binh. Trong nganh, IC 0.02-0.05 da la co
gia tri; IC > 0.1 tren du lieu tai chinh gan nhu luon la dau hieu ro ri.

BA LOP CHONG TU LUA:
1. PURGE: nhan triple-barrier mat nhieu nen moi nga ngu, nen mau gan ranh
   train/test co nhan keo dai sang vung test -> phai loai bo. Khong purge thi
   IC duong gia tao.
2. EMBARGO: bo them mot khoang sau moi train de tranh tuong quan chuoi con sot.
3. DOI CHUNG NHAN XAO TRON: chay lai toan bo voi nhan da xao. Neu IC van duong
   thi pipeline co ro ri o dau do, va MOI so lieu khac deu vo nghia.
   Bo test khong the that bai thi khong chung minh duoc gi.
"""
import argparse
import os
import sys
from typing import Dict, List

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

import config
from src import datafeed, features

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "reports")


def nap(symbols: List[str], interval: str) -> Dict[str, pd.DataFrame]:
    out = {}
    for s in symbols:
        df = datafeed.load_cache(s, interval)
        if df is None:
            print("  bo qua %s (khong co cache)" % s)
            continue
        df["datetime"] = pd.to_datetime(df["datetime"])
        out[s] = df
    return out


def nap_phai_sinh(symbols: List[str], interval: str) -> Dict[str, pd.DataFrame]:
    """Nap funding/open interest. Ma nao thieu thi bo khoi nghien cuu han -
    de lai voi NaN se lam Ridge vo va lam so lieu giua cac ma khong so sanh duoc."""
    from research.download_derivatives import duong_dan
    out = {}
    for s in symbols:
        p = duong_dan(s, interval)
        if os.path.exists(p):
            out[s] = pd.read_csv(p)
    return out


def ic_cat_ngang(du_doan: np.ndarray, thuc: np.ndarray, ts: np.ndarray,
                 min_ma: int = 8) -> float:
    """Spearman tai tung moc thoi gian roi lay trung binh.

    min_ma: moc nao co qua it ma thi bo - xep hang tren 3 ma khong co y nghia.
    """
    ics = []
    for _, idx in pd.Series(range(len(ts))).groupby(ts).groups.items():
        i = np.asarray(idx)
        if len(i) < min_ma:
            continue
        a, b = du_doan[i], thuc[i]
        if np.std(a) == 0 or np.std(b) == 0:
            continue
        r = stats.spearmanr(a, b).statistic
        if np.isfinite(r):
            ics.append(r)
    return float(np.mean(ics)) if ics else np.nan


def chay(panel: pd.DataFrame, cols: List[str], target: str,
         train_bars: int, test_bars: int, embargo: int,
         xao_nhan: bool = False, seed: int = 0, stride: int = 1) -> pd.DataFrame:
    """stride > 1 chi giu moi nen thu N.

    Voi max_horizon=60, hai mau canh nhau co nhan chong lan toi 98%: chung gan
    nhu la CUNG mot quan sat duoc dem 60 lan. Dieu do khong lam sai gia tri
    trung binh nhung lam PHONG DAI t-stat rat manh, vi t-stat gia dinh cac quan
    sat doc lap. Dat stride = max_horizon cho ra cac nhan roi nhau hoan toan;
    neu mot hieu ung bien mat khi do, no chua bao gio ton tai.
    """
    moc = np.sort(panel["timestamp"].unique())
    vi_tri = {t: k for k, t in enumerate(moc)}
    panel = panel.copy()
    panel["_i"] = panel["timestamp"].map(vi_tri)

    if xao_nhan:
        rng = np.random.default_rng(seed)
        panel[target] = rng.permutation(panel[target].to_numpy())

    rows = []
    start = 0
    while start + train_bars + embargo + test_bars <= len(moc):
        tr_lo, tr_hi = start, start + train_bars
        te_lo = tr_hi + embargo
        te_hi = te_lo + test_bars

        tr = panel[(panel["_i"] >= tr_lo) & (panel["_i"] < tr_hi)]
        # PURGE: bo mau co nhan keo dai cham vao vung test
        tr = tr[tr["_i"] + tr["bars_held"] < te_lo]
        te = panel[(panel["_i"] >= te_lo) & (panel["_i"] < te_hi)]

        if stride > 1:
            tr = tr[tr["_i"] % stride == 0]
            te = te[te["_i"] % stride == 0]

        tr = tr.dropna(subset=cols + [target])
        te = te.dropna(subset=cols + [target])
        if len(tr) < 300 or len(te) < 60:
            start += test_bars
            continue

        scaler = StandardScaler().fit(tr[cols])
        Xtr, Xte = scaler.transform(tr[cols]), scaler.transform(te[cols])
        ytr = tr[target].to_numpy()

        for ten, mo_hinh in (
            ("ridge", Ridge(alpha=10.0)),
            ("gbm", HistGradientBoostingRegressor(
                max_depth=3, max_iter=150, learning_rate=0.05,
                min_samples_leaf=200, l2_regularization=1.0, random_state=seed)),
        ):
            mo_hinh.fit(Xtr, ytr)
            p = mo_hinh.predict(Xte)
            y = te[target].to_numpy()
            ic = ic_cat_ngang(p, y, te["timestamp"].to_numpy())

            # Chenh lech decile: xep theo du doan, lay 10% dau tru 10% cuoi.
            # Day moi la con so co y nghia kinh te - IC chi la tuong quan.
            k = max(1, len(p) // 10)
            thu_tu = np.argsort(p)
            spread = float(y[thu_tu[-k:]].mean() - y[thu_tu[:k]].mean())

            rows.append({"cua_so": len(rows) // 2, "mo_hinh": ten, "ic": ic,
                         "decile_spread": spread, "n_train": len(tr), "n_test": len(te)})
        start += test_bars

    return pd.DataFrame(rows)


def bao_cao(df: pd.DataFrame, nhan: str) -> None:
    print("\n%s" % nhan)
    print("-" * 78)
    print("%-8s %8s %9s %9s %9s %9s" % ("Mo hinh", "Cua so", "IC TB", "IC std",
                                        "t-stat", "Decile"))
    for ten, g in df.groupby("mo_hinh"):
        ic = g["ic"].dropna()
        if len(ic) < 2:
            print("%-8s %8d   khong du cua so" % (ten, len(g)))
            continue
        t = ic.mean() / (ic.std(ddof=1) / np.sqrt(len(ic)))
        print("%-8s %8d %9.4f %9.4f %9.2f %9.4f"
              % (ten, len(ic), ic.mean(), ic.std(ddof=1), t,
                 g["decile_spread"].mean()))


def main() -> int:
    ap = argparse.ArgumentParser(description="Do information coefficient")
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--interval", default="240")
    ap.add_argument("--target", default="edge", choices=["edge", "ret_long", "ret_short"])
    ap.add_argument("--train-bars", type=int, default=2000)
    ap.add_argument("--test-bars", type=int, default=500)
    ap.add_argument("--embargo", type=int, default=60)
    ap.add_argument("--max-horizon", type=int, default=60)
    ap.add_argument("--stride", type=int, default=1,
                    help="giu moi nen thu N; dat = max-horizon de nhan khong chong lan")
    ap.add_argument("--phai-sinh", action="store_true",
                    help="them funding rate va open interest vao dac trung")
    args = ap.parse_args()

    syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    print("Nap %d ma khung %s ..." % (len(syms), args.interval))
    frames = nap(syms, args.interval)

    derivs = {}
    if args.phai_sinh:
        derivs = nap_phai_sinh(list(frames), args.interval)
        thieu = [s for s in frames if s not in derivs]
        if thieu:
            print("  bo %d ma khong co du lieu phai sinh: %s" % (len(thieu), ",".join(thieu)))
            frames = {k: v for k, v in frames.items() if k in derivs}
        print("  dung du lieu phai sinh cho %d ma" % len(derivs))

    print("Xay panel + gan nhan triple-barrier (co the mat vai phut) ...")
    panel = features.xay_panel(frames, config, max_horizon=args.max_horizon,
                              derivs=derivs or None)

    cols = features.cot_dac_trung(co_xep_hang=True, co_phai_sinh=bool(derivs))
    print("Panel: %d dong | %d dac trung | %d moc thoi gian"
          % (len(panel), len(cols), panel["timestamp"].nunique()))
    print("Muc tieu: %s | train=%d test=%d embargo=%d nen"
          % (args.target, args.train_bars, args.test_bars, args.embargo))
    print("So ma trung binh moi moc: %.1f" % panel["n_ma"].mean())

    that = chay(panel, cols, args.target, args.train_bars, args.test_bars,
                args.embargo, stride=args.stride)
    bao_cao(that, "KET QUA THAT (stride=%d)" % args.stride)

    xao = chay(panel, cols, args.target, args.train_bars, args.test_bars,
               args.embargo, xao_nhan=True, seed=1, stride=args.stride)
    bao_cao(xao, "DOI CHUNG - NHAN DA XAO TRON (phai ~0; neu duong la co RO RI)")

    os.makedirs(OUT_DIR, exist_ok=True)
    p = os.path.join(OUT_DIR, "ic_study_%s.csv" % args.target)
    that.assign(loai="that").to_csv(p, index=False)
    print("\nDa luu %s" % p)

    print("\n" + "=" * 78)
    ic_that = that[that["mo_hinh"] == "gbm"]["ic"].dropna()
    ic_xao = xao[xao["mo_hinh"] == "gbm"]["ic"].dropna()

    def t_stat(v):
        return v.mean() / (v.std(ddof=1) / np.sqrt(len(v))) if len(v) >= 2 else np.nan

    if len(ic_that) >= 2:
        t, t_xao = t_stat(ic_that), t_stat(ic_xao)
        print("DOC KET QUA: IC that = %.4f (t=%.2f) | IC xao tron = %.4f (t=%.2f)"
              % (ic_that.mean(), t, ic_xao.mean(), t_xao))
        # Ro ri phai the hien la IC DUONG MOT CACH ON DINH tren nhan xao tron.
        # So sanh gia tri trung binh voi mot nguong cung la sai: voi it cua so,
        # sai so chuan cua IC co the lon hon chinh nguong do, va phep kiem se
        # bao dong gia moi khi du lieu it di.
        if t_xao > 2.0:
            print("  CANH BAO: nhan xao tron cho IC duong on dinh -> pipeline CO RO RI.")
        elif ic_that.mean() < 0.01 or t < 2.0:
            print("  Bo dac trung hien tai gan nhu KHONG chua thong tin du bao.")
            print("  Xay policy tren no la vo vong - phai mo rong DAU VAO truoc.")
        else:
            print("  Co tin hieu do duoc. Du co so de xay policy.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
