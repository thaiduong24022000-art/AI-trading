"""
Dieu khien vong hoc lien tuc cua AI policy.

    python run_policy.py hoc      --symbols BTCUSDT,ETHUSDT,...   # mot vong hoc
    python run_policy.py trang-thai                                # dang co gi
    python run_policy.py the      --phien-ban v2026...             # doc the mo hinh
    python run_policy.py theo-doi                                  # cham champion
    python run_policy.py ha-cap   --ly-do "..."                    # lui mot buoc
    python run_policy.py thang-cap --phien-ban v2026... --ly-do "..."

`hoc` la lenh chinh. No huan luyen mot challenger, cham diem tren khoi kiem dinh
gan nhat, va CHI thang cap khi qua toan bo cong thong ke. Ket qua thuong gap
nhat - va dung nhat khi du lieu chua co tin hieu - la "tu choi".

Muon lap lich chay hang tuan tren Windows:
    schtasks /create /tn "AITrade hoc policy" /sc weekly /d SUN /st 03:00 ^
      /tr "C:\\Users\\Admin\\Desktop\\AITrade\\.venv\\Scripts\\python.exe ^
           C:\\Users\\Admin\\Desktop\\AITrade\\run_policy.py hoc --symbols ..."
"""
import argparse
import json
import logging
import os
import sys

import config
from src import continual, model_store
from src.storage import Storage

DINH_DANG_LOG = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"


def _log(muc=logging.INFO) -> None:
    logging.basicConfig(level=muc, format=DINH_DANG_LOG,
                        handlers=[logging.StreamHandler(sys.stdout)])


def _ma(chuoi: str):
    if chuoi:
        return [s.strip().upper() for s in chuoi.split(",") if s.strip()]
    # Mac dinh: moi ma co cache khung dang chay. Xep hang cat ngang can be rong,
    # nen lay tat ca chu khong chi 3 ma dang giao dich.
    tep = [f for f in os.listdir(config.CACHE_DIR)
           if f.endswith("_%s.csv" % config.KLINE_INTERVAL) and "_deriv_" not in f]
    return sorted(f.rsplit("_", 1)[0] for f in tep)


def lenh_hoc(args) -> int:
    syms = _ma(args.symbols)
    print("Hoc tren %d ma khung %s: %s" % (len(syms), args.interval or config.KLINE_INTERVAL,
                                           ", ".join(syms[:8]) + ("..." if len(syms) > 8 else "")))
    if len(syms) < config.POLICY_MIN_MA:
        print("\nCANH BAO: chi co %d ma, POLICY_MIN_MA = %d." % (len(syms), config.POLICY_MIN_MA))
        print("Dac trung xep hang cat ngang can it nhat %d ma tai moi moc thoi gian"
              % config.POLICY_MIN_MA)
        print("moi co nghia. Duoi muc do policy se tu choi co y kien khi chay that.")

    kq = continual.chay_mot_vong(
        syms, args.interval, config, dung_phai_sinh=not args.khong_phai_sinh,
        max_horizon=args.max_horizon, seed=args.seed, bo_qua_cong=args.ep_thang_cap)

    print("\n" + "=" * 78)
    if "cong" in kq:
        print("CONG THANG CAP")
        print("-" * 78)
        print("  %-22s %-14s %-22s %s" % ("Dieu kien", "Gia tri", "Yeu cau", "Ket qua"))
        print(kq["cong"].in_ra())
    print("=" * 78)
    print("Phien ban: %s" % kq.get("phien_ban", "(khong tao)"))
    print("Trang thai: %s" % kq["trang_thai"].upper().replace("_", " "))
    if kq.get("thong_diep"):
        print("  %s" % kq["thong_diep"])

    if kq["trang_thai"] == "tu_choi":
        print("\nDay thuong la ket qua DUNG, khong phai loi. Mot vong hoc lien tuc")
        print("lan nao cung thang cap la mot vong duoi theo nhieu. Champion cu giu nguyen.")
    elif kq["trang_thai"] == "nghi_ro_ri":
        print("\nDUNG LAI VA KIEM TRA: mo hinh huan luyen tren NHAN DA XAO TRON van")
        print("dat diem cao. Dieu do nghia la co dac trung nhin thay tuong lai o dau do")
        print("trong duong ong. Moi so lieu khac trong lan chay nay deu khong dung duoc.")
    elif kq["trang_thai"] == "da_thang_cap":
        print("\nDa thang cap. Buoc tiep theo KHONG phai la chay tien that:")
        print("  1. dat POLICY_MODE=shadow trong .env va de no chay song song vai tuan")
        print("  2. `python run_policy.py theo-doi` de so ket qua that voi kiem dinh")
        print("  3. chi khi ho so truc tuyen khop voi kiem dinh moi tinh den filter/active")
    return 0


def lenh_trang_thai(args) -> int:
    kho = model_store.KhoModel()
    ds = kho.danh_sach()
    champ = kho.champion_hien_tai()
    tt = kho.thong_tin_champion()

    print("Thu muc mo hinh : %s" % kho.thu_muc)
    print("Che do policy   : %s" % config.POLICY_MODE)
    print("Champion        : %s" % (champ or "(khong co - chay thuan chien luoc luat)"))
    if tt.get("ly_do"):
        print("  ly do        : %s" % tt["ly_do"])
    if tt.get("truoc_do"):
        print("  duong lui ve : %s" % tt["truoc_do"])

    print("\n%d phien ban da luu:" % len(ds))
    print("  %-26s %-7s %-7s %-9s %-9s %s" % ("phien ban", "AUC", "IC", "ky vong", "so lenh", "cong"))
    for pb in ds[-15:]:
        m = kho.doc_meta(pb)
        cs = m.get("chi_so", {})
        print("  %-26s %-7s %-7s %-9s %-9s %s%s"
              % (pb,
                 continual._so(cs.get("auc_tb"), "%.3f"),
                 continual._so(cs.get("ic"), "%.3f"),
                 continual._so(cs.get("loi_nhuan_tb"), "%.4f"),
                 cs.get("so_lenh", "-"),
                 "DAT" if m.get("cong_dat") else "truot",
                 "  <- champion" if pb == champ else ""))

    sk = kho.su_kien(12)
    if sk:
        print("\nSu kien gan day:")
        for e in sk:
            print("  %s  %-18s %-26s %s" % (e.get("thoi_diem"), e.get("loai"),
                                            e.get("phien_ban"), e.get("ly_do", "")[:60]))

    if champ:
        st = Storage()
        tk = st.thong_ke_policy(champ)
        print("\nKet qua THAT cua champion (tu policy_predictions):")
        if tk.get("so_lenh", 0) == 0:
            print("  chua co lenh nao co ket qua. Can chay o che do shadow mot thoi gian,")
            print("  roi `python run_policy.py theo-doi` de dien ket qua.")
        else:
            print("  %d lenh | ky vong %.4f/lenh | thang %.1f%% | PF %.2f"
                  % (tk["so_lenh"], tk["loi_nhuan_tb"], tk["ty_le_thang"] * 100,
                     tk["profit_factor"]))
    return 0


def lenh_the(args) -> int:
    kho = model_store.KhoModel()
    pb = args.phien_ban or kho.champion_hien_tai()
    if not pb:
        print("Khong co phien ban nao de xem.")
        return 1
    p = os.path.join(kho.thu_muc, pb, "the_mo_hinh.md")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            print(f.read())
    else:
        print(json.dumps(kho.doc_meta(pb), ensure_ascii=False, indent=2)[:6000])
    return 0


def lenh_theo_doi(args) -> int:
    st = Storage()
    syms = _ma(args.symbols)
    so = continual.dong_ket_qua(st, syms, args.interval or config.KLINE_INTERVAL, config,
                                max_horizon=args.max_horizon)
    print("Da dien ket qua that cho %d du doan." % so)

    kq = continual.theo_doi_champion(st, model_store.KhoModel(), config)
    print("Trang thai: %s" % kq["trang_thai"].upper().replace("_", " "))
    if kq["trang_thai"] == "chua_du_du_lieu":
        print("  moi co %d/%d lenh co ket qua." % (kq["so_lenh"], kq["can"]))
    elif "thuc_te" in kq:
        t, k = kq["thuc_te"], kq["kiem_dinh"]
        print("  thuc te  : %d lenh | ky vong %.4f | thang %.1f%% | PF %.2f"
              % (t["so_lenh"], t["loi_nhuan_tb"], t["ty_le_thang"] * 100, t["profit_factor"]))
        print("  kiem dinh: ky vong %s | PF %s"
              % (continual._so(k.get("loi_nhuan_tb")), continual._so(k.get("profit_factor"), "%.2f")))
        if kq["trang_thai"] == "da_ha_cap":
            print("  DA HA CAP -> champion moi: %s" % (kq.get("champion_moi") or "(khong co)"))
    return 0


def lenh_thang_cap(args) -> int:
    kho = model_store.KhoModel()
    if not args.phien_ban:
        print("Can --phien-ban")
        return 1
    m = kho.doc_meta(args.phien_ban)
    if not m.get("cong_dat"):
        print("CANH BAO: phien ban nay KHONG qua cong thong ke luc huan luyen.")
        if not args.toi_chac_chan:
            print("Them --toi-chac-chan neu that su muon thang cap no.")
            return 1
    kho.thang_cap(args.phien_ban, args.ly_do or "thang cap thu cong")
    print("Da thang cap %s" % args.phien_ban)
    return 0


def lenh_ha_cap(args) -> int:
    moi = model_store.KhoModel().ha_cap(args.ly_do or "ha cap thu cong")
    print("Champion moi: %s" % (moi or "(khong co - chay thuan chien luoc luat)"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Vong hoc lien tuc cua AI policy")
    sub = ap.add_subparsers(dest="lenh", required=True)

    def chung(p):
        p.add_argument("--symbols", default="", help="mac dinh: moi ma co cache")
        p.add_argument("--interval", default=None)
        p.add_argument("--max-horizon", type=int, default=60)

    p = sub.add_parser("hoc", help="huan luyen mot challenger va cham cong")
    chung(p)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--khong-phai-sinh", action="store_true",
                   help="bo funding/open interest khoi dac trung")
    p.add_argument("--ep-thang-cap", action="store_true",
                   help="thang cap DU khong qua cong (chi de thu duong ong)")
    p.set_defaults(ham=lenh_hoc)

    p = sub.add_parser("trang-thai", help="champion, lich su phien ban, ket qua that")
    p.set_defaults(ham=lenh_trang_thai)

    p = sub.add_parser("the", help="doc the mo hinh")
    p.add_argument("--phien-ban", default=None)
    p.set_defaults(ham=lenh_the)

    p = sub.add_parser("theo-doi", help="dien ket qua that + kiem tra ha cap")
    chung(p)
    p.set_defaults(ham=lenh_theo_doi)

    p = sub.add_parser("thang-cap", help="thang cap thu cong")
    p.add_argument("--phien-ban", required=True)
    p.add_argument("--ly-do", default="")
    p.add_argument("--toi-chac-chan", action="store_true")
    p.set_defaults(ham=lenh_thang_cap)

    p = sub.add_parser("ha-cap", help="lui champion ve phien ban truoc")
    p.add_argument("--ly-do", default="")
    p.set_defaults(ham=lenh_ha_cap)

    args = ap.parse_args()
    _log()
    return args.ham(args)


if __name__ == "__main__":
    sys.exit(main())
