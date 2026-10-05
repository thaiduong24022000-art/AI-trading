"""
Web UI cho AI Trade Bot - bang dieu khien day du, chay tren may cua ban.

PHAM VI: bang nay dieu khien duoc toan bo he thong - du lieu, backtest,
walk-forward, vong hoc AI policy, thang cap/ha cap mo hinh, cau hinh, va ca
viec bat/dung bot.

BON RANG BUOC AN TOAN, DUOC THUC THI BANG CODE CHU KHONG BANG GHI CHU:

  1. CHI LANG NGHE 127.0.0.1. Bang nay chay duoc tien trinh tren may ban; mo no
     ra mang la mo mot cong chay lenh tuy y cho ca mang LAN.

  2. KHOA API DI MOT CHIEU. UI dat duoc khoa moi (POST /api/config/bi-mat)
     nhung KHONG route nao tra gia tri khoa ve - chi tra CO dat hay chua.
     Xem `env_store.ghi_bi_mat`. Nut "Thu ket noi" dung khoa ngay trong tien
     trinh nay va chi bao ket qua ket noi, khong bao khoa.

  3. CHAY TIEN THAT PHAI GO XAC NHAN. Bat bot o che do dry-run hoac testnet thi
     bam mot nut. Bat bot o che do gui lenh that bang tien that thi phai go dung
     mot cau xac nhan. Do khong phai thu tuc ruom ra: khac biet giua hai truong
     hop nay la khac biet giua mot loi bam nham va mot khoan lo that.

  4. CHI CHAY DUOC SCRIPT TRONG DANH SACH TRANG. Xem `jobs.SCRIPT_CHO_PHEP`.
     Khong route nao o day ghep chuoi tu dau vao nguoi dung thanh dong lenh.
"""
import glob
import json
import logging
import os
import sqlite3
import threading
import time
from typing import Dict, List

from flask import Flask, jsonify, render_template, request, send_file

import config
from . import env_store
from src.exchange import build_client
from .jobs import BASE_DIR, dich_vu, manager

REPORT_DIR = os.path.join(BASE_DIR, "data", "reports")
MODEL_DIR = getattr(config, "POLICY_MODEL_DIR", os.path.join(BASE_DIR, "models"))
ORDERBOOK_DIR = os.path.join(BASE_DIR, "data", "orderbook")

# Cau xac nhan de bat bot bang tien that. Co y kho go nham.
CAU_XAC_NHAN = "TOI CHAP NHAN RUI RO"

logger = logging.getLogger(__name__)

# Bo nho dem ket qua thu ket noi san.
#
# VI SAO PHAI CO. Bang dieu khien hoi /api/status moi 6 giay. Neu moi lan hoi
# deu goi san that thi vua ton han muc goi vua cham. Nhung neu KHONG goi san
# thi bang chi biet ".env co bien hay khong" - va do chinh la cai bay da xay ra
# ngay 2026-09-10: khoa DA DAT nhung khong hop le (Bybit tra 10003), bang van
# bao "da dat" mau xanh, con muc "viec nen lam tiep" thi di nhac chuyen so ma.
# Nguoi dung nhin bang thay moi thu on trong khi thu duy nhat dang chan ho lai
# khong duoc nhac o dau ca.
_KET_NOI = {"luc": 0.0, "ket_qua": None}
_KET_NOI_TTL = 90.0
_KET_NOI_KHOA = threading.Lock()

app = Flask(__name__, template_folder="templates")

# Jinja cache template va bang nay chay debug=False (co y - debug mo mot console
# chay code tuy y tren cong mang). Khong bat auto-reload thi sua index.html xong
# phai khoi dong lai server moi thay, va trieu chung la "code moi khong chay" -
# rat de doc nham thanh loi logic roi di sua nham cho.
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True


@app.get("/")
def index():
    return render_template("index.html")


# ==========================================================
# Tien ich dung chung
# ==========================================================
def _json() -> Dict:
    return request.get_json(silent=True) or {}


def _int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(_json().get(name, default))))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(_json().get(name, default))))
    except (TypeError, ValueError):
        return default


def _symbol(mac_dinh: str = "BTCUSDT") -> str:
    """Chi cho chu va so - tham so nay di vao dong lenh."""
    raw = str(_json().get("symbol", mac_dinh)).upper()
    return "".join(c for c in raw if c.isalnum())[:20] or mac_dinh


def _danh_sach_ma(ten: str = "symbols") -> str:
    """Chuoi 'A,B,C' da lam sach. Rong = de script tu chon mac dinh."""
    raw = str(_json().get(ten, "")).upper()
    ma = ["".join(c for c in s if c.isalnum())[:20] for s in raw.split(",")]
    return ",".join([s for s in ma if s][:60])


def _ma_co_cache(interval: str) -> List[str]:
    """Cac ma da co cache o mot khung - khong tinh tep du lieu phai sinh."""
    duoi = "_%s.csv" % interval
    ra = []
    for p in glob.glob(os.path.join(config.CACHE_DIR, "*%s" % duoi)):
        ten = os.path.basename(p)[:-len(duoi)]
        if "_deriv" not in ten:
            ra.append(ten)
    return sorted(ra)


def _chien_luoc_meta() -> str:
    """Ten chien luoc nguon cho bo loc - chi nhan ten da biet."""
    from src.strategies import ALL_STRATEGIES
    hop_le = {c.name for c in ALL_STRATEGIES}
    try:
        from src.strategies.kho_luat import KhoLuat
        hop_le |= set(KhoLuat().ten_chu_dong())
    except Exception:
        pass
    chon = [s.strip() for s in str(_json().get("chien_luoc", "")).split(",")
            if s.strip() in hop_le]
    return ",".join(chon[:10])


def _seeds() -> str:
    """Danh sach seed - chi so, toi da 5 cai."""
    ra = []
    for x in str(_json().get("seeds", "0,1,2")).split(","):
        x = x.strip()
        if x.isdigit():
            ra.append(x[:4])
    return ",".join(ra[:5]) or "0"


def _strategy() -> str:
    from src.strategies import ALL_STRATEGIES
    hop_le = {"all"} | {c.name for c in ALL_STRATEGIES}
    val = str(_json().get("strategy", "all"))
    return val if val in hop_le else "all"


def _phien_ban(gia_tri: str) -> str:
    """Ten phien ban mo hinh: chi chu, so, gach duoi - di vao duong dan va lenh."""
    return "".join(c for c in str(gia_tri) if c.isalnum() or c == "_")[:60]


def _doc_db(cau_lenh: str, tham_so=()) -> List[Dict]:
    if not os.path.exists(config.DB_PATH):
        return []
    try:
        con = sqlite3.connect("file:%s?mode=ro" % config.DB_PATH, uri=True)
        con.row_factory = sqlite3.Row
        rows = [dict(r) for r in con.execute(cau_lenh, tham_so)]
        con.close()
        return rows
    except sqlite3.Error:
        return []


# ==========================================================
# Trang thai he thong
# ==========================================================
# Nho so nen da dem theo duong dan -> ((mtime, size), so nen).
#
# VI SAO CAN. Bang goi /api/status moi 6 giay, va ham duoi dem so dong cua MOI
# tep CSV trong cache de hien "so nen". Voi 72 tep / 39 MB thi do la 39 MB doc
# dia moi 6 giay - do duoc 85 ms moi lan goi, gan het thoi gian cua ca endpoint
# - chi de hien mot con so chi doi khi nguoi dung tai du lieu moi.
#
# Khoa theo (mtime, size) chu khong chi mtime: mot vai he tep co do phan giai
# mtime tho (1-2 giay), nen mot tep bi ghi hai lan trong cung giay se qua mat
# phep kiem neu chi nhin mtime. Kem them size thi truong hop do phai vua trung
# giay VUA khong doi byte nao moi lot - luc do so nen cung dung la khong doi.
_DEM_NEN: Dict[str, tuple] = {}


def _so_nen(path: str) -> int:
    try:
        st = os.stat(path)
    except OSError:
        return 0
    dau = (st.st_mtime, st.st_size)
    cu = _DEM_NEN.get(path)
    if cu and cu[0] == dau:
        return cu[1]
    try:
        with open(path, "r", encoding="utf-8") as f:
            n = max(0, sum(1 for _ in f) - 1)
    except OSError:
        return 0
    _DEM_NEN[path] = (dau, n)
    return n


def _cache_files() -> List[Dict]:
    out = []
    ten_con = set()
    for path in sorted(glob.glob(os.path.join(config.CACHE_DIR, "*.csv"))):
        name = os.path.basename(path)[:-4]
        symbol, _, interval = name.rpartition("_")
        ten_con.add(path)
        out.append({
            "symbol": symbol, "interval": interval, "bars": _so_nen(path),
            "phai_sinh": "_deriv" in symbol,
            "size_kb": round(os.path.getsize(path) / 1024),
            "updated": time.strftime("%Y-%m-%d %H:%M",
                                     time.localtime(os.path.getmtime(path))),
        })
    # Tep da xoa khoi dia thi bo khoi bang nho, khong de no phinh mai.
    for cu in [k for k in _DEM_NEN if k not in ten_con]:
        _DEM_NEN.pop(cu, None)
    return out


def _db_summary() -> Dict:
    out = {"co_db": os.path.exists(config.DB_PATH), "equity": None}
    if not out["co_db"]:
        return out
    try:
        con = sqlite3.connect("file:%s?mode=ro" % config.DB_PATH, uri=True)
        con.row_factory = sqlite3.Row
        for bang in ("decisions", "orders", "trades", "equity_snapshots",
                     "policy_predictions"):
            try:
                out[bang] = con.execute("SELECT COUNT(*) FROM %s" % bang).fetchone()[0]
            except sqlite3.Error:
                out[bang] = 0
        row = con.execute(
            "SELECT equity, heat, open_positions FROM equity_snapshots "
            "ORDER BY ts DESC LIMIT 1").fetchone()
        if row:
            out["equity"] = dict(row)
        con.close()
    except sqlite3.Error as e:
        out["loi"] = str(e)
    return out


def _log_tail(n: int = 60) -> List[str]:
    if not os.path.exists(config.LOG_PATH):
        return []
    try:
        with open(config.LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
            return [l.rstrip("\n") for l in f.readlines()[-n:]]
    except OSError:
        return []


def _champion_yen_lang(lam_kho) -> str:
    """Ten champion, hoac chuoi rong. Kho hong khong duoc lam sap /api/status."""
    try:
        return lam_kho().champion_hien_tai() or ""
    except Exception:
        return ""


def _kiem_tra_ket_noi_dem(buoc_lam_moi: bool = False) -> Dict:
    """Trang thai ket noi san THUC TE, co dem theo thoi gian.

    Tra ve mot trong bon trang thai, va chung khac nhau ve CACH SUA:
        chua_co_khoa  -> dan khoa vao tab Cau hinh
        khoa_sai      -> khoa khong ton tai o san nay, tao khoa moi dung san
        thieu_quyen   -> khoa co that, sua quyen tren chinh khoa do
        ok            -> goi duoc, kem so du
    """
    env = env_store.trang_thai_bi_mat()
    san = env_store.doc_gia_tri().get("EXCHANGE", config.EXCHANGE)
    can = env_store.KHOA_BAT_BUOC.get(san, ())
    thieu = [k for k in can if not env.get(k)]
    if thieu:
        return {"trang_thai": "chua_co_khoa", "san": san, "thieu": thieu,
                "chi_tiet": "chua dat: %s" % ", ".join(thieu)}

    now = time.time()
    with _KET_NOI_KHOA:
        cu = _KET_NOI["ket_qua"]
        if cu and not buoc_lam_moi and (now - _KET_NOI["luc"]) < _KET_NOI_TTL:
            return dict(cu, tu_bo_nho_dem=True)

    try:
        kq = build_client(config).kiem_tra_ket_noi()
        ra = {
            "trang_thai": "ok" if kq.get("ok")
                          else ("khoa_sai" if kq.get("khoa_khong_ton_tai")
                                else "thieu_quyen"),
            "san": san,
            "chi_tiet": kq.get("chi_tiet", ""),
        }
    except Exception as e:
        # Loi mang khong duoc bao thanh "khoa sai" - hai cai sua khac han nhau.
        ra = {"trang_thai": "khong_goi_duoc", "san": san,
              "chi_tiet": "khong goi duoc san: %s" % str(e)[:120]}

    with _KET_NOI_KHOA:
        _KET_NOI["luc"], _KET_NOI["ket_qua"] = time.time(), ra
    return dict(ra, tu_bo_nho_dem=False)


def _trang_thai_collector() -> Dict:
    """So lenh dang duoc thu thap khong - ke ca khi collector chay ngoai UI.

    Bo thu thap thuong duoc bat bang file .bat truoc khi mo bang dieu khien, nen
    UI khong the chi nhin tien trinh con cua chinh no. Dau hieu dang tin hon la
    tep du lieu co dang lon len hay khong.
    """
    tep = sorted(glob.glob(os.path.join(ORDERBOOK_DIR, "ob_*.csv")))
    if not tep:
        return {"co_du_lieu": False, "dang_ghi": False, "so_dong": 0}
    moi_nhat = tep[-1]
    tuoi = time.time() - os.path.getmtime(moi_nhat)
    try:
        with open(moi_nhat, "r", encoding="utf-8") as f:
            so_dong = max(0, sum(1 for _ in f) - 1)
    except OSError:
        so_dong = 0
    return {
        "co_du_lieu": True,
        "tep": os.path.basename(moi_nhat),
        "so_dong": so_dong,
        "so_ngay": len(tep),
        "giay_tu_lan_ghi_cuoi": round(tuoi),
        # Ghi moi phut mot lan; qua 180 giay khong doi nghia la da dung.
        "dang_ghi": tuoi < 180,
    }


def _trang_thai_bot() -> Dict:
    """Nhip tim bot ghi vao DB moi vong. Khac voi "tien trinh con song khong":
    cai nay cho biet bot dang NGHI GI - nhat la circuit breaker co dang ngat.
    """
    rows = _doc_db("SELECT * FROM trang_thai_bot WHERE id = 1")
    if not rows:
        return {"co": False}
    r = dict(rows[0])
    r["co"] = True
    r["giay_tu_nhip_cuoi"] = round(time.time() - (r.get("ts") or 0))
    cho = _doc_db("SELECT lenh, ts FROM lenh_dieu_khien WHERE trang_thai='cho'")
    r["lenh_dang_cho"] = [x["lenh"] for x in cho]
    return r


@app.get("/api/status")
def api_status():
    job = manager.current()
    moi_nhat = _CauHinhVuaDoc()
    return jsonify({
        "cache": _cache_files(),
        "db": _db_summary(),
        "log": _log_tail(),
        "dang_chay": job.to_dict(since=job.to_dict()["total_lines"]) if job else None,
        "dich_vu": dich_vu.tat_ca(),
        "orderbook": _trang_thai_collector(),
        "bot_trang_thai": _trang_thai_bot(),
        "bi_mat": env_store.trang_thai_bi_mat(),
        "ket_noi": _kiem_tra_ket_noi_dem(),
        # Champion cua hai lop hoc may. Bang trang thai can chung de phan biet
        # "policy dang bat" voi "policy dang bat NHUNG chua co mo hinh nao" -
        # hai trang thai rat khac nhau ma bang cu gop lam mot.
        "policy_champion": _champion_yen_lang(_kho),
        "meta_champion": _champion_yen_lang(_kho_meta),
        # Doc lai tu .env chu khong dung ban da nap: nguoi dung vua luu xong
        # ma the o Tong quan van hien gia tri cu la mot bao cao SAI, khong
        # phai mot do tre - ho khong co cach nao biet cai nao dang dung.
        "cau_hinh": {
            "exchange": moi_nhat.EXCHANGE,
            "symbols": moi_nhat.SYMBOLS,
            "interval": moi_nhat.KLINE_INTERVAL,
            "category": moi_nhat.CATEGORY,
            "testnet": (moi_nhat.BYBIT_TESTNET if moi_nhat.EXCHANGE == "bybit"
                       else moi_nhat.OKX_DEMO),
            "dry_run": moi_nhat.DRY_RUN,
            "allow_short": moi_nhat.ALLOW_SHORT,
            "chien_luoc": moi_nhat.ENABLED_STRATEGIES,
            "policy_mode": moi_nhat.POLICY_MODE,
            "rui_ro_moi_lenh": moi_nhat.RISK_PER_TRADE,
            "heat_toi_da": moi_nhat.MAX_PORTFOLIO_HEAT,
            "phi_mot_vong": (config.FEE_TAKER + config.SLIPPAGE) * 2,
        },
        "cong": {
            "so_lenh": config.GATE_MIN_TRADES, "sharpe": config.GATE_MIN_SHARPE,
            "drawdown": config.GATE_MAX_DRAWDOWN, "pf": config.GATE_MIN_PROFIT_FACTOR,
        },
    })


# ==========================================================
# Tac vu mot lan
# ==========================================================
@app.post("/api/run/<kind>")
def api_run(kind: str):
    os.makedirs(REPORT_DIR, exist_ok=True)
    script = "run_backtest.py"

    if kind == "download":
        symbol = _symbol()
        bars = _int("bars", 8000, 200, 200000)
        args = ["download", "--symbol", symbol, "--bars", str(bars)]
        label = "Tai %s - %d nen" % (symbol, bars)

    elif kind == "backtest":
        symbol = _symbol()
        args = ["backtest", "--symbol", symbol, "--strategy", _strategy(),
                "--equity", str(_float("equity", 10000.0, 100.0, 1e9))]
        if _json().get("synthetic"):
            args += ["--synthetic", "--bars", str(_int("bars", 3000, 300, 100000))]
        if _json().get("no_regime"):
            args.append("--no-regime")
        name = "backtest_%s_%s.html" % (symbol, time.strftime("%Y%m%d_%H%M%S"))
        args += ["--report", os.path.join(REPORT_DIR, name)]
        label = "Backtest %s" % symbol

    elif kind == "walkforward":
        symbol = _symbol()
        args = ["walkforward", "--symbol", symbol, "--strategy", _strategy(),
                "--equity", str(_float("equity", 10000.0, 100.0, 1e9)),
                "--train-bars", str(_int("train_bars", 4320, 200, 100000)),
                "--test-bars", str(_int("test_bars", 1440, 100, 100000)),
                "--step-bars", str(_int("step_bars", 1440, 100, 100000))]
        if _json().get("synthetic"):
            args += ["--synthetic", "--bars", str(_int("bars", 4000, 300, 100000))]
        label = "Walk-forward %s" % symbol

    elif kind == "hoc":
        script = "run_policy.py"
        args = ["hoc", "--max-horizon", str(_int("max_horizon", 60, 5, 400)),
                "--seed", str(_int("seed", 0, 0, 9999))]
        ma = _danh_sach_ma()
        if ma:
            args += ["--symbols", ma]
        if _json().get("khong_phai_sinh"):
            args.append("--khong-phai-sinh")
        label = "Vong hoc policy"

    elif kind == "meta-hoc":
        script = "run_meta.py"
        args = ["hoc", "--max-horizon", str(_int("max_horizon", 60, 5, 400)),
                "--seed", str(_int("seed", 0, 0, 9999))]
        ma = _danh_sach_ma()
        if ma:
            args += ["--symbols", ma]
        cl = _chien_luoc_meta()
        if cl:
            args += ["--chien-luoc", cl]
        label = "Hoc bo loc meta"

    elif kind == "meta-quet":
        script = "run_meta.py"
        args = ["quet", "--max-horizon", str(_int("max_horizon", 60, 5, 400)),
                "--so-cua-so", str(_int("so_cua_so", 6, 2, 20)),
                "--val-bars", str(_int("val_bars", 700, 100, 5000)),
                "--seeds", _seeds()]
        ma = _danh_sach_ma()
        if ma:
            args += ["--symbols", ma]
        cl = _chien_luoc_meta()
        if cl:
            args += ["--chien-luoc", cl]
        label = "Quet do on dinh bo loc"

    elif kind == "theo-doi":
        script = "run_policy.py"
        args = ["theo-doi", "--max-horizon", str(_int("max_horizon", 60, 5, 400))]
        label = "Theo doi champion"

    elif kind == "tai-universe":
        script = "-m research.download_universe"
        args = ["--interval", str(_int("interval", int(config.KLINE_INTERVAL)
                                       if str(config.KLINE_INTERVAL).isdigit() else 240,
                                       1, 1440)),
                "--top", str(_int("top", 25, 2, 100))]
        label = "Tai ro ma tu mainnet"

    elif kind == "tai-phai-sinh":
        script = "-m research.download_derivatives"
        khung = str(_int("interval", 240, 1, 1440))
        # --symbols la bat buoc voi script nay. Khong nhap thi lay moi ma dang co
        # cache o khung do - do gan nhu luon la y dinh cua nguoi bam nut.
        ma = _danh_sach_ma() or ",".join(_ma_co_cache(khung))
        if not ma:
            return jsonify({"loi": "chua co ma nao trong cache o khung %s" % khung}), 400
        args = ["--interval", khung, "--symbols", ma]
        label = "Tai funding + OI cho %d ma" % len(ma.split(","))

    elif kind == "ic-study":
        script = "-m research.ic_study"
        khung = str(_int("interval", 240, 1, 1440))
        ma = _danh_sach_ma() or ",".join(_ma_co_cache(khung))
        if not ma:
            return jsonify({"loi": "chua co ma nao trong cache o khung %s" % khung}), 400
        args = ["--symbols", ma, "--interval", khung,
                "--max-horizon", str(_int("max_horizon", 60, 5, 400))]
        label = "Do IC tren %d ma" % len(ma.split(","))

    elif kind == "quet-hang-rao":
        script = "-m research.quet_hang_rao"
        khung = str(_int("interval", 240, 1, 1440))
        ma = _danh_sach_ma() or ",".join(_ma_co_cache(khung))
        if not ma:
            return jsonify({"loi": "chua co ma nao trong cache o khung %s" % khung}), 400
        args = ["--symbols", ma, "--interval", khung,
                "--max-horizon", str(_int("max_horizon", 60, 5, 400)),
                "--seed", str(_int("seed", 0, 0, 9999))]
        if _json().get("nhanh"):
            args.append("--nhanh")
        label = "Quet hang rao x chi phi tren %d ma" % len(ma.split(","))

    elif kind == "phase0":
        script = "run_phase0.py"
        args = ["--symbols", _danh_sach_ma() or ",".join(config.SYMBOLS),
                "--timeframes", "60,240,D"]
        label = "Phase 0 - quet chien luoc goc"

    elif kind == "lab-kiem-dinh":
        script = "-m research.strategy_lab"
        duong_dan = os.path.join(BASE_DIR, "research", "gia_thuyet.json")
        if not os.path.exists(duong_dan):
            return jsonify({"loi": "chua co research/gia_thuyet.json - soan gia "
                                   "thuyet o tab Strategy Lab truoc"}), 400
        args = ["kiem-dinh", "--specs", duong_dan]
        ma = _danh_sach_ma()
        if ma:
            args += ["--symbols", ma]
        args += ["--interval", str(_int("interval", int(config.KLINE_INTERVAL)
                                        if str(config.KLINE_INTERVAL).isdigit() else 240,
                                        1, 1440))]
        # Moi lan chay la mot loat phep thu VINH VIEN vao bo dem - nhan hien so
        # gia thuyet de nguoi bam biet minh dang tieu bao nhieu.
        try:
            with open(duong_dan, encoding="utf-8") as f:
                so = len(json.load(f))
        except Exception:
            so = 0
        label = "Strategy Lab: kiem dinh %d gia thuyet" % so

    elif kind == "lab-sinh":
        if not config.ANTHROPIC_API_KEY:
            return jsonify({"loi": "chua co ANTHROPIC_API_KEY trong .env"}), 400
        script = "-m research.strategy_lab"
        args = ["sinh", "--so-luong", str(_int("so_luong", 10, 1, 30))]
        label = "Strategy Lab: nho LLM sinh gia thuyet"

    else:
        return jsonify({"loi": "tac vu khong hop le"}), 400

    try:
        job = manager.start(kind, script, args, label)
    except (RuntimeError, ValueError) as e:
        return jsonify({"loi": str(e)}), 409
    return jsonify({"id": job.id})


@app.get("/api/job/<job_id>")
def api_job(job_id: str):
    job = manager.get(job_id)
    if job is None:
        return jsonify({"loi": "khong tim thay tac vu"}), 404
    try:
        since = int(request.args.get("since", 0))
    except ValueError:
        since = 0
    return jsonify(job.to_dict(since=max(0, since)))


@app.post("/api/job/<job_id>/stop")
def api_stop(job_id: str):
    job = manager.get(job_id)
    if job is None:
        return jsonify({"loi": "khong tim thay tac vu"}), 404
    return jsonify({"da_dung": job.stop()})


@app.get("/api/jobs")
def api_jobs():
    return jsonify(manager.recent())


# ==========================================================
# Dich vu chay dai: bot va bo thu thap so lenh
# ==========================================================
@app.post("/api/service/bot/start")
def api_bot_start():
    """Bat bot. Che do tien that doi go dung cau xac nhan.

    Doc lai .env truc tiep chu khong dua vao `config` da nap trong bo nho: nguoi
    dung vua sua cau hinh o tab ben canh thi tien trinh web van giu gia tri cu,
    va quyet dinh "co phai tien that khong" phai dua tren cai SAP CHAY chu khong
    phai cai da nap luc khoi dong web.
    """
    env = env_store.doc_gia_tri()
    dry_run = env.get("DRY_RUN", str(config.DRY_RUN)).strip().lower() in ("1", "true", "yes", "on")

    # San dang chon quyet dinh KHOA testnet/demo nao la khoa that su co hieu luc.
    # Doc nham BYBIT_TESTNET khi dang chay OKX (hoac nguoc lai) se lam cong xac
    # nhan tien that bi BO QUA hoan toan - day la ly do khong duoc hardcode ten
    # khoa, phai chon theo EXCHANGE dang duoc cau hinh de chay.
    exchange = env.get("EXCHANGE", config.EXCHANGE).strip().lower()
    if exchange == "okx":
        testnet_key, testnet_mac_dinh = "OKX_DEMO", config.OKX_DEMO
    else:
        testnet_key, testnet_mac_dinh = "BYBIT_TESTNET", config.BYBIT_TESTNET
    testnet = env.get(testnet_key, str(testnet_mac_dinh)).strip().lower() in ("1", "true", "yes", "on")
    tien_that = (not dry_run) and (not testnet)

    if tien_that and str(_json().get("xac_nhan", "")).strip() != CAU_XAC_NHAN:
        return jsonify({
            "loi": "Cau hinh hien tai la GUI LENH THAT BANG TIEN THAT "
                   "(DRY_RUN=false, %s=false, san=%s)." % (testnet_key, exchange),
            "can_xac_nhan": True,
            "cau_xac_nhan": CAU_XAC_NHAN,
        }), 428

    bi_mat = env_store.trang_thai_bi_mat()
    if exchange == "okx":
        thieu = (not bi_mat.get("OKX_API_KEY") or not bi_mat.get("OKX_API_SECRET")
                or not bi_mat.get("OKX_API_PASSPHRASE"))
        ten_khoa = "OKX_API_KEY/OKX_API_SECRET/OKX_API_PASSPHRASE"
    else:
        thieu = not bi_mat.get("BYBIT_API_KEY") or not bi_mat.get("BYBIT_API_SECRET")
        ten_khoa = "BYBIT_API_KEY/BYBIT_API_SECRET"
    if thieu:
        return jsonify({"loi": "Chua co %s trong .env - bot se "
                               "dung lai o buoc doi soat. Sua .env bang trinh soan thao."
                               % ten_khoa}), 400

    ghi_chu = ("CHE DO TIEN THAT" if tien_that
               else "dry-run" if dry_run else "testnet")
    cmd = [__import__("sys").executable, "-u", os.path.join(BASE_DIR, "main.py")]
    if _json().get("mot_vong"):
        cmd.append("--once")
        ghi_chu += " - chay mot vong roi thoat"

    sv = dich_vu.get("bot")
    try:
        sv.start(cmd, ghi_chu)
    except RuntimeError as e:
        return jsonify({"loi": str(e)}), 409
    return jsonify({"ok": True, "ghi_chu": ghi_chu, "tien_that": tien_that})


@app.post("/api/service/collector/start")
def api_collector_start():
    ma = _danh_sach_ma() or ",".join(config.SYMBOLS)
    cmd = [__import__("sys").executable, "-u", "-m", "research.collect_orderbook",
           "--symbols", ma,
           "--depth", str(_int("depth", 50, 1, 200)),
           "--category", "linear" if _json().get("category", "linear") == "linear" else "spot"]
    sv = dich_vu.get("collector")
    try:
        sv.start(cmd, "thu thap %d ma" % len(ma.split(",")))
    except RuntimeError as e:
        return jsonify({"loi": str(e)}), 409
    return jsonify({"ok": True})


@app.post("/api/service/<ten>/stop")
def api_service_stop(ten: str):
    sv = dich_vu.get(ten)
    if sv is None:
        return jsonify({"loi": "khong co dich vu nay"}), 404
    return jsonify({"da_dung": sv.stop()})


@app.get("/api/service/<ten>")
def api_service(ten: str):
    sv = dich_vu.get(ten)
    if sv is None:
        return jsonify({"loi": "khong co dich vu nay"}), 404
    try:
        since = int(request.args.get("since", 0))
    except ValueError:
        since = 0
    return jsonify(sv.to_dict(since=max(0, since)))


# ==========================================================
# AI policy
# ==========================================================
def _loi_ngan(e: Exception, gioi_han: int = 200) -> str:
    """Thong bao loi gon, da XOA moi khoa bi mat co the lot vao.

    Thu vien HTTP thinh thoang nhet ca header hoac URL day du vao thong bao
    loi. Neu mot ngay nao do khoa nam trong do that, no se di thang ra man
    hinh va vao log trinh duyet. Loc o day re hon nhieu so voi viec tin rang
    dieu do khong bao gio xay ra.
    """
    return _loi_ngan_chuoi("%s: %s" % (type(e).__name__, e), gioi_han)


def _loi_ngan_chuoi(s: str, gioi_han: int = 200) -> str:
    """Cat ngan va xoa moi khoa bi mat co the lot vao mot chuoi bat ky."""
    for gia_tri in env_store.doc_bi_mat_cho_tien_trinh_nay().values():
        if len(gia_tri) >= 8:
            s = s.replace(gia_tri, "***")
    return s[:gioi_han]


def _kho():
    from src import model_store
    return model_store.KhoModel(MODEL_DIR)


@app.get("/api/policy")
def api_policy():
    from src.storage import Storage

    kho = _kho()
    champ = kho.champion_hien_tai()
    phien_ban = []
    for pb in kho.danh_sach():
        m = kho.doc_meta(pb)
        cs = m.get("chi_so", {})
        xao = m.get("chi_so_nhan_xao", {})
        phien_ban.append({
            "phien_ban": pb,
            "la_champion": pb == champ,
            "cong_dat": bool(m.get("cong_dat")),
            "huan_luyen_luc": m.get("huan_luyen_luc"),
            "so_ma": len(m.get("symbols", [])),
            "interval": m.get("interval"),
            "auc": cs.get("auc_tb"),
            "auc_xao": xao.get("auc_tb"),
            "ic": cs.get("ic"),
            "ic_t": cs.get("ic_t"),
            "ic_t_tho": cs.get("ic_t_tho"),
            "ky_vong": cs.get("loi_nhuan_tb"),
            "profit_factor": cs.get("profit_factor"),
            "so_lenh": cs.get("so_lenh"),
            "ty_le_vao_lenh": cs.get("ty_le_vao_lenh"),
            "dau_van_tay": m.get("dau_van_tay"),
        })

    ket_qua_that = {}
    if champ and os.path.exists(config.DB_PATH):
        try:
            ket_qua_that = Storage(config.DB_PATH).thong_ke_policy(champ)
        except Exception:
            ket_qua_that = {}

    # Dau van tay hien tai: neu lech voi champion thi policy dang tu choi mo hinh
    van_tay_ht = None
    if champ:
        m = kho.doc_meta(champ)
        if m.get("cot_dac_trung"):
            from src import model_store
            van_tay_ht = model_store.dau_van_tay(m["cot_dac_trung"], config,
                                                 m.get("max_horizon", 60))

    return jsonify({
        "che_do": config.POLICY_MODE,
        "champion": champ,
        "thong_tin_champion": kho.thong_tin_champion(),
        "van_tay_hien_tai": van_tay_ht,
        "phien_ban": phien_ban[::-1],
        "su_kien": kho.su_kien(25)[::-1],
        "ket_qua_that": ket_qua_that,
        "nguong": {
            "auc_min": config.GATE_POLICY_AUC_MIN,
            "auc_max": config.GATE_POLICY_AUC_MAX,
            "xao_auc_max": config.GATE_POLICY_XAO_AUC_MAX,
            "ic_min": config.GATE_POLICY_IC_MIN,
            "ic_t_min": config.GATE_POLICY_IC_T_MIN,
            "min_lenh": config.GATE_POLICY_MIN_LENH,
            "ky_vong_min": config.GATE_POLICY_KY_VONG_MIN,
            "pf_min": config.GATE_POLICY_PF_MIN,
            "ty_le_vao_max": config.GATE_POLICY_TY_LE_VAO_MAX,
            "ev_min": config.POLICY_EV_MIN,
            "min_ma": config.POLICY_MIN_MA,
        },
    })


@app.get("/api/policy/the/<phien_ban>")
def api_policy_the(phien_ban: str):
    pb = _phien_ban(phien_ban)
    kho = _kho()
    p = os.path.join(kho.thu_muc, pb, "the_mo_hinh.md")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return jsonify({"phien_ban": pb, "the": f.read(),
                            "meta": kho.doc_meta(pb)})
    meta = kho.doc_meta(pb)
    if not meta:
        return jsonify({"loi": "khong co phien ban nay"}), 404
    return jsonify({"phien_ban": pb, "the": "", "meta": meta})


@app.post("/api/policy/thang-cap")
def api_policy_thang_cap():
    pb = _phien_ban(_json().get("phien_ban", ""))
    kho = _kho()
    meta = kho.doc_meta(pb)
    if not meta:
        return jsonify({"loi": "khong co phien ban nay"}), 404

    # Thang cap mot mo hinh TRUOT cong la hanh dong co chu dich, khong phai loi
    # bam nham - nen no doi mot co rieng va duoc ghi vao nhat ky su kien.
    if not meta.get("cong_dat") and not _json().get("toi_chac_chan"):
        return jsonify({
            "loi": "Phien ban nay KHONG qua cong thong ke luc huan luyen.",
            "can_xac_nhan": True,
        }), 428

    ly_do = str(_json().get("ly_do", ""))[:200] or "thang cap tu bang dieu khien"
    if not meta.get("cong_dat"):
        ly_do = "EP THANG CAP (khong qua cong): " + ly_do
    try:
        kho.thang_cap(pb, ly_do)
    except FileNotFoundError as e:
        return jsonify({"loi": str(e)}), 404
    return jsonify({"ok": True, "champion": kho.champion_hien_tai()})


@app.post("/api/policy/ha-cap")
def api_policy_ha_cap():
    ly_do = str(_json().get("ly_do", ""))[:200] or "ha cap tu bang dieu khien"
    moi = _kho().ha_cap(ly_do)
    return jsonify({"ok": True, "champion": moi})


@app.get("/api/policy/du-doan")
def api_policy_du_doan():
    rows = _doc_db(
        "SELECT ts, bar_ts, symbol, phien_ban, che_do, action, strength, "
        "p_long, p_short, ev_long, ev_short, ret_thuc, nhan_xong, ly_do "
        "FROM policy_predictions ORDER BY id DESC LIMIT 200")
    return jsonify(rows)


# ==========================================================
# Bo loc meta-label
# ==========================================================
def _kho_meta():
    from src.meta_continual import KhoMeta
    return KhoMeta()


@app.get("/api/meta")
def api_meta():
    """Trang thai bo loc: champion, cac phien ban, va MOC SO SANH.

    Moi con so o day deu di kem ban "khong loc". Mot bo loc chi co gia tri neu
    no hon viec nghe het moi tin hieu - AUC dep ma ky vong khong hon thi no chi
    la mot lop phuc tap them vao lam ta tuong minh dang duoc bao ve.
    """
    kho = _kho_meta()
    champ = kho.champion_hien_tai()
    phien_ban = []
    for pb in kho.danh_sach():
        m = kho.doc_meta(pb)
        cs = m.get("chi_so", {})
        xao = m.get("chi_so_nhan_xao", {})
        goc = m.get("goc_toan_bo_lich_su", {})
        phien_ban.append({
            "phien_ban": pb,
            "la_champion": pb == champ,
            "cong_dat": bool(m.get("cong_dat")),
            "huan_luyen_luc": m.get("huan_luyen_luc"),
            "chien_luoc_nguon": m.get("chien_luoc_nguon", []),
            "nguong": m.get("nguong"),
            "cach_chon_nguong": m.get("cach_chon_nguong"),
            "auc": cs.get("auc"),
            "auc_xao": xao.get("auc"),
            "ky_vong": cs.get("ky_vong"),
            "ky_vong_khong_loc": cs.get("ky_vong_khong_loc"),
            "cai_thien": cs.get("cai_thien"),
            "pf": cs.get("profit_factor"),
            "pf_khong_loc": cs.get("profit_factor_khong_loc"),
            "ty_le_giu": cs.get("ty_le_giu"),
            "so_lenh_giu": cs.get("so_lenh_giu"),
            "so_lenh_goc": cs.get("so_lenh_goc"),
            "ty_le_lai_co_so": goc.get("ty_le_lai_co_so"),
            "p_hoa_von": goc.get("p_hoa_von"),
        })

    return jsonify({
        "champion": champ,
        "thong_tin_champion": kho.thong_tin_champion(),
        "chien_luoc_mac_dinh": list(config.META_CHIEN_LUOC),
        "bat": getattr(config, "META_BAT", True),
        "phien_ban": phien_ban[::-1],
        "su_kien": kho.su_kien(20)[::-1],
        "nguong_cong": {
            "auc_min": config.GATE_META_AUC_MIN,
            "auc_max": config.GATE_META_AUC_MAX,
            "xao_auc_max": config.GATE_META_XAO_AUC_MAX,
            "ty_le_giu_min": config.GATE_META_TY_LE_GIU_MIN,
            "ty_le_giu_max": config.GATE_META_TY_LE_GIU_MAX,
            "ky_vong_min": config.GATE_META_KY_VONG_MIN,
            "cai_thien_min": config.GATE_META_CAI_THIEN_MIN,
            "pf_min": config.GATE_META_PF_MIN,
            "min_lenh_giu": config.GATE_META_MIN_LENH_GIU,
        },
    })


@app.get("/api/meta/the/<phien_ban>")
def api_meta_the(phien_ban: str):
    pb = _phien_ban(phien_ban)
    kho = _kho_meta()
    p = os.path.join(kho.thu_muc, pb, "the_mo_hinh.md")
    meta = kho.doc_meta(pb)
    if not meta:
        return jsonify({"loi": "khong co phien ban nay"}), 404
    the = ""
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            the = f.read()
    return jsonify({"phien_ban": pb, "the": the, "meta": meta})


@app.post("/api/meta/thang-cap")
def api_meta_thang_cap():
    pb = _phien_ban(_json().get("phien_ban", ""))
    kho = _kho_meta()
    meta = kho.doc_meta(pb)
    if not meta:
        return jsonify({"loi": "khong co phien ban nay"}), 404

    # Thang cap mot bo loc TRUOT cong la hanh dong co chu dich. No dat mot mo
    # hinh chua chung minh duoc gi vao duong di cua lenh that, noi no duoc phep
    # CHAN tin hieu - nen no doi mot co rieng va duoc ghi vao nhat ky su kien.
    if not meta.get("cong_dat") and not _json().get("toi_chac_chan"):
        return jsonify({"loi": "Bo loc nay KHONG qua cong thong ke luc huan luyen.",
                        "can_xac_nhan": True}), 428

    ly_do = str(_json().get("ly_do", ""))[:200] or "thang cap tu bang dieu khien"
    if not meta.get("cong_dat"):
        ly_do = "EP THANG CAP (khong qua cong): " + ly_do
    try:
        kho.thang_cap(pb, ly_do)
    except FileNotFoundError as e:
        return jsonify({"loi": str(e)}), 404
    return jsonify({"ok": True, "champion": kho.champion_hien_tai()})


@app.post("/api/meta/ha-cap")
def api_meta_ha_cap():
    ly_do = str(_json().get("ly_do", ""))[:200] or "ha cap tu bang dieu khien"
    return jsonify({"ok": True, "champion": _kho_meta().ha_cap(ly_do)})


# ==========================================================
# Cau hinh
# ==========================================================
@app.get("/api/config")
def api_config():
    return jsonify({
        "khoa": env_store.mo_ta_khoa(),
        "bi_mat": env_store.trang_thai_bi_mat(),
        # Bang chon san da ve nhung khoa nay roi - gui kem de UI khoi ve lai
        # o bang .env chung, roi hai cho lech nhau sau mot lan luu.
        "khoa_san": list(env_store.KHOA_SAN),
        "duong_dan_env": env_store.ENV_PATH,
        "chi_so_chi_doc": {
            "FEE_TAKER": config.FEE_TAKER,
            "SLIPPAGE": config.SLIPPAGE,
            "MIN_SIGNAL_STRENGTH": config.MIN_SIGNAL_STRENGTH,
            "MAX_CONSECUTIVE_LOSSES": config.MAX_CONSECUTIVE_LOSSES,
            "GATE_MIN_SHARPE": config.GATE_MIN_SHARPE,
            "GATE_MIN_PROFIT_FACTOR": config.GATE_MIN_PROFIT_FACTOR,
        },
    })


@app.post("/api/config")
def api_config_luu():
    thay_doi = _json().get("thay_doi") or {}
    if not isinstance(thay_doi, dict) or not thay_doi:
        return jsonify({"loi": "khong co gi de luu"}), 400
    kq = env_store.ghi({str(k): str(v) for k, v in thay_doi.items()})
    if not kq.get("ok"):
        return jsonify(kq), 400
    return jsonify(kq)


@app.post("/api/config/bi-mat")
def api_bi_mat_luu():
    """Dat khoa API. MOT CHIEU: khong route nao doc gia tri khoa ra.

    Chuoi rong = xoa khoa. Ket qua chi liet ke TEN khoa da doi, khong bao gio
    gia tri - ke ca trong thong bao loi.
    """
    thay_doi = _json().get("thay_doi") or {}
    if not isinstance(thay_doi, dict) or not thay_doi:
        return jsonify({"loi": "khong co gi de luu"}), 400
    kq = env_store.ghi_bi_mat({str(k): str(v) for k, v in thay_doi.items()})
    if not kq.get("ok"):
        return jsonify(kq), 400
    _xoa_dem_ket_noi()      # khoa vua doi - trang thai cu khong con dung nua
    return jsonify(kq)


class _CauHinhVuaDoc:
    """Cau hinh doc lai TU .env ngay luc goi, thay cho ban `config` da nap.

    config.py goi load_dotenv() mot lan luc import, nen tien trinh web giu ban
    cau hinh tu luc khoi dong. Khong co lop nay thi nguoi dung sua SYMBOLS xong
    the o Tong quan van hien ma cu, va bam doi san xong nhan tren dau van ghi
    san cu - trong ca hai truong hop ho da luu dung, chi la bang khong biet.

    Thuoc tinh nao khong co trong .env thi roi ve `config` - de client san va
    cac route van thay du moi thu chung can (FEE_TAKER, GATE_*, ...).
    """

    def __init__(self):
        self._env = dict(env_store.doc_gia_tri())
        self._env.update(env_store.doc_bi_mat_cho_tien_trinh_nay())

    def __getattr__(self, ten):
        v = self._env.get(ten)
        if v is None or v == "":
            # Khoa bi mat chua dat: tra chuoi rong chu khong roi ve config, vi
            # roi ve se lay nham khoa cu tu luc khoi dong va bao "ket noi
            # duoc" cho mot khoa nguoi dung vua xoa.
            if ten in env_store.KHOA_BI_MAT:
                return ""
            return getattr(config, ten)
        if ten == "EXCHANGE":
            # config.py chuan hoa khoa nay luc nap; .env sua tay co the con
            # "OKX " hoac "Bybit". Khong chuan hoa o day thi tra cuu theo ten
            # san truot mot cach im lang.
            return v.strip().lower()
        return _ep_kieu(v, getattr(config, ten, None))


def _ep_kieu(v: str, mau):
    """Ep chuoi tu .env ve DUNG KIEU ma config.py dung cho khoa do.

    Lay kieu tu chinh gia tri trong config.py chu khong tu mot bang liet ke:
    bang liet ke se lac hau ngay lan dau ai do them mot khoa moi, va kieu
    hong o day khong bao loi ma di tiep - `len(SYMBOLS)` tren mot chuoi van
    chay, chi la tra ve so KY TU thay vi so ma.
    """
    if isinstance(mau, bool):                      # phai kiem truoc int
        return v.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(mau, list):
        return [x.strip() for x in v.split(",") if x.strip()]
    if isinstance(mau, (int, float)):
        try:
            return type(mau)(v)
        except ValueError:
            return mau
    return v


def _thieu_khoa(cfg) -> List[str]:
    """Ten cac khoa bat buoc cua san dang chon ma chua dat."""
    can = env_store.KHOA_BAT_BUOC.get(cfg.EXCHANGE, ())
    return [k for k in can if not getattr(cfg, k, "")]


def _xoa_dem_ket_noi() -> None:
    """Goi sau khi khoa doi. Khong xoa thi bang con bao trang thai cu toi 90
    giay, va nguoi dung vua sua xong se tuong minh sua chua an."""
    with _KET_NOI_KHOA:
        _KET_NOI["luc"], _KET_NOI["ket_qua"] = 0.0, None


@app.post("/api/san/kiem-tra")
def api_san_kiem_tra():
    """Thu ket noi san bang cau hinh DANG CO TRONG .env, tra ve tung buoc mot.

    Tach lam hai buoc vi hai buoc hong vi hai ly do khac han nhau:

      cong khai  - lay gia. Hong = sai ten ma, chan mang, hoac sai san.
      rieng tu   - lay so du. Hong = sai khoa, sai passphrase, sai quyen,
                   hoac dang tro vao mainnet bang khoa demo (va nguoc lai).

    Bao duoc "cong khai OK, rieng tu hong" la khac biet giua "mang cua ban co
    van de" va "khoa cua ban co van de" - hai huong sua hoan toan khac nhau.
    """
    cfg = _CauHinhVuaDoc()
    ma = _symbol(config.SYMBOLS[0] if config.SYMBOLS else "BTCUSDT")
    ra = {
        "san": cfg.EXCHANGE,
        "ma": ma,
        "category": getattr(cfg, "CATEGORY", "spot"),
        "demo": bool(getattr(cfg, "OKX_DEMO" if cfg.EXCHANGE == "okx"
                             else "BYBIT_TESTNET", True)),
        "cong_khai": {"ok": False, "chi_tiet": ""},
        "rieng_tu": {"ok": False, "chi_tiet": ""},
    }

    thieu = _thieu_khoa(cfg)
    ra["thieu_khoa"] = thieu
    if thieu:
        ra["rieng_tu"]["chi_tiet"] = "chua dat: " + ", ".join(thieu)

    try:
        client = build_client(cfg)
    except Exception as e:
        ra["cong_khai"]["chi_tiet"] = _loi_ngan(e)
        return jsonify(ra)

    try:
        gia = client.get_last_price(ma)
        if gia:
            ra["cong_khai"] = {"ok": True, "chi_tiet": "gia %s = %s" % (ma, gia)}
        else:
            ra["cong_khai"]["chi_tiet"] = ("san khong tra ve gia cho %s - kiem tra "
                                           "ten ma va CATEGORY" % ma)
    except Exception as e:
        ra["cong_khai"]["chi_tiet"] = _loi_ngan(e)

    if thieu:
        return jsonify(ra)

    # Dung kiem_tra_ket_noi() chu khong phai get_equity(): get_equity nuot moi
    # loi thanh None cho bot chay tiep duoc, nen "khoa sai" va "tai khoan rong"
    # deu ra cung mot ket qua. O day ta can chinh cai ma loi do.
    try:
        ra["rieng_tu"] = client.kiem_tra_ket_noi()
        _xoa_dem_ket_noi()   # nguoi dung vua thu that -> bang cap nhat theo
    except Exception as e:
        ra["rieng_tu"]["chi_tiet"] = _loi_ngan(e)
    else:
        ra["rieng_tu"]["chi_tiet"] = _loi_ngan_chuoi(ra["rieng_tu"].get("chi_tiet", ""))

    return jsonify(ra)


@app.get("/api/san")
def api_san():
    """Moi thu bang chon san can, trong mot lan goi.

    Gom ca trang thai khoa cua CA HAI san chu khong rieng san dang chon: cau
    hoi that su cua nguoi dung la "toi doi sang OKX duoc chua", va tra loi no
    can biet khoa OKX da co hay chua NGAY CA KHI dang chay Bybit.
    """
    cfg = _CauHinhVuaDoc()
    bi_mat = env_store.trang_thai_bi_mat()
    gia_tri = env_store.doc_gia_tri()

    san = {}
    for ten, can in env_store.KHOA_BAT_BUOC.items():
        san[ten] = {
            "khoa": [{"ten": k, "da_dat": bi_mat.get(k, False)} for k in can],
            "san_sang": all(bi_mat.get(k) for k in can),
        }
    san["bybit"]["demo"] = gia_tri.get("BYBIT_TESTNET", "true")
    san["bybit"]["khoa_demo"] = "BYBIT_TESTNET"
    san["okx"]["demo"] = gia_tri.get("OKX_DEMO", "true")
    san["okx"]["khoa_demo"] = "OKX_DEMO"
    san["okx"]["td_mode"] = gia_tri.get("OKX_TD_MODE", "cross")

    return jsonify({
        "dang_chon": cfg.EXCHANGE,
        "category": gia_tri.get("CATEGORY", "spot"),
        "bot_dang_chay": dich_vu.get("bot").dang_chay,
        "san": san,
    })


@app.post("/api/san/chon")
def api_san_chon():
    """Doi san. Chan lai neu san DANG dung con vi the/lenh mo.

    Vi sao phai chan: `reconcile()` chi doc vi the tu san dang cau hinh, khong
    doi chieu voi mot so sach rieng. Doi sang OKX trong khi con mot vi the tren
    Bybit thi vong sau bot thay \"khong co vi the nao\" va chay tiep binh thuong
    - con cai vi the kia nam lai khong ai quan stop, khong ca luoi _ep_stop.
    Bot khong he bao loi, vi theo goc nhin moi cua no thi khong co gi sai ca.

    Khong co khoa cho san dang dung thi bo qua phep kiem - khong khoa thi cung
    khong the co vi the nao de bo roi.
    """
    moi = str(_json().get("san", "")).strip().lower()
    if moi not in env_store.KHOA_BAT_BUOC:
        return jsonify({"loi": "san khong hop le (chi nhan bybit|okx)"}), 400

    cu = _CauHinhVuaDoc().EXCHANGE
    if moi == cu:
        return jsonify({"ok": True, "da_doi": False, "dang_chon": moi,
                        "ghi_chu": "van dang o %s" % moi.upper()})

    if not _json().get("xac_nhan"):
        vuong = _vuong_mac_tren_san(cu)
        if vuong:
            return jsonify({
                "loi": "San %s dang con %s. Doi san bay gio la bo roi chung: "
                       "bot moi se khong nhin thay, khong quan stop, va cung "
                       "khong bao loi. Dong chung tren %s truoc da."
                       % (cu.upper(), " va ".join(vuong), cu.upper()),
                "can_xac_nhan": True,
                "vuong_mac": vuong,
            }), 409

    kq = env_store.ghi({"EXCHANGE": moi})
    if not kq.get("ok"):
        return jsonify(kq), 400
    _xoa_dem_ket_noi()      # san khac thi khoa khac
    return jsonify({"ok": True, "da_doi": True, "dang_chon": moi,
                    "bot_dang_chay": dich_vu.get("bot").dang_chay})


def _vuong_mac_tren_san(ten_san: str) -> List[str]:
    """Vi the/lenh cho dang co tren mot san. Rong = khong co gi de mat.

    Doc that bai cung tra ve rong CO CHU DICH: khong doc duoc san thi ta khong
    biet gi ca, va chan nguoi dung lai bang mot loi mang chi khien ho bam
    \"xac nhan\" theo phan xa - lam hong dung cai canh bao nay de bao ve.
    """
    class _Cfg(_CauHinhVuaDoc):
        EXCHANGE = ten_san

    cfg = _Cfg()
    if any(not getattr(cfg, k, "") for k in env_store.KHOA_BAT_BUOC[ten_san]):
        return []
    try:
        client = build_client(cfg)
        vuong = []
        vi_the = client.get_open_positions()
        if vi_the:
            vuong.append("%d vi the mo" % len(vi_the))
        lenh = client.get_open_orders()
        if lenh:
            vuong.append("%d lenh cho" % len(lenh))
        return vuong
    except Exception as e:
        logger.warning("Khong kiem tra duoc vi the tren %s: %s", ten_san, e)
        return []


@app.get("/api/kho-luat")
def api_kho_luat():
    """Kho chien luoc luat + so tin hieu che do bong 30 ngay qua.

    CHI DOC. Thang cap/ha cap co y chi lam duoc bang run_luat.py: do la quyet
    dinh nen phai go tay mot lenh, khong phai mot cu bam nham tren trinh duyet.
    """
    import time as _t
    try:
        from src.strategies import kho_luat as kl
        kho = kl.KhoLuat()
        muc = []
        tu = _t.time() - 30 * 86400
        for m in kho.tat_ca().values():
            ten = m["ten"]
            bc = m.get("bang_chung") or {}
            diem = None
            if m.get("trang_thai") == kl.BONG:
                try:
                    from src.cham_diem_bong import danh_gia
                    from src.storage import Storage
                    diem = danh_gia(Storage(), ten)
                except Exception:
                    diem = None
            tin_hieu = {}
            if m.get("trang_thai") == kl.BONG:
                tin_hieu = {r["action"]: r["n"] for r in _doc_db(
                    "SELECT action, COUNT(*) AS n FROM shadow_signals "
                    "WHERE chien_luoc = ? AND ts >= ? GROUP BY action", (ten, tu))}
            muc.append({
                "ten": ten,
                "trang_thai": m.get("trang_thai"),
                "mo_ta": (m.get("spec") or {}).get("mo_ta", ""),
                "ngay_o_bong": round(kho.so_ngay_o_bong(ten), 1),
                "ngay_bong_can": kl.NGAY_BONG_TOI_THIEU,
                "sharpe_min": bc.get("sharpe_min"),
                "so_phep_thu": bc.get("so_phep_thu_luy_ke"),
                "dang_bat": ten in config.ENABLED_STRATEGIES,
                "tin_hieu_bong": tin_hieu,
                "diem_bong": diem,
            })
        return jsonify({"muc": sorted(muc, key=lambda x: x["ten"])})
    except Exception as e:
        return jsonify({"muc": [], "loi": str(e)})


@app.post("/api/kho-luat/<hanh_dong>")
def api_kho_luat_doi(hanh_dong: str):
    """Thang cap / ha cap / loai bo mot chien luoc luat.

    Thang cap len CHU_DONG la buoc dua mot luat vao duong ra lenh that, nen no
    doi go dung cau xac nhan - giong het nut bat bot bang tien that. Cac buoc
    con lai (len bong, va moi chieu XUONG) khong doi gi: dua vao che do bong
    khong dung den tien, con duong lui thi phai luon thong.
    """
    from src.strategies import kho_luat as kl

    ten = "".join(c for c in str(_json().get("ten", "")) if c.isalnum() or c == "_")[:60]
    ly_do = str(_json().get("ly_do", ""))[:200] or "thao tac tu bang dieu khien"
    kho = kl.KhoLuat()
    muc = kho.lay(ten)
    if muc is None:
        return jsonify({"loi": "khong co '%s' trong kho" % ten}), 404

    try:
        if hanh_dong == "thang-cap":
            len_chu_dong = muc.get("trang_thai") == kl.BONG
            if len_chu_dong and str(_json().get("xac_nhan", "")).strip() != CAU_XAC_NHAN:
                return jsonify({
                    "loi": "Thang cap '%s' len chu_dong la cho phep no sinh lenh "
                           "that trong ensemble." % ten,
                    "can_xac_nhan": True, "cau_xac_nhan": CAU_XAC_NHAN,
                }), 428
            from src.storage import Storage
            moi = kho.thang_cap(ten, ly_do, ep=bool(_json().get("ep")),
                                storage=Storage())
        elif hanh_dong == "ha-cap":
            moi = kho.ha_cap(ten, ly_do)
        elif hanh_dong == "loai-bo":
            moi = kho.loai_bo(ten, ly_do)
        else:
            return jsonify({"loi": "hanh dong khong hop le"}), 400
    except kl.KhoLuatLoi as e:
        return jsonify({"loi": str(e)}), 409

    ra = {"ok": True, "ten": ten, "trang_thai": moi["trang_thai"]}
    if moi["trang_thai"] == kl.CHU_DONG and ten not in config.ENABLED_STRATEGIES:
        ra["nhac"] = ("'%s' da duoc phep chay nhung CHUA chay. Them ten no vao "
                      "ENABLED_STRATEGIES o tab Cau hinh roi khoi dong lai bot." % ten)
    if moi["trang_thai"] != kl.CHU_DONG and ten in config.ENABLED_STRATEGIES:
        ra["nhac"] = ("CANH BAO: '%s' van con trong ENABLED_STRATEGIES - bo ra o "
                      "tab Cau hinh roi khoi dong lai bot, neu khong no van chay." % ten)
    return jsonify(ra)


# Danh sach trang phia web. Bot con mot danh sach trang RIENG
# (main.TradingBot.LENH_CHO_PHEP) va no moi la cai quyet dinh - hai lop nay co
# y trung lap: web co the bi sua, bot thi tu bao ve minh.
LENH_CHO_PHEP = {
    "reset_breaker": "Reset circuit breaker",
    "nap_lai_kho_luat": "Nap lai chien luoc luat che do bong",
}


@app.post("/api/lenh/<lenh>")
def api_gui_lenh(lenh: str):
    """Xep mot lenh dieu khien cho bot doc o vong lap sau.

    Bot doc lenh qua DB chu khong qua mot cong mang: hai tien trinh da dung
    chung DB roi, va mo them mot cong nghe lenh la mo them mot be mat tan cong.
    Lenh co han 10 phut - bot tat vai ngay roi bat lai khong nen thuc hien mot
    lenh xep tu ba ngay truoc.
    """
    if lenh not in LENH_CHO_PHEP:
        return jsonify({"loi": "lenh khong hop le"}), 400
    if not dich_vu.get("bot").dang_chay:
        return jsonify({"loi": "Bot khong chay - lenh se khong ai doc. "
                               "Bat bot truoc."}), 409
    try:
        from src.storage import Storage
        id_ = Storage().them_lenh(lenh, {"tu": "web"})
    except Exception as e:
        return jsonify({"loi": str(e)}), 500
    return jsonify({"ok": True, "id": id_, "nhan": LENH_CHO_PHEP[lenh],
                    "ghi_chu": "Bot se doc lenh o vong quyet dinh ke tiep."})


@app.get("/api/gia-thuyet")
def api_gia_thuyet():
    """Noi dung research/gia_thuyet.json + bo dem phep thu luy ke."""
    duong_dan = os.path.join(BASE_DIR, "research", "gia_thuyet.json")
    noi_dung, so = "[]", 0
    if os.path.exists(duong_dan):
        with open(duong_dan, encoding="utf-8") as f:
            noi_dung = f.read()
        try:
            so = len(json.loads(noi_dung))
        except ValueError:
            so = 0

    bo_dem = {"so_lan_thu": 0, "lich_su": []}
    try:
        from research import strategy_lab
        bo_dem = strategy_lab.doc_bo_dem()
    except Exception as e:
        bo_dem["loi"] = str(e)
    return jsonify({"noi_dung": noi_dung, "so_gia_thuyet": so, "bo_dem": bo_dem})


@app.post("/api/gia-thuyet")
def api_gia_thuyet_luu():
    """Ghi lai file gia thuyet, sau khi KIEM TRA TUNG SPEC.

    Kiem tra o day dung chinh bo kiem tra ma Strategy Lab dung
    (rule_spec.kiem_tra_spec), nen mot spec hong bi bat ngay luc soan chu khong
    phai luc chay - va quan trong hon, khong ton mot phep thu vao bo dem.
    """
    from src.strategies.rule_spec import SpecKhongHopLe, kiem_tra_spec

    raw = _json().get("noi_dung", "")
    if len(raw) > 200_000:
        return jsonify({"loi": "noi dung qua dai"}), 400
    try:
        specs = json.loads(raw)
    except ValueError as e:
        return jsonify({"loi": "JSON khong hop le: %s" % e}), 400
    if not isinstance(specs, list):
        return jsonify({"loi": "phai la mot mang JSON cac gia thuyet"}), 400
    if len(specs) > 50:
        return jsonify({"loi": "toi da 50 gia thuyet moi lan"}), 400

    loi = {}
    for i, sp in enumerate(specs):
        try:
            kiem_tra_spec(sp)
        except SpecKhongHopLe as e:
            loi[str(i)] = str(e)
    if loi:
        return jsonify({"loi": "co spec khong hop le", "chi_tiet": loi}), 400

    duong_dan = os.path.join(BASE_DIR, "research", "gia_thuyet.json")
    with open(duong_dan, "w", encoding="utf-8") as f:
        json.dump(specs, f, ensure_ascii=False, indent=2)
    return jsonify({"ok": True, "so_gia_thuyet": len(specs)})


@app.get("/api/lab-ket-qua")
def api_lab_ket_qua():
    p = os.path.join(REPORT_DIR, "strategy_lab.json")
    if not os.path.exists(p):
        return jsonify({"co": False})
    try:
        with open(p, encoding="utf-8") as f:
            return jsonify({"co": True, **json.load(f)})
    except Exception as e:
        return jsonify({"co": False, "loi": str(e)})


# ==========================================================
# Bao cao
# ==========================================================
@app.get("/api/reports")
def api_reports():
    os.makedirs(REPORT_DIR, exist_ok=True)
    out = []
    for path in sorted(glob.glob(os.path.join(REPORT_DIR, "*.html")), reverse=True):
        out.append({
            "name": os.path.basename(path),
            "size_kb": round(os.path.getsize(path) / 1024),
            "created": time.strftime("%Y-%m-%d %H:%M",
                                     time.localtime(os.path.getmtime(path))),
        })
    for path in sorted(glob.glob(os.path.join(REPORT_DIR, "*.csv")), reverse=True):
        out.append({
            "name": os.path.basename(path), "csv": True,
            "size_kb": round(os.path.getsize(path) / 1024),
            "created": time.strftime("%Y-%m-%d %H:%M",
                                     time.localtime(os.path.getmtime(path))),
        })
    return jsonify(out[:60])


@app.get("/report/<path:name>")
def serve_report(name: str):
    # Chi phuc vu file nam TRONG thu muc bao cao - basename() chan duong dan di len
    safe = os.path.basename(name)
    if not safe.endswith((".html", ".csv")):
        return "khong hop le", 400
    path = os.path.join(REPORT_DIR, safe)
    if not os.path.isfile(path):
        return "khong tim thay bao cao", 404
    return send_file(path)


# ==========================================================
# Theo doi
# ==========================================================
@app.get("/api/monitor")
def api_monitor():
    if not os.path.exists(config.DB_PATH):
        return jsonify({"co_db": False, "decisions": [], "trades": [],
                        "equity": [], "orders": []})
    return jsonify({
        "co_db": True,
        "decisions": _doc_db(
            "SELECT ts, symbol, regime, action, strength, llm_veto, executed, reason "
            "FROM decisions ORDER BY ts DESC LIMIT 80"),
        "trades": _doc_db(
            "SELECT symbol, strategy, side, qty, entry_price, exit_price, pnl, "
            "pnl_pct, exit_reason, exit_ts FROM trades ORDER BY exit_ts DESC LIMIT 80"),
        "orders": _doc_db(
            "SELECT ts, symbol, side, qty, price, stop_loss, take_profit, strategy, "
            "dry_run, status FROM orders ORDER BY ts DESC LIMIT 50"),
        "equity": _doc_db(
            "SELECT ts, equity, heat, open_positions FROM equity_snapshots "
            "ORDER BY ts DESC LIMIT 400")[::-1],
    })


@app.get("/api/log")
def api_log():
    try:
        n = max(20, min(500, int(request.args.get("n", 200))))
    except ValueError:
        n = 200
    return jsonify({"dong": _log_tail(n)})
