"""
Dieu khien kho chien luoc luat - duong di tu Strategy Lab den ban live.

    python run_luat.py trang-thai                          # dang co gi trong kho
    python run_luat.py xem       --ten funding_am_sau_long  # chi tiet mot muc
    python run_luat.py thang-cap --ten ... --ly-do "..."    # len mot bac
    python run_luat.py ha-cap    --ten ... --ly-do "..."    # xuong mot bac
    python run_luat.py loai-bo   --ten ... --ly-do "..."

Duong di: ung_vien -> bong -> chu_dong. Khong nhay coc duoc.

Sau khi mot chien luoc len chu_dong, no VAN chua chay: phai them ten no vao
ENABLED_STRATEGIES trong .env roi khoi dong lai bot. Day la buoc thu ba co y -
kho luat noi "duoc phep chay", .env noi "dang chay", va hai dieu do khong nen
la mot.
"""
import argparse
import sys
import time

import config
from src.storage import Storage
from src.strategies import kho_luat


def _in_muc(muc: dict, kho: kho_luat.KhoLuat, chi_tiet: bool = False) -> None:
    ten = muc["ten"]
    tt = muc.get("trang_thai")
    them = ""
    if tt == kho_luat.BONG:
        ngay = kho.so_ngay_o_bong(ten)
        them = " | da chay bong %.1f/%d ngay" % (ngay, kho_luat.NGAY_BONG_TOI_THIEU)
        diem = kho.diem_bong(ten, Storage())
        if diem:
            them += " | %s" % diem["ly_do"]
    print("  %-28s %-10s%s" % (ten, tt, them))
    if not chi_tiet:
        return

    spec = muc.get("spec", {})
    print("    mo ta      : %s" % spec.get("mo_ta", "-"))
    print("    gia thuyet : %s" % spec.get("gia_thuyet", "-"))
    for chieu in ("long", "short"):
        if spec.get(chieu):
            dk = " VA ".join("%s %s %s" % tuple(d) for d in spec[chieu])
            print("    %-10s : %s" % (chieu, dk))
    bc = muc.get("bang_chung", {})
    if bc:
        print("    bang chung : sharpe_min=%.2f | %d lenh | nguong da hieu chinh %.2f "
              "| %d phep thu luy ke"
              % (bc.get("sharpe_min", 0), bc.get("tong_lenh", 0),
                 bc.get("nguong_da_hieu_chinh", 0), bc.get("so_phep_thu_luy_ke", 0)))
        for sym, v in (bc.get("theo_ma") or {}).items():
            print("        %-10s sharpe=%+.2f pf=%.2f lenh=%d"
                  % (sym, v.get("sharpe", 0), v.get("pf", 0), v.get("so_lenh", 0)))
    print("    lich su    :")
    for h in muc.get("lich_su", []):
        print("        %s  %s -> %s  (%s)"
              % (h["luc"], h.get("tu") or "-", h.get("den"), h.get("ly_do", "")))


def cmd_trang_thai(kho: kho_luat.KhoLuat) -> int:
    tat_ca = kho.tat_ca()
    if not tat_ca:
        print("Kho luat trong. Chay research/strategy_lab.py de sinh ung vien.")
        return 0

    for tt in kho_luat.CAC_TRANG_THAI:
        ds = [m for m in tat_ca.values() if m.get("trang_thai") == tt]
        if not ds:
            continue
        print("\n%s (%d):" % (tt.upper(), len(ds)))
        for m in sorted(ds, key=lambda x: x["ten"]):
            _in_muc(m, kho)

    chu_dong = kho.ten_chu_dong()
    if chu_dong:
        dang_bat = [s for s in chu_dong if s in config.ENABLED_STRATEGIES]
        chua_bat = [s for s in chu_dong if s not in config.ENABLED_STRATEGIES]
        print()
        if dang_bat:
            print("Dang chay that: %s" % ", ".join(dang_bat))
        if chua_bat:
            print("Duoc phep chay nhung CHUA bat: %s" % ", ".join(chua_bat))
            print("  Them vao ENABLED_STRATEGIES trong .env roi khoi dong lai bot.")

    bong = kho.ten_bong()
    if bong:
        st = Storage()
        tu = time.time() - 30 * 86400
        print("\nTin hieu che do bong 30 ngay qua:")
        for ten in bong:
            rows = st.thong_ke_shadow(ten, tu)
            if not rows:
                print("  %-28s chua co tin hieu nao" % ten)
                continue
            tom = " ".join("%s=%d" % (r["action"], r["n"]) for r in rows)
            print("  %-28s %s" % (ten, tom))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Kho chien luoc luat")
    sub = ap.add_subparsers(dest="lenh", required=True)
    sub.add_parser("trang-thai")
    for ten_lenh in ("xem", "thang-cap", "ha-cap", "loai-bo"):
        p = sub.add_parser(ten_lenh)
        p.add_argument("--ten", required=True)
        if ten_lenh != "xem":
            p.add_argument("--ly-do", default="")
        if ten_lenh == "thang-cap":
            p.add_argument("--ep", action="store_true",
                           help="bo qua dieu kien so ngay chay bong (tu chiu trach nhiem)")
    args = ap.parse_args()

    kho = kho_luat.KhoLuat()
    try:
        if args.lenh == "trang-thai":
            return cmd_trang_thai(kho)

        if args.lenh == "xem":
            muc = kho.lay(args.ten)
            if muc is None:
                print("Khong co '%s' trong kho" % args.ten)
                return 1
            _in_muc(muc, kho, chi_tiet=True)
            return 0

        if args.lenh == "thang-cap":
            muc = kho.thang_cap(args.ten, args.ly_do, ep=args.ep, storage=Storage())
            print("'%s' -> %s" % (args.ten, muc["trang_thai"]))
            if muc["trang_thai"] == kho_luat.CHU_DONG:
                print("Chien luoc nay CHUA chay. Them '%s' vao ENABLED_STRATEGIES "
                      "trong .env roi khoi dong lai bot." % args.ten)
            return 0

        if args.lenh == "ha-cap":
            muc = kho.ha_cap(args.ten, args.ly_do)
        else:
            muc = kho.loai_bo(args.ten, args.ly_do)
        print("'%s' -> %s" % (args.ten, muc["trang_thai"]))
        if args.ten in config.ENABLED_STRATEGIES:
            print("CANH BAO: '%s' van con trong ENABLED_STRATEGIES cua .env - "
                  "bo ra roi khoi dong lai bot, neu khong no van chay." % args.ten)
        return 0

    except kho_luat.KhoLuatLoi as e:
        print("Tu choi: %s" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
