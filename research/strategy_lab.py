"""
Strategy Lab - Nang cap 5: LLM sinh gia thuyet, MAY kiem dinh.

    python -m research.strategy_lab kiem-dinh --specs research/gia_thuyet.json
    python -m research.strategy_lab trang-thai
    python -m research.strategy_lab sinh --so-luong 10      # can ANTHROPIC_API_KEY

VAN DE TRUNG TAM CUA CA FILE NAY - va la ly do no dai hon ban trong kien truc:

Thu 20 gia thuyet roi chon cai co Sharpe cao nhat KHONG PHAI la nghien cuu.
Do la mot may sinh duong tinh gia. Ngay ca khi ca 20 y tuong deu vo dung, cai
"tot nhat" trong 20 van se trong rat dep - vi ta dang do CAI CUC DAI cua nhieu
ngau nhien chu khong do ky nang.

Chinh file research/quet_hang_rao.py trong du an nay da canh bao dung dieu do:
"thu 18 cau hinh roi chon cai dep nhat LA MOT DANG TIM KIEM, va no overfit y
het viec quet tham so". Mot Strategy Lab khong hieu chinh cho so phep thu se
lap lai sai lam do, chi khac la o quy mo tu dong hoa.

Vi vay cong o day CHAT HON cong walk-forward thong thuong, theo hai cach:

  1. NGUONG SHARPE TANG THEO SO PHEP THU.
     Ky vong cua cuc dai N bien chuan (Bailey & Lopez de Prado):
        E[max_N] ~ (1-g)*Z(1 - 1/N) + g*Z(1 - 1/(N*e)),  g = hang so Euler
     Nhan voi sai so chuan cua chinh uoc luong Sharpe se ra nguong ma mot
     chien luoc VO DUNG van dat duoc nho may man. Vuot cong co ban chua du -
     phai vuot ca nguong nay.

  2. BO DEM PHEP THU DUOC LUU LAI GIUA CAC LAN CHAY.
     Neu bo dem reset moi lan chay, ta chi viec chay lab 10 lan voi 2 y tuong
     moi lan de vo hieu hoa toan bo hieu chinh - va se lam vay ma khong he
     nhan ra minh dang lam vay. Bo dem nam trong data/strategy_lab_trials.json
     va CHI TANG.

Ket qua DUNG cua hau het cac lan chay la "khong y tuong nao qua cong". Do la
he thong dang lam viec, khong phai he thong hong.
"""
import argparse
import json
import math
import os
import sys
import time
from typing import Dict, List, Optional

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from backtest import metrics, walkforward
from src import datafeed, indicators
from src.strategies import kho_luat, rule_spec

DUONG_DAN_BO_DEM = os.path.join(config.BASE_DIR, "data", "strategy_lab_trials.json")
DUONG_DAN_KET_QUA = os.path.join(config.BASE_DIR, "data", "reports", "strategy_lab.json")

EULER = 0.5772156649015329


# ==========================================================
# Hieu chinh nhieu phep thu
# ==========================================================
def ky_vong_cuc_dai_chuan(n_thu: int) -> float:
    """E[max cua n_thu bien chuan doc lap] - xap xi Bailey & Lopez de Prado.

    n_thu = 1 tra ve 0: chua tim kiem gi thi khong co gi de hieu chinh.
    """
    if n_thu <= 1:
        return 0.0
    from scipy.stats import norm
    a = norm.ppf(1.0 - 1.0 / n_thu)
    b = norm.ppf(1.0 - 1.0 / (n_thu * math.e))
    return (1.0 - EULER) * a + EULER * b


def nguong_sharpe(n_thu: int, so_quan_sat: int, bars_per_year: int,
                  sharpe_co_ban: float) -> float:
    """Nguong Sharpe da hieu chinh cho so phep thu da thuc hien.

    Sai so chuan cua Sharpe nam theo don vi nam ~ sqrt(bars_per_year/n). Nhan
    voi ky vong cuc dai se ra muc ma mot chien luoc KHONG CO KY NANG van dat
    toi duoc nho tim kiem qua nhieu lan.
    """
    if so_quan_sat <= 1:
        return float("inf")
    se = math.sqrt(bars_per_year / float(so_quan_sat))
    return max(sharpe_co_ban, ky_vong_cuc_dai_chuan(n_thu) * se)


# ==========================================================
# Bo dem phep thu - chi tang, khong bao gio reset
# ==========================================================
def doc_bo_dem() -> Dict:
    if not os.path.exists(DUONG_DAN_BO_DEM):
        return {"so_lan_thu": 0, "lich_su": []}
    try:
        with open(DUONG_DAN_BO_DEM, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # File hong thi KHONG duoc coi la "chua thu lan nao" - do la huong sai
        # nguy hiem (no noi long cong). Bao loi de nguoi xu ly.
        raise RuntimeError("Bo dem phep thu hong: %s. Sua hoac xoa co y thuc - "
                           "xoa lam mat lich su tim kiem va noi long cong."
                           % DUONG_DAN_BO_DEM)


def ghi_bo_dem(bo_dem: Dict, them: int, ghi_chu: str) -> Dict:
    bo_dem["so_lan_thu"] = int(bo_dem.get("so_lan_thu", 0)) + int(them)
    bo_dem.setdefault("lich_su", []).append({
        "thoi_diem": time.strftime("%Y-%m-%d %H:%M:%S"),
        "them": them, "tong": bo_dem["so_lan_thu"], "ghi_chu": ghi_chu,
    })
    os.makedirs(os.path.dirname(DUONG_DAN_BO_DEM), exist_ok=True)
    with open(DUONG_DAN_BO_DEM, "w", encoding="utf-8") as f:
        json.dump(bo_dem, f, ensure_ascii=False, indent=2)
    return bo_dem


# ==========================================================
# Kiem dinh
# ==========================================================
def lam_sach(x):
    """Doi inf/nan thanh None truoc khi ghi ra JSON.

    profit_factor = inf khi mot cua so khong co lenh thua nao - chuyen binh
    thuong. Nhung json.dump cua Python ghi no thanh `Infinity`, ma do KHONG
    PHAI JSON hop le: moi bo doc nghiem ngat (trinh duyet, jq, mot ngon ngu
    khac) se vo khi gap. Python doc lai duoc file cua chinh no nen loi kieu nay
    an rat lau, cho den luc mot cong cu khac cham vao.
    """
    if isinstance(x, dict):
        return {k: lam_sach(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [lam_sach(v) for v in x]
    if isinstance(x, float) and (x != x or x in (float("inf"), float("-inf"))):
        return None
    return x


def nap_gia(symbol: str, interval: str) -> Optional[pd.DataFrame]:
    """Nen + chi bao, cong funding/open_interest neu da tai ve.

    File deriv da duoc ghep LUI tu luc tai (merge_asof backward trong
    download_derivatives.py), nen moi dong chi chua gia tri cong bo TRUOC khi
    nen do mo. Ghep lai o day theo timestamp giu nguyen tinh chat do.
    """
    df = datafeed.load_cache(symbol, interval)
    if df is None or len(df) < 1000:
        return None
    df = indicators.add_indicators(df)

    from research.download_derivatives import duong_dan
    p = duong_dan(symbol, interval)
    if os.path.exists(p):
        d = pd.read_csv(p)
        if {"timestamp", "funding", "open_interest"} <= set(d.columns):
            df["timestamp"] = df["timestamp"].astype("int64")
            d["timestamp"] = d["timestamp"].astype("int64")
            df = df.merge(d[["timestamp", "funding", "open_interest"]],
                          on="timestamp", how="left")
            # Muc TUYET DOI cua OI khong so sanh duoc giua cac ma (BTC va SOL
            # khac nhau hang bac), va muc tuyet doi cua funding thi khong noi
            # len no dang cao hay thap so voi chinh no. Hai cot dan xuat duoi
            # day moi la thu mot luat co the dung. Ca hai deu NHAN QUA:
            # pct_change va rolling chi nhin ve qua khu.
            oi = df["open_interest"]
            df["oi_chg_24"] = oi.pct_change(24)
            f = df["funding"]
            sd = f.rolling(60, min_periods=30).std().replace(0.0, float("nan"))
            df["funding_z"] = (f - f.rolling(60, min_periods=30).mean()) / sd
    return df


def kiem_dinh_mot(spec: Dict, khung_gia: Dict[str, pd.DataFrame], n_thu: int,
                  bars_per_year: int, cfg=config) -> Dict:
    """Walk-forward mot gia thuyet tren nhieu ma. Tra ve ban ghi ket qua.

    Chay tren NHIEU MA co chu dich: mot bien do chi xuat hien tren mot ma la
    may man; xuat hien tren nhieu ma thi co the la cau truc that. Nhung nho
    rang BTC/ETH/SOL tuong quan 0.85-0.9 nen day KHONG phai nhieu phep thu
    doc lap - dung dem chung nhu bang chung rieng biet.
    """
    try:
        cls = rule_spec.bien_dich(spec)
    except rule_spec.SpecKhongHopLe as e:
        return {"ten": spec.get("ten", "?"), "hop_le": False, "ly_do": str(e)}

    theo_ma, tong_lenh = {}, 0
    sharpe_min = float("inf")
    oos_moi_ma = []
    for sym, df in khung_gia.items():
        bc = walkforward.walk_forward(df, cls, cfg=cfg, param_grid={},
                                      bars_per_year=bars_per_year)
        m = bc.oos_metrics
        theo_ma[sym] = {"sharpe": m.sharpe, "pf": m.profit_factor,
                        "so_lenh": m.num_trades, "dd": m.max_drawdown,
                        "qua_cong_co_ban": bc.gates_passed}
        tong_lenh += m.num_trades
        sharpe_min = min(sharpe_min, m.sharpe)
        oos_moi_ma.append(sum(w.test_end - w.train_end for w in bc.windows))

    # SO QUAN SAT DUNG DE HIEU CHINH - hai lua chon o day deu co the sai theo
    # huong NGUY HIEM (nguong thap hon thuc te can), nen ca hai deu chon phia
    # bao thu:
    #
    #   1. Chi dem nen OUT-OF-SAMPLE, khong dem toan bo lich su. Sharpe dang
    #      duoc cham la Sharpe OOS, nen sai so chuan cua no phai tinh tren so
    #      quan sat OOS. Dem ca vung train se thoi phong n len vai lan, lam sai
    #      so chuan nho di va nguong tut xuong.
    #
    #   2. Lay ma IT nen nhat chu khong cong don ca ba ma. Vi dai luong duoc
    #      cham la sharpe_min (Sharpe cua ma te nhat), sai so chuan phai la cua
    #      MOT ma. Va du co muon cong don thi cung khong duoc: BTC/ETH/SOL
    #      tuong quan 0.85-0.9, cong nen cua ba ma lai khong cho ra ba lan
    #      luong thong tin doc lap.
    so_quan_sat = min(oos_moi_ma) if oos_moi_ma else 0
    nguong = nguong_sharpe(n_thu, so_quan_sat, bars_per_year, cfg.GATE_MIN_SHARPE)

    # Dung SHARPE THAP NHAT trong cac ma, khong dung trung binh: mot y tuong
    # chi song nho mot ma keo len la y tuong chua chung minh duoc gi.
    qua = (sharpe_min >= nguong
           and tong_lenh >= cfg.GATE_MIN_TRADES
           and all(v["pf"] >= cfg.GATE_MIN_PROFIT_FACTOR for v in theo_ma.values()))

    return lam_sach({
        "ten": spec["ten"], "hop_le": True, "mo_ta": spec.get("mo_ta", ""),
        "gia_thuyet": spec.get("gia_thuyet", ""),
        "theo_ma": theo_ma, "sharpe_min": sharpe_min, "tong_lenh": tong_lenh,
        "nguong_da_hieu_chinh": nguong, "so_phep_thu_luy_ke": n_thu,
        "qua_cong": qua,
    })


def chay(specs: List[Dict], symbols: List[str], interval: str, cfg=config) -> Dict:
    khung_gia = {}
    for sym in symbols:
        df = nap_gia(sym, interval)
        if df is None:
            print("  bo qua %s: chua co cache gia du dai" % sym)
            continue
        khung_gia[sym] = df
    if not khung_gia:
        raise RuntimeError("Khong co ma nao co du du lieu. Chay run_backtest.py "
                           "download hoac research.download_universe truoc.")

    bars_per_year = metrics.bars_per_year(interval)
    bo_dem = doc_bo_dem()
    # Dem TRUOC khi kiem dinh: n phep thu nay da xay ra roi, ke ca neu ta dung
    # giua chung. Dem sau se tao dong co am tham cho viec "chay thu roi bo".
    n_truoc = int(bo_dem.get("so_lan_thu", 0))
    bo_dem = ghi_bo_dem(bo_dem, len(specs), "kiem dinh %d gia thuyet" % len(specs))
    n_thu = bo_dem["so_lan_thu"]

    print("Da thu %d gia thuyet truoc day, lan nay them %d -> tong %d"
          % (n_truoc, len(specs), n_thu))
    print("Ma: %s | khung %s | %d nen/nam\n"
          % (",".join(khung_gia), interval, bars_per_year))

    ket_qua = []
    for i, sp in enumerate(specs, 1):
        ten = sp.get("ten", "?") if isinstance(sp, dict) else "?"
        print("%2d/%d  %-28s " % (i, len(specs), ten), end="", flush=True)
        kq = kiem_dinh_mot(sp, khung_gia, n_thu, bars_per_year, cfg)
        ket_qua.append(kq)
        if not kq.get("hop_le"):
            print("SPEC HONG: %s" % kq["ly_do"][:60])
        else:
            print("sharpe_min=%+.2f (can >= %.2f) | %d lenh | %s"
                  % (kq["sharpe_min"], kq["nguong_da_hieu_chinh"], kq["tong_lenh"],
                     "QUA CONG" if kq["qua_cong"] else "truot"))

    qua = [k for k in ket_qua if k.get("qua_cong")]
    bao_cao = {"thoi_diem": time.strftime("%Y-%m-%d %H:%M:%S"),
               "so_phep_thu_luy_ke": n_thu, "khung": interval,
               "ma": list(khung_gia), "ket_qua": ket_qua,
               "so_qua_cong": len(qua)}
    os.makedirs(os.path.dirname(DUONG_DAN_KET_QUA), exist_ok=True)
    with open(DUONG_DAN_KET_QUA, "w", encoding="utf-8") as f:
        json.dump(lam_sach(bao_cao), f, ensure_ascii=False, indent=2, default=float,
                  allow_nan=False)

    print("\n%d/%d gia thuyet qua cong. Bao cao: %s"
          % (len(qua), len(specs), DUONG_DAN_KET_QUA))
    if not qua:
        print("Khong y tuong nao qua cong - day la ket qua THUONG GAP va dung.\n"
              "Cong da chat hon vi da thu %d gia thuyet luy ke." % n_thu)
        return bao_cao

    # Ghi vao kho o trang thai UNG_VIEN - tuc la chua chay o dau ca. Buoc len
    # che do bong la mot lenh rieng do NGUOI go, khong tu dong.
    kho = kho_luat.KhoLuat()
    theo_ten = {sp["ten"]: sp for sp in specs if isinstance(sp, dict) and "ten" in sp}
    for k in qua:
        try:
            kho.them_ung_vien(theo_ten[k["ten"]], k,
                              ghi_chu="qua cong lab voi %d phep thu luy ke" % n_thu)
        except kho_luat.KhoLuatLoi as e:
            print("  (khong ghi vao kho duoc '%s': %s)" % (k["ten"], e))

    print("\nLUU Y: qua cong o day KHONG phai giay phep chay tien that.\n"
          "Cac y tuong tren da vao kho o trang thai 'ung_vien'. Buoc tiep theo\n"
          "la cho chay che do BONG vai tuan - xem: python run_luat.py trang-thai")
    for k in qua:
        print("  - %s: %s" % (k["ten"], k.get("mo_ta", "")))
    return bao_cao


# ==========================================================
# Sinh gia thuyet bang LLM (tuy chon)
# ==========================================================
LOI_NHAC = """Ban la nha nghien cuu dinh luong. Hay de xuat %d gia thuyet giao dich
crypto khung %s, moi gia thuyet duoi dang JSON theo DUNG luoc do sau.

Cot duoc phep dung: %s
Toan tu duoc phep: %s
Toi da %d dieu kien moi chieu.

Dinh dang tra ve - CHI tra ve mot mang JSON, khong giai thich gi them:
[
  {
    "ten": "ten_ngan_gon_chu_thuong",
    "mo_ta": "mot cau mo ta luat",
    "gia_thuyet": "vi sao ban nghi no co bien do - co che thi truong nao",
    "long": [["rsi", "<", 30], ["close", ">", "ema_trend"]],
    "short": [["rsi", ">", 70]]
  }
]

Boi canh quan trong:
- Cac chien luoc hien co: %s
- Kiem dinh truoc day cho thay dac trung OHLCV thuan co IC ~ 0 tren 23 ma.
  Nhung y tuong chi to hop lai RSI/EMA/MACD theo cach thong thuong gan nhu
  chac chan da bi arbitrage het. Hay uu tien co che it nguoi khai thac.
- Phi mot vong ~%.2f%%, nen y tuong nham bien do nho hon muc do se lo sau phi.
- Y tuong cua ban se bi walk-forward tren nhieu ma voi cong thong ke da hieu
  chinh cho so phep thu. Duoc phep sai - dung co gang lam dep so lieu.
"""


def sinh_bang_llm(so_luong: int, cfg=config) -> List[Dict]:
    """Goi Claude de sinh gia thuyet. Tra ve list spec CHUA kiem tra."""
    if not cfg.ANTHROPIC_API_KEY:
        raise RuntimeError("Chua co ANTHROPIC_API_KEY trong .env")
    import anthropic

    phi = (cfg.FEE_TAKER + cfg.SLIPPAGE) * 2 * 100
    nhac = LOI_NHAC % (so_luong, cfg.KLINE_INTERVAL, ", ".join(rule_spec.COT_HOP_LE),
                       ", ".join(rule_spec.TOAN_TU_HOP_LE), rule_spec.GIOI_HAN_DIEU_KIEN,
                       ", ".join(cfg.ENABLED_STRATEGIES), phi)
    client = anthropic.Anthropic(api_key=cfg.ANTHROPIC_API_KEY)
    resp = client.messages.create(model=cfg.LLM_MODEL, max_tokens=4000,
                                  messages=[{"role": "user", "content": nhac}])
    text = resp.content[0].text.strip()
    dau, cuoi = text.find("["), text.rfind("]")
    if dau < 0 or cuoi < 0:
        raise RuntimeError("LLM khong tra ve mang JSON:\n%s" % text[:400])
    return json.loads(text[dau:cuoi + 1])


# ==========================================================
# CLI
# ==========================================================
def main() -> int:
    ap = argparse.ArgumentParser(description="Strategy Lab - Nang cap 5")
    sub = ap.add_subparsers(dest="lenh", required=True)

    p1 = sub.add_parser("kiem-dinh", help="walk-forward cac gia thuyet trong file")
    p1.add_argument("--specs", required=True, help="file JSON chua mang gia thuyet")
    p1.add_argument("--symbols", default=None)
    p1.add_argument("--interval", default=None)

    p2 = sub.add_parser("sinh", help="nho LLM sinh gia thuyet moi (can API key)")
    p2.add_argument("--so-luong", type=int, default=10)
    p2.add_argument("--ra", default=os.path.join(config.BASE_DIR, "research",
                                                 "gia_thuyet.json"))

    sub.add_parser("trang-thai", help="da thu bao nhieu gia thuyet luy ke")
    args = ap.parse_args()

    if args.lenh == "trang-thai":
        bo_dem = doc_bo_dem()
        n = bo_dem.get("so_lan_thu", 0)
        print("So gia thuyet da thu luy ke: %d" % n)
        print("Ky vong cuc dai cua nhieu (don vi sai so chuan): %.2f"
              % ky_vong_cuc_dai_chuan(n))
        for m in bo_dem.get("lich_su", [])[-10:]:
            print("  %s  +%-3d -> %-4d  %s"
                  % (m["thoi_diem"], m["them"], m["tong"], m.get("ghi_chu", "")))
        return 0

    if args.lenh == "sinh":
        specs = sinh_bang_llm(args.so_luong)
        hop_le = rule_spec.bien_dich_nhieu(specs)
        with open(args.ra, "w", encoding="utf-8") as f:
            json.dump(specs, f, ensure_ascii=False, indent=2)
        print("LLM sinh %d gia thuyet, %d cai bien dich duoc. Ghi vao %s"
              % (len(specs), len(hop_le), args.ra))
        print("Doc lai truoc khi kiem dinh - moi gia thuyet deu ton mot phep thu.")
        return 0

    with open(args.specs, encoding="utf-8") as f:
        specs = json.load(f)
    symbols = ([s.strip().upper() for s in args.symbols.split(",")]
               if args.symbols else list(config.SYMBOLS))
    chay(specs, symbols, args.interval or config.KLINE_INTERVAL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
