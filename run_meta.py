"""
Dieu khien bo loc meta-label - lop hoc "tin hieu nay co dang nghe khong".

    python run_meta.py hoc          # huan luyen mot bo loc + cham cong
    python run_meta.py quet         # kiem do ON DINH tren nhieu cua so + seed
    python run_meta.py trang-thai   # champion, lich su phien ban
    python run_meta.py the          # doc the bo loc
    python run_meta.py ha-cap --ly-do "..."

`quet` la lenh nen chay TRUOC khi tin bat ky ket qua nao cua `hoc`. Mot lan
`hoc` cham diem tren mot cua so kiem dinh duy nhat, tuc mot doan thi truong duy
nhat; `quet` chay lai tren nhieu cua so va nhieu seed de thay phan tan. Neu loi
the chi xuat hien o vai cua so thi cai dang nhin la phuong sai, khong phai
ky nang - va trung binh dep den may cung khong doi duoc dieu do.
"""
import argparse
import json
import logging
import os
import sys

import config
from src import meta_continual


def _ma(chuoi: str):
    if chuoi:
        return [s.strip().upper() for s in chuoi.split(",") if s.strip()]
    duoi = "_%s.csv" % config.KLINE_INTERVAL
    tep = [f for f in os.listdir(config.CACHE_DIR)
           if f.endswith(duoi) and "_deriv_" not in f]
    return sorted(f[:-len(duoi)] for f in tep)


def _chien_luoc(chuoi: str):
    return ([s.strip() for s in chuoi.split(",") if s.strip()] if chuoi
            else list(config.META_CHIEN_LUOC))


def lenh_hoc(args) -> int:
    syms = _ma(args.symbols)
    ten = _chien_luoc(args.chien_luoc)
    print("Hoc bo loc cho: %s | %d ma khung %s"
          % (", ".join(ten), len(syms), args.interval or config.KLINE_INTERVAL))

    kq = meta_continual.chay_mot_vong(
        syms, args.interval, config, max_horizon=args.max_horizon, seed=args.seed,
        ten_chien_luoc=ten, dung_phai_sinh=not args.khong_phai_sinh,
        bo_qua_cong=args.ep_thang_cap)

    print("\n" + "=" * 78)
    if "cong" in kq:
        print("CONG THANG CAP")
        print("-" * 78)
        print("  %-22s %-14s %-22s %s" % ("Dieu kien", "Gia tri", "Yeu cau", "Ket qua"))
        print(kq["cong"].in_ra())
    print("=" * 78)
    print("Phien ban : %s" % kq.get("phien_ban", "(khong tao)"))
    print("Trang thai: %s" % kq["trang_thai"].upper().replace("_", " "))
    if kq.get("thong_diep"):
        print("  %s" % kq["thong_diep"])
    if kq["trang_thai"] == "tu_choi":
        print("\nDay thuong la ket qua DUNG. Truoc khi sua bat ky nguong nao, chay")
        print("  python run_meta.py quet")
        print("de xem loi the co on dinh qua nhieu cua so khong. Neu no khong on")
        print("dinh thi ha nguong chi lam bo loc de dau hon, khong lam no dung hon.")
    return 0


def lenh_quet(args) -> int:
    syms = _ma(args.symbols)
    seeds = [int(x) for x in args.seeds.split(",") if x.strip()]
    print("Quet %d cua so x %d seed tren %d ma ..."
          % (args.so_cua_so, len(seeds), len(syms)))

    d = meta_continual.quet_walkforward(
        syms, args.interval, config, max_horizon=args.max_horizon,
        so_cua_so=args.so_cua_so, val_bars=args.val_bars, cac_seed=seeds,
        ten_chien_luoc=_chien_luoc(args.chien_luoc),
        dung_phai_sinh=not args.khong_phai_sinh)

    if d.empty:
        print("Khong chay duoc cua so nao.")
        return 1
    ok = d[d["loi"].isna()] if "loi" in d.columns else d
    if ok.empty:
        print("Moi cua so deu loi:")
        for _, r in d.iterrows():
            print("  cua so %s: %s" % (r.get("cua_so"), r.get("loi")))
        return 1

    print("\n%-7s %-5s %8s %11s %12s %7s %7s"
          % ("cua so", "seed", "giu", "ky vong", "khong loc", "PF", "AUC"))
    print("-" * 66)
    for _, r in ok.iterrows():
        print("%-7d %-5d %8.3f %+11.5f %+12.5f %7.2f %7.3f"
              % (r.cua_so, r.seed, r.ty_le_giu, r.ky_vong,
                 r.ky_vong_khong_loc, r.pf, r.auc))

    n_tot = int((ok["cai_thien"] > 0).sum())
    print("-" * 66)
    print("Cua so co cai thien duong : %d/%d" % (n_tot, len(ok)))
    print("Cai thien trung vi        : %+.5f" % ok["cai_thien"].median())
    print("AUC trung binh            : %.3f  (0.5 = khong biet gi)" % ok["auc"].mean())

    theo_cua_so = ok.groupby("cua_so")["auc"].mean()
    so_khong_ky_nang = int((theo_cua_so < 0.52).sum())
    print("\nDOC KET QUA")
    print("-" * 66)
    if n_tot < len(ok) * 0.7:
        print("  Loi the KHONG on dinh: chi %d/%d lan chay co cai thien duong."
              % (n_tot, len(ok)))
    if so_khong_ky_nang:
        print("  %d/%d cua so co AUC < 0.52 - o nhung doan do mo hinh khong biet gi,"
              % (so_khong_ky_nang, len(theo_cua_so)))
        print("  va mot bo loc khong biet gi van dang CHAN lenh that.")
    if n_tot >= len(ok) * 0.7 and not so_khong_ky_nang:
        print("  Loi the xuat hien deu qua cac cua so. Day la co so de chay bong.")
    return 0


def lenh_trang_thai(args) -> int:
    kho = meta_continual.KhoMeta()
    champ = kho.champion_hien_tai()
    ds = kho.danh_sach()
    print("Thu muc      : %s" % kho.thu_muc)
    print("Champion     : %s" % (champ or "(khong co - tin hieu di tiep nguyen ven)"))
    print("Chien luoc   : %s" % ", ".join(config.META_CHIEN_LUOC))

    print("\n%d phien ban da luu:" % len(ds))
    print("  %-26s %7s %9s %10s %7s %s"
          % ("phien ban", "AUC", "ky vong", "khong loc", "giu", "cong"))
    for pb in ds[-15:]:
        m = kho.doc_meta(pb)
        cs = m.get("chi_so", {})
        print("  %-26s %7s %9s %10s %7s %s%s"
              % (pb,
                 meta_continual._so(cs.get("auc"), "%.3f"),
                 meta_continual._so(cs.get("ky_vong"), "%+.4f"),
                 meta_continual._so(cs.get("ky_vong_khong_loc"), "%+.4f"),
                 meta_continual._so(cs.get("ty_le_giu"), "%.3f"),
                 "DAT" if m.get("cong_dat") else "truot",
                 "  <- champion" if pb == champ else ""))

    sk = kho.su_kien(10)
    if sk:
        print("\nSu kien gan day:")
        for e in sk:
            print("  %s  %-16s %-26s %s" % (e.get("thoi_diem"), e.get("loai"),
                                            e.get("phien_ban"), e.get("ly_do", "")[:50]))
    return 0


def lenh_the(args) -> int:
    kho = meta_continual.KhoMeta()
    pb = args.phien_ban or kho.champion_hien_tai() or (kho.danh_sach() or [None])[-1]
    if not pb:
        print("Chua co phien ban nao.")
        return 1
    p = os.path.join(kho.thu_muc, pb, "the_mo_hinh.md")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            print(f.read())
    else:
        print(json.dumps(kho.doc_meta(pb), ensure_ascii=False, indent=2)[:6000])
    return 0


def lenh_ha_cap(args) -> int:
    moi = meta_continual.KhoMeta().ha_cap(args.ly_do or "ha cap thu cong")
    print("Champion moi: %s" % (moi or "(khong co - tin hieu di tiep nguyen ven)"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Bo loc meta-label")
    sub = ap.add_subparsers(dest="lenh", required=True)

    def chung(p):
        p.add_argument("--symbols", default="", help="mac dinh: moi ma co cache")
        p.add_argument("--interval", default=None)
        p.add_argument("--max-horizon", type=int, default=60)
        p.add_argument("--chien-luoc", default="", help="mac dinh: META_CHIEN_LUOC")
        p.add_argument("--khong-phai-sinh", action="store_true")

    p = sub.add_parser("hoc", help="huan luyen mot bo loc va cham cong")
    chung(p)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--ep-thang-cap", action="store_true",
                   help="thang cap DU khong qua cong (chi de thu duong ong)")
    p.set_defaults(ham=lenh_hoc)

    p = sub.add_parser("quet", help="kiem do on dinh tren nhieu cua so + seed")
    chung(p)
    p.add_argument("--so-cua-so", type=int, default=6)
    p.add_argument("--val-bars", type=int, default=700)
    p.add_argument("--seeds", default="0,1,2")
    p.set_defaults(ham=lenh_quet)

    p = sub.add_parser("trang-thai", help="champion + lich su phien ban")
    p.set_defaults(ham=lenh_trang_thai)

    p = sub.add_parser("the", help="doc the bo loc")
    p.add_argument("--phien-ban", default=None)
    p.set_defaults(ham=lenh_the)

    p = sub.add_parser("ha-cap", help="lui champion mot buoc")
    p.add_argument("--ly-do", default="")
    p.set_defaults(ham=lenh_ha_cap)

    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])
    return args.ham(args)


if __name__ == "__main__":
    sys.exit(main())
