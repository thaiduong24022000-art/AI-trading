"""
Doc va sua .env tu web UI - co danh sach trang chat che.

BA RANG BUOC, THEO THU TU QUAN TRONG:

1. KHOA BI MAT GHI DUOC NHUNG KHONG DOC DUOC.
   `OKX_API_SECRET` va cac khoa khac ghi duoc tu UI qua `ghi_bi_mat()`, nhung
   KHONG CO duong nao doc gia tri ra. UI chi biet duoc mot dieu ve chung: CO
   dat hay CHUA dat. Gia tri di MOT CHIEU - tu trinh duyet vao .env, khong bao
   gio di nguoc lai: khong vao ket qua tra ve, khong vao log, khong vao nhan
   `da_doi`.

   Vi sao mot chieu la du: bang dieu khien chi lang nghe 127.0.0.1, va ai vao
   duoc cong do thi da bat/tat bot va dat lenh duoc roi - cho ghi them khoa
   khong noi rong quyen han bao nhieu. Cho DOC thi khac han: no bien moi lo
   hong hien thi thanh mot vu lo khoa API vinh vien, va khoa da lo thi khong
   rut lai duoc.

2. CHI SUA DUOC NHUNG GI CO TRONG `CO_THE_SUA`.
   Moi khoa co mot bo kiem tra rieng. Gia tri khong hop le bi tu choi kem ly do,
   khong bao gio duoc ghi "cho co". Mot so xau trong .env se lam bot doc ra gia
   tri mac dinh mot cach im lang - do la kieu hong te nhat.

3. GHI KHONG DUOC LAM MAT GI.
   Ghi de theo DONG: giu nguyen thu tu, comment, dong trong va moi khoa khong
   quen biet. Khong bao gio sinh lai ca tep tu mot dict - lam vay se xoa sach
   comment va cac khoa ma phien ban UI nay chua biet den.
"""
import os
import re
import shutil
from typing import Dict, List, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")

# Khoa bi mat: UI chi duoc biet CO dat hay chua, khong bao gio biet gia tri.
KHOA_BI_MAT = ("BYBIT_API_KEY", "BYBIT_API_SECRET", "ANTHROPIC_API_KEY",
              "OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE",
              "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")


# Nhung khoa thuoc ve BANG CHON SAN chu khong phai bang .env chung. Chung van
# sua duoc qua `ghi()` nhu moi khoa khac - danh sach nay chi de UI khoi ve
# chung o hai cho, roi hai cho lech nhau sau mot lan luu.
KHOA_SAN = ("EXCHANGE", "BYBIT_TESTNET", "OKX_DEMO", "OKX_TD_MODE")

# Khoa bat buoc de goi duoc API rieng tu cua tung san. OKX doi them passphrase
# ma Bybit khong co - do la thu nguoi chuyen tu Bybit sang hay quen nhat.
KHOA_BAT_BUOC = {
    "bybit": ("BYBIT_API_KEY", "BYBIT_API_SECRET"),
    "okx": ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"),
}


def _bool(v: str) -> Tuple[bool, str]:
    return (v.lower() in ("true", "false"),
            "chi nhan true hoac false")


# `lua_chon` cho UI biet khoa nay chi co mot tap gia tri huu han, de render ra
# o CHON thay vi o go tu do. Go tay mot enum la mot nguon loi khong can thiet:
# "Bybit" hay "OKX " (thua dau cach) deu bi tu choi, va nguoi dung phai doan
# xem minh go sai cho nao.
_bool.lua_chon = ["true", "false"]


def _trong(lo: float, hi: float):
    def kiem(v: str) -> Tuple[bool, str]:
        try:
            x = float(v)
        except ValueError:
            return False, "phai la mot so"
        return lo <= x <= hi, "phai nam trong khoang %g - %g" % (lo, hi)
    return kiem


def _thuoc(*cho_phep):
    def kiem(v: str) -> Tuple[bool, str]:
        return v in cho_phep, "chi nhan: %s" % ", ".join(cho_phep)
    kiem.lua_chon = list(cho_phep)
    return kiem


def _danh_sach_ma(v: str) -> Tuple[bool, str]:
    ma = [s.strip() for s in v.split(",") if s.strip()]
    if not ma:
        return False, "phai co it nhat mot ma"
    if len(ma) > 60:
        return False, "toi da 60 ma"
    return (all(re.fullmatch(r"[A-Z0-9]{4,20}", s) for s in ma),
            "moi ma chi gom chu hoa va so, vi du BTCUSDT")


def _chien_luoc(v: str) -> Tuple[bool, str]:
    """Ba chien luoc goc, cong cac chien luoc LUAT da len trang thai chu_dong.

    Chien luoc luat dang o che do bong CO Y khong duoc nhan o day: bat no
    trong ENABLED_STRATEGIES la dua no vao ensemble that, tuc la ket thuc che
    do bong bang duong vong ma khong ai ghi lai quyet dinh do o dau.
    """
    from src.strategies import ALL_STRATEGIES
    ten = {c.name for c in ALL_STRATEGIES}
    try:
        from src.strategies.kho_luat import KhoLuat
        ten |= set(KhoLuat().ten_chu_dong())
    except Exception:
        pass        # kho luat hong khong duoc chan viec sua cau hinh khac
    chon = [s.strip() for s in v.split(",") if s.strip()]
    return (bool(chon) and all(s in ten for s in chon),
            "chi nhan: %s" % ", ".join(sorted(ten)))


def _khung(v: str) -> Tuple[bool, str]:
    return v in ("1", "3", "5", "15", "30", "60", "120", "240", "360", "720",
                 "D", "W", "M"), "khung Bybit hop le, vi du 60 hoac 240"


# Khoa: (bo kiem tra, mo ta ngan, co can khoi dong lai bot khong)
CO_THE_SUA: Dict[str, Tuple] = {
    # --- che do chay ---
    "DRY_RUN": (_bool, "true = khong gui lenh that", True),
    "EXCHANGE": (_thuoc("bybit", "okx"), "san giao dich - doi can restart bot", True),
    "BYBIT_TESTNET": (_bool, "true = san thu nghiem (Bybit)", True),
    "OKX_DEMO": (_bool, "true = demo trading (OKX) - tuong duong BYBIT_TESTNET", True),
    "OKX_TD_MODE": (_thuoc("cross", "isolated"), "che do margin OKX khi CATEGORY=linear", True),
    "ALLOW_SHORT": (_bool, "cho phep ban khong - spot phai la false", True),
    "CATEGORY": (_thuoc("spot", "linear"), "spot hoac linear (futures)", True),

    # --- thi truong ---
    "SYMBOLS": (_danh_sach_ma, "cac ma theo doi, cach nhau bang dau phay", True),
    "KLINE_INTERVAL": (_khung, "khung thoi gian tinh bang phut", True),
    "ENABLED_STRATEGIES": (_chien_luoc, "chien luoc luat duoc bat", True),
    "LOOP_INTERVAL_SECONDS": (_trong(30, 3600), "giay giua hai vong quyet dinh", True),

    # --- rui ro ---
    "RISK_PER_TRADE": (_trong(0.0005, 0.05), "ty le von rui ro moi lenh", True),
    "MAX_PORTFOLIO_HEAT": (_trong(0.005, 0.20), "tong rui ro dang mo toi da", True),
    "MAX_DAILY_DRAWDOWN": (_trong(0.01, 0.30), "sut giam ngay toi da truoc khi ngat", True),
    "MAX_OPEN_POSITIONS": (_trong(1, 20), "so vi the mo cung luc", True),
    "ATR_STOP_MULT": (_trong(0.5, 6.0), "khoang cach stop theo ATR", True),
    "ATR_TP_MULT": (_trong(0.5, 12.0), "khoang cach chot lai theo ATR", True),
    "EP_STOP_PHIA_BOT": (_bool, "bot tu dong khi stop cua san khong chay", True),

    # --- AI policy ---
    "POLICY_MODE": (_thuoc("off", "shadow", "filter", "active"),
                    "muc do policy duoc phep anh huong den lenh", True),
    "POLICY_MIN_MA": (_trong(2, 60), "so ma toi thieu de xep hang cat ngang co nghia", True),
    "POLICY_EV_MIN": (_trong(0.0, 0.05), "ky vong toi thieu de vao lenh", True),
    "POLICY_EV_FULL": (_trong(0.001, 0.10), "muc ky vong cho do manh toi da", True),
    "POLICY_FILTER_GIAM": (_trong(0.0, 1.0), "he so giam quy mo o che do filter", True),

    # --- canh bao ---
    "ENABLE_TELEGRAM": (_bool, "gui canh bao qua Telegram", True),
    "TELEGRAM_BAO_TUNG_LENH": (_bool, "bao moi lenh mo/dong", True),

    # --- LLM ---
    "ENABLE_LLM_VETO": (_bool, "bat lop LLM chan lenh", True),
    "ENABLE_NIGHTLY_JOURNAL": (_bool, "viet nhat ky hang dem", True),
}

# Nhung khoa co the doi BAI TOAN ma mo hinh da hoc. Doi chung se lam dau van tay
# lech va policy tu choi champion hien tai - UI phai canh bao truoc, khong de
# nguoi dung phat hien ra bang cach thay policy bong dung im lang.
DOI_BAI_TOAN = ("ATR_STOP_MULT", "ATR_TP_MULT", "KLINE_INTERVAL")


def doc_tho() -> List[str]:
    if not os.path.exists(ENV_PATH):
        return []
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        return f.read().splitlines()


def _tach(dong: str) -> Optional[Tuple[str, str]]:
    s = dong.strip()
    if not s or s.startswith("#") or "=" not in s:
        return None
    k, _, v = s.partition("=")
    return k.strip(), v.strip()


def doc_gia_tri() -> Dict[str, str]:
    """Chi cac khoa CO TRONG danh sach sua duoc. Khoa bi mat khong bao gio o day."""
    ra = {}
    for dong in doc_tho():
        cap = _tach(dong)
        if cap and cap[0] in CO_THE_SUA:
            ra[cap[0]] = cap[1]
    return ra


def trang_thai_bi_mat() -> Dict[str, bool]:
    """CO dat hay chua - khong bao gio la gia tri.

    Du chi de hien mot dau tich trong UI, va du de chan doan "401 vi thieu key"
    ma khong bao gio dua khoa qua HTTP.
    """
    co = {k: False for k in KHOA_BI_MAT}
    for dong in doc_tho():
        cap = _tach(dong)
        if cap and cap[0] in co:
            co[cap[0]] = bool(cap[1].strip())
    return co


def doc_bi_mat_cho_tien_trinh_nay() -> Dict[str, str]:
    """Gia tri that cua cac khoa bi mat. CHI dung trong tien trinh, KHONG tra ra HTTP.

    Ton tai cho DUNG MOT viec: nut "Thu ket noi" o UI phai dung khoa vua dan
    de goi san, ma khoa do moi nam trong .env chu chua co trong `config` da nap
    tu luc khoi dong. Ham nay dua khoa thang cho client san, roi ket qua tra ve
    chi la "ket noi duoc / khong" - khoa khong di kem.

    Bat ky cho nao goi ham nay roi dua ket qua vao `jsonify`, vao log, hay vao
    thong bao loi deu la mot bug bao mat, khong phai mot lua chon thiet ke.
    """
    ra = {k: "" for k in KHOA_BI_MAT}
    for dong in doc_tho():
        cap = _tach(dong)
        if cap and cap[0] in ra:
            ra[cap[0]] = cap[1].strip()
    return ra


def kiem_tra(khoa: str, gia_tri: str) -> Optional[str]:
    """None = hop le. Nguoc lai tra ve ly do tu choi."""
    if khoa not in CO_THE_SUA:
        return "khoa '%s' khong duoc phep sua tu giao dien" % khoa
    gia_tri = str(gia_tri).strip()
    if "\n" in gia_tri or "\r" in gia_tri:
        return "gia tri khong duoc xuong dong"
    if len(gia_tri) > 500:
        return "gia tri qua dai"
    hop_le, mo_ta = CO_THE_SUA[khoa][0](gia_tri)
    return None if hop_le else mo_ta


def _ap_dung(thay_doi: Dict[str, str]) -> Dict[str, Dict]:
    """Ghi de theo DONG vao .env. Tra ve {khoa: {"cu":..., "moi":...}}.

    Ham NOI BO va la cho duy nhat cham vao tep. Ket qua no tra ve CO CHUA gia
    tri that, ke ca gia tri bi mat - nguoi goi chiu trach nhiem loc truoc khi
    dua ra ngoai (xem `ghi_bi_mat`).
    """
    dong = doc_tho()
    con_lai = {k: str(v).strip() for k, v in thay_doi.items()}
    da_doi = {}

    for i, d in enumerate(dong):
        cap = _tach(d)
        if not cap or cap[0] not in con_lai:
            continue
        khoa = cap[0]
        gia_tri_moi = con_lai.pop(khoa)
        if cap[1] != gia_tri_moi:
            da_doi[khoa] = {"cu": cap[1], "moi": gia_tri_moi}
        dong[i] = "%s=%s" % (khoa, gia_tri_moi)

    if con_lai:
        dong.append("")
        dong.append("# Them tu bang dieu khien")
        for khoa, gia_tri_moi in con_lai.items():
            dong.append("%s=%s" % (khoa, gia_tri_moi))
            da_doi[khoa] = {"cu": "", "moi": gia_tri_moi}

    if da_doi:
        # Ban sao truoc khi ghi. .env chua khoa API - mat no vi mot loi ghi tep
        # la mot buoi chieu di tao lai khoa tren san.
        if os.path.exists(ENV_PATH):
            shutil.copy2(ENV_PATH, ENV_PATH + ".bak")
        tam = ENV_PATH + ".tmp"
        with open(tam, "w", encoding="utf-8") as f:
            f.write("\n".join(dong).rstrip("\n") + "\n")
        os.replace(tam, ENV_PATH)

    return da_doi


def ghi(thay_doi: Dict[str, str]) -> Dict:
    """Ghi de theo dong, giu nguyen moi thu khac. Tra ve tom tat viec da lam.

    Kiem tra TOAN BO truoc khi ghi bat cu gi: mot yeu cau doi 5 khoa ma khoa thu
    3 sai thi khong duoc de lai .env o trang thai sua mot nua.
    """
    loi = {}
    for k, v in thay_doi.items():
        ly_do = kiem_tra(k, v)
        if ly_do:
            loi[k] = ly_do
    if loi:
        return {"ok": False, "loi": loi}

    da_doi = _ap_dung(thay_doi)
    for m in da_doi.values():
        if m["cu"] == "":
            m["cu"] = "(chua dat)"

    return {
        "ok": True,
        "da_doi": da_doi,
        "can_khoi_dong_lai": any(CO_THE_SUA[k][2] for k in da_doi),
        "doi_bai_toan": [k for k in da_doi if k in DOI_BAI_TOAN],
    }


def kiem_tra_bi_mat(khoa: str, gia_tri: str) -> Optional[str]:
    """None = hop le. Nguoc lai tra ve ly do tu choi.

    Chuoi rong la HOP LE va co nghia la XOA khoa - do la cach go mot khoa da
    dan ra ngoai ma khong phai mo trinh soan thao.

    Ly do tu choi KHONG BAO GIO duoc nhac lai gia tri: thong bao loi di vao
    log trinh duyet va lich su fetch, nen mot dong "khoa sai: sk-abc123" chinh
    la kieu ro ri ma ca thiet ke nay dung de chan.
    """
    if khoa not in KHOA_BI_MAT:
        return "'%s' khong phai khoa bi mat" % khoa
    gia_tri = str(gia_tri).strip()
    if gia_tri == "":
        return None                       # chuoi rong = xoa khoa
    if len(gia_tri) > 500:
        return "gia tri qua dai (toi da 500 ky tu)"
    # Khoa API khong bao gio co khoang trang hay xuong dong o giua. Neu co thi
    # gan nhu chac chan la dan nham ca dong hoac ca doan van - bat o day de
    # nguoi dung biet ngay, thay vi doi san tra ve "invalid signature" mot
    # ngay nao do giua phien chay.
    if re.search(r"\s", gia_tri):
        return "khoa khong duoc chua khoang trang hay xuong dong - kiem tra lai doan vua dan"
    if gia_tri[0] in "\"'" or gia_tri[-1] in "\"'":
        return "bo dau nhay o hai dau - .env khong can dau nhay"
    return None


def ghi_bi_mat(thay_doi: Dict[str, str]) -> Dict:
    """Ghi khoa bi mat vao .env. MOT CHIEU: khong tra ve gia tri nao.

    Ket qua chi noi moi khoa roi vao trang thai nao - da dat hay da xoa - du
    nguoi goi la ai. Do la ly do ham nay khong dung chung duong tra ve voi
    `ghi`: `ghi` bao "cu -> moi" cho nguoi dung doi chieu, con o day chinh cai
    "cu -> moi" ay la thu khong duoc phep noi ra.
    """
    loi = {}
    for k, v in thay_doi.items():
        ly_do = kiem_tra_bi_mat(k, v)
        if ly_do:
            loi[k] = ly_do
    if loi:
        return {"ok": False, "loi": loi}

    da_doi = _ap_dung(thay_doi)
    return {
        "ok": True,
        "da_dat": sorted(k for k, m in da_doi.items() if m["moi"]),
        "da_xoa": sorted(k for k, m in da_doi.items() if not m["moi"]),
        "khong_doi": sorted(k for k in thay_doi if k not in da_doi),
        "can_khoi_dong_lai": bool(da_doi),
    }


def mo_ta_khoa() -> List[Dict]:
    """Danh sach khoa sua duoc kem gia tri hien tai - de UI dung bang cau hinh."""
    hien = doc_gia_tri()
    ra = []
    for khoa, (kiem, mo_ta, khoi_dong_lai) in CO_THE_SUA.items():
        ra.append({
            "khoa": khoa,
            "gia_tri": hien.get(khoa, ""),
            "mo_ta": mo_ta,
            "can_khoi_dong_lai": khoi_dong_lai,
            "doi_bai_toan": khoa in DOI_BAI_TOAN,
            "lua_chon": getattr(kiem, "lua_chon", None),
        })
    return ra
