"""
Cau hinh trung tam - AI Trade Bot v2.

Nguyen tac:
  - Moi gia tri nhay cam (API key/secret) doc tu .env, KHONG hardcode.
  - Mac dinh moi thu o che do AN TOAN: testnet + dry-run + LLM tat.
  - Chi bat tung thu mot cach co chu dich sau khi da backtest va paper trade.

Ghi chu: comment va log message trong code deu khong dau tieng Viet
de tranh loi encoding khi chay tren console Windows.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        return default


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ==========================================================
# Ket noi san
# ==========================================================
EXCHANGE = os.getenv("EXCHANGE", "bybit").strip().lower()   # "bybit" | "okx"
# Client thuc te duoc chon o src/exchange.py:build_client() theo bien nay -
# doi san chi can sua .env, khong phai sua main.py/run_backtest.py.

BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")
BYBIT_TESTNET = _bool("BYBIT_TESTNET", True)

# OKX bat buoc them PASSPHRASE (dat luc tao API key) ma Bybit khong co.
# OKX_DEMO tuong duong BYBIT_TESTNET - true = tien gia, KHONG phai tien that.
OKX_API_KEY = os.getenv("OKX_API_KEY", "")
OKX_API_SECRET = os.getenv("OKX_API_SECRET", "")
OKX_API_PASSPHRASE = os.getenv("OKX_API_PASSPHRASE", "")
OKX_DEMO = _bool("OKX_DEMO", True)
OKX_TD_MODE = os.getenv("OKX_TD_MODE", "cross")  # margin cho SWAP: cross|isolated (spot luon "cash")

# NOI LAY DU LIEU LICH SU, tach roi khoi noi GIAO DICH.
#
# Testnet co so lenh rieng va thanh khoan rat mong: gia testnet lech gia that
# trung binh ~1.5% va co luc gan 5%. Voi stop 2xATR (~4%) thi sai so du lieu
# con lon hon ca khoang cach stop - backtest tren do khong do duoc gi.
#
# Nguy hiem hon: thanh khoan mong lam gia troi xa roi bat lai ve gia tham chieu,
# tao ra mot bien do mean-reversion GIA khong ton tai tren thi truong that.
#
# Vi vay: giao dich co the o testnet, nhung du lieu lich su LUON lay tu mainnet.
# Kline la du lieu cong khai, khong can API key.
DATA_TESTNET = _bool("DATA_TESTNET", False)

# ==========================================================
# LLM (giai doan 4 - mac dinh TAT)
# ==========================================================
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-4-5")
ENABLE_LLM_VETO = _bool("ENABLE_LLM_VETO", False)
ENABLE_NIGHTLY_JOURNAL = _bool("ENABLE_NIGHTLY_JOURNAL", False)
# Neu LLM loi/timeout: True = van cho giao dich (fail-open).
# Ly do: tin hieu ky thuat moi la nguon alpha chinh, LLM chi la lop loc phu.
LLM_FAIL_OPEN = _bool("LLM_FAIL_OPEN", True)
LLM_TIMEOUT_SECONDS = _int("LLM_TIMEOUT_SECONDS", 20)
# Cau hoi veto la ve boi canh thi truong, doi cham hon nhip goi cua bot nhieu.
# 0 = tat cache (hoi lai moi ma moi vong - ton tien va cham).
LLM_VETO_CACHE_SECONDS = _int("LLM_VETO_CACHE_SECONDS", 900)

# ==========================================================
# Canh bao Telegram (mac dinh TAT)
#
# Bot chay tren may ca nhan thi log nam tren may ca nhan - tuc la khong ai
# biet gi cho den luc mo may ra xem. Xem src/notifier.py.
# Lay token: chat voi @BotFather. Lay chat id: chat voi @userinfobot.
# ==========================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ENABLE_TELEGRAM = _bool("ENABLE_TELEGRAM", False)
TELEGRAM_TIMEOUT_SECONDS = _int("TELEGRAM_TIMEOUT_SECONDS", 5)
# Bao moi lenh mo/dong. Tat neu chay nhieu ma va thay on.
TELEGRAM_BAO_TUNG_LENH = _bool("TELEGRAM_BAO_TUNG_LENH", True)

# ==========================================================
# Che do chay
# ==========================================================
DRY_RUN = _bool("DRY_RUN", True)          # True = khong gui lenh that
ALLOW_SHORT = _bool("ALLOW_SHORT", False)  # spot: False. futures: True

# ==========================================================
# Thi truong theo doi
# ==========================================================
SYMBOLS = [s.strip().upper() for s in
           os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT").split(",") if s.strip()]

# Chien luoc duoc bat. Kiem dinh 2026-09 tren du lieu mainnet 4.5 nam:
#   breakout 4H        OOS PF 1.12 tren 3/4 ma  <- ung vien duy nhat
#   trend_following    bien do am
#   mean_reversion     bien do am (edge duong truoc do la artifact cua testnet)
# De ca ba chay chung nghia la lay trung binh cua hai cai lo va mot cai lai.
ENABLED_STRATEGIES = [s.strip() for s in
                      os.getenv("ENABLED_STRATEGIES",
                                "trend_following,mean_reversion,breakout").split(",")
                      if s.strip()]
CATEGORY = os.getenv("CATEGORY", "spot")   # "spot" | "linear"
KLINE_INTERVAL = os.getenv("KLINE_INTERVAL", "60")  # phut
LOOKBACK_BARS = _int("LOOKBACK_BARS", 400)
LOOP_INTERVAL_SECONDS = _int("LOOP_INTERVAL_SECONDS", 300)

# ==========================================================
# Quan ly rui ro (Nang cap 3) - co dinh RUI RO moi lenh,
# khong co dinh gia tri lenh
# ==========================================================
RISK_PER_TRADE = _float("RISK_PER_TRADE", 0.0075)   # 0.75% von cho moi lenh
ATR_PERIOD = 14
ATR_STOP_MULT = _float("ATR_STOP_MULT", 2.0)
ATR_TP_MULT = _float("ATR_TP_MULT", 3.0)            # R:R = 1.5
MAX_PORTFOLIO_HEAT = _float("MAX_PORTFOLIO_HEAT", 0.03)  # tong rui ro dang mo
MAX_OPEN_POSITIONS = _int("MAX_OPEN_POSITIONS", 3)
MAX_POSITIONS_PER_CLUSTER = _int("MAX_POSITIONS_PER_CLUSTER", 1)
MAX_POSITION_NOTIONAL_PCT = _float("MAX_POSITION_NOTIONAL_PCT", 0.25)

# Tran tuong quan: cac coin cung cum duoc coi la MOT lenh
CORRELATION_CLUSTERS = {
    "BTCUSDT": "major",
    "ETHUSDT": "major",
    "SOLUSDT": "major",
    "BNBUSDT": "major",
}
DEFAULT_CLUSTER = "alt"

# ==========================================================
# Circuit breakers (Nang cap 7)
# ==========================================================
MAX_DAILY_DRAWDOWN = _float("MAX_DAILY_DRAWDOWN", 0.05)
MAX_CONSECUTIVE_LOSSES = _int("MAX_CONSECUTIVE_LOSSES", 5)
MAX_DATA_STALENESS_SECONDS = _int("MAX_DATA_STALENESS_SECONDS", 900)
MAX_BAR_JUMP_ATR = _float("MAX_BAR_JUMP_ATR", 5.0)
MAX_CONSECUTIVE_API_ERRORS = _int("MAX_CONSECUTIVE_API_ERRORS", 3)

# Luoi an toan: bot tu dong vi the khi gia da xuyen stop ma san van bao con mo.
# Stop dat o san co the khong ton tai ma bot van tuong la co (sai ten tham so,
# lenh algo bi tu choi, loi cua san). Xem src/position_manager.py:_ep_stop.
EP_STOP_PHIA_BOT = _bool("EP_STOP_PHIA_BOT", True)

# ==========================================================
# Chi phi giao dich - PHAI khop voi phi that de backtest co nghia
# ==========================================================
FEE_TAKER = _float("FEE_TAKER", 0.001)      # Bybit spot taker ~0.1%
FEE_MAKER = _float("FEE_MAKER", 0.001)
SLIPPAGE = _float("SLIPPAGE", 0.0005)       # uoc luong 0.05% moi chieu

# ==========================================================
# Ensemble chien luoc + allocator (Nang cap 2)
# ==========================================================
STRATEGY_WEIGHT_FLOOR = _float("STRATEGY_WEIGHT_FLOOR", 0.10)
STRATEGY_WEIGHT_CAP = _float("STRATEGY_WEIGHT_CAP", 0.60)
PERFORMANCE_LOOKBACK_DAYS = _int("PERFORMANCE_LOOKBACK_DAYS", 45)
# Nguong nay phai hop voi cach gan trong so o allocator.
# Ba chien luoc la CHUYEN GIA THEO REGIME: binh thuong chi mot cai ban tin hieu,
# nen doi diem gop >= 0.5 la doi gan nhu nhat tri - mau thuan voi chinh thiet ke.
# Voi trong so ~0.42 cho chien luoc hop regime, nguong 0.15 nghia la:
#   - chien luoc hop regime can strength >= 0.36 moi vao lenh
#   - chien luoc bi ep xuong san (0.10) khong the tu kich hoat mot minh
MIN_SIGNAL_STRENGTH = _float("MIN_SIGNAL_STRENGTH", 0.15)

# ==========================================================
# Phan loai regime (Nang cap 1b)
# ==========================================================
ADX_TREND_THRESHOLD = _float("ADX_TREND_THRESHOLD", 25.0)
ATR_HIGH_VOL_PERCENTILE = _float("ATR_HIGH_VOL_PERCENTILE", 0.85)
REGIME_LOOKBACK = _int("REGIME_LOOKBACK", 100)

# ==========================================================
# Cong thong ke truoc khi promote chien luoc len live (Nang cap 4)
# ==========================================================
GATE_MIN_TRADES = _int("GATE_MIN_TRADES", 100)
GATE_MIN_SHARPE = _float("GATE_MIN_SHARPE", 1.0)
GATE_MAX_DRAWDOWN = _float("GATE_MAX_DRAWDOWN", 0.20)
GATE_MIN_PROFIT_FACTOR = _float("GATE_MIN_PROFIT_FACTOR", 1.3)
GATE_MAX_DEGRADATION = _float("GATE_MAX_DEGRADATION", 0.5)  # OOS vs IS

# ==========================================================
# AI POLICY + VONG HOC LIEN TUC (Nang cap 5)
# ==========================================================
# Che do trien khai policy, xep theo muc do duoc phep anh huong den lenh that:
#   off     khong nap mo hinh (mac dinh)
#   shadow  co du doan va ghi so, tin hieu LUON bi nen ve HOLD
#   filter  chi duoc chan hoac giam quy mo tin hieu cua chien luoc luat
#   active  la thanh vien binh thuong cua ensemble
#
# Doi che do la QUYET DINH CUA NGUOI. Vong hoc duoc phep doi champion trong mot
# che do, no khong bao gio duoc tu nang che do len.
POLICY_MODE = os.getenv("POLICY_MODE", "off").strip().lower()
POLICY_MODEL_DIR = os.getenv("POLICY_MODEL_DIR") or os.path.join(BASE_DIR, "models")

# Xep hang cat ngang tren qua it ma la vo nghia: voi 3 ma thi "top 33%" khong
# mang thong tin gi, nhung mo hinh van an cac cot _r nhu that. Duoi nguong nay
# policy tu choi co y kien.
POLICY_MIN_MA = _int("POLICY_MIN_MA", 8)

# Nguong ra quyet dinh tinh bang KY VONG LOI NHUAN RONG moi lenh, khong phai
# bang xac suat. Nho vay khi phi hoac barrier doi thi nguong tu dieu chinh theo,
# thay vi phai do lai bang tay mot con so p vo nghia ve kinh te.
POLICY_EV_MIN = _float("POLICY_EV_MIN", 0.0015)    # duoi muc nay = HOLD
POLICY_EV_FULL = _float("POLICY_EV_FULL", 0.012)   # muc cho strength = 1.0

# O che do "filter": policy khong dong y thi giam quy mo con bao nhieu phan.
# Nguoc chieu han thi chan hoan toan. Giong rang buoc dat cho LLM veto - lop nay
# chi duoc lam tin hieu YEU DI, khong bao gio manh len.
POLICY_FILTER_GIAM = _float("POLICY_FILTER_GIAM", 0.5)

# Do dai cac khoi khi cat lich su: train | embargo | calib | embargo | val
POLICY_CALIB_BARS = _int("POLICY_CALIB_BARS", 500)
POLICY_VAL_BARS = _int("POLICY_VAL_BARS", 700)

# ---------- Cong thang cap ----------
# Mot mo hinh chi tro thanh champion khi vuot TAT CA cac muc duoi day tren khoi
# kiem dinh ma no chua tung thay. Khong ha nguong de mo hinh dep hon: nguong o
# day da la muc thap nhat con co nghia tren du lieu tai chinh.
GATE_POLICY_MIN_MAU_TRAIN = _int("GATE_POLICY_MIN_MAU_TRAIN", 5000)
GATE_POLICY_MIN_MAU_VAL = _int("GATE_POLICY_MIN_MAU_VAL", 300)   # mau HIEU DUNG

# AUC co ca san lan TRAN. Tran ton tai vi tren du lieu gia, AUC > 0.75 gan nhu
# luon la dau hieu co dac trung nhin thay tuong lai chu khong phai ky nang.
# Mot cong chi chan tu duoi se de lot dung loai loi nguy hiem nhat.
GATE_POLICY_AUC_MIN = _float("GATE_POLICY_AUC_MIN", 0.52)
GATE_POLICY_AUC_MAX = _float("GATE_POLICY_AUC_MAX", 0.75)

# Doi chung nhan xao tron: mo hinh huan luyen tren nhan da xao PHAI vo dung.
# Neu no cung dat AUC cao thi ro ri nam trong duong ong, va moi so lieu khac
# deu khong dung duoc - vong hoc dung lai va bao dong thay vi thang cap.
GATE_POLICY_XAO_AUC_MAX = _float("GATE_POLICY_XAO_AUC_MAX", 0.55)

GATE_POLICY_IC_MIN = _float("GATE_POLICY_IC_MIN", 0.01)
GATE_POLICY_IC_T_MIN = _float("GATE_POLICY_IC_T_MIN", 2.0)
GATE_POLICY_MIN_LENH = _int("GATE_POLICY_MIN_LENH", 50)
GATE_POLICY_KY_VONG_MIN = _float("GATE_POLICY_KY_VONG_MIN", 0.0005)
GATE_POLICY_PF_MIN = _float("GATE_POLICY_PF_MIN", 1.15)
# Mo hinh doi vao lenh o phan lon so nen la mo hinh chua hoc duoc rang hau het
# thoi diem khong dang giao dich sau khi tru phi.
GATE_POLICY_TY_LE_VAO_MAX = _float("GATE_POLICY_TY_LE_VAO_MAX", 0.35)

# Challenger phai hon champion mot bien du lon, neu khong ta se doi mo hinh
# lien tuc chi vi nhieu ngau nhien - va moi lan doi la mot lan mat ho so ket qua
# truc tuyen dang tich luy.
GATE_POLICY_CAI_THIEN_AUC = _float("GATE_POLICY_CAI_THIEN_AUC", 0.005)

# ---------- Duong ha cap tu dong ----------
# Champion bi ha cap khi ket qua THAT kem xa so lieu kiem dinh cua chinh no.
# Chi xet sau khi da du so lenh: mot mo hinh khong bi loai vi vai lenh dau xau.
GATE_POLICY_MIN_LENH_THEO_DOI = _int("GATE_POLICY_MIN_LENH_THEO_DOI", 40)
GATE_POLICY_SUY_GIAM = _float("GATE_POLICY_SUY_GIAM", 0.5)

# ==========================================================
# BO LOC META-LABEL (Nang cap 6)
# ==========================================================
# Cau hoi khac han AI policy o tren. Policy hoi "trong moi cay nen, cai nao
# dang mua" - cau do qua kho: ty le co so 39.5% nam DUOI hoa von 40%, nen mo
# hinh phai tu sinh ra toan bo loi the va no khong lam duoc (0 lenh tren 15.096
# nen kiem dinh).
#
# Meta-label chi hoi khi mot chien luoc LUAT da len tieng: "tin hieu nay co dang
# nghe khong". Do tren mainnet 4H, 12 ma, 4.5 nam:
#     moi nen              126.873 mau, ty le lai sau phi 39.53%
#     nen breakout da phat   4.979 mau, ty le lai sau phi 42.86%
# Ty le co so cao hon 3.3 diem chi vi dung yen cho den khi co tin hieu.
META_CHIEN_LUOC = [s.strip() for s in
                   os.getenv("META_CHIEN_LUOC", "breakout").split(",") if s.strip()]

# Bien an toan cong vao nguong hoa von. Vao lenh o dung diem hoa von nghia la
# mot nua so lan ta dang vao lenh co ky vong am - sai so du doan cua mo hinh
# nam ca hai phia.
META_BIEN_AN_TOAN = _float("META_BIEN_AN_TOAN", 0.01)

# Bo loc chay khi co champion. Tat han bang bien nay neu can chay bot khong co
# bat ky lop hoc may nao - huu ich khi chan doan mot van de khac.
META_BAT = _bool("META_BAT", True)

# Vung GIAM nam ngay duoi nguong: mo hinh khong du tu tin de bao "vao lenh",
# nhung cung chua noi nguoc lai. Chan han o day se vut ca nhung tin hieu chi
# vua sat nguong, ma sai so du doan cua mo hinh lon hon khoang sat do nhieu.
META_VUNG_GIAM = _float("META_VUNG_GIAM", 0.02)

# ---------- Cong thang cap cho bo loc ----------
# MOC SO SANH LA "NGHE HET MOI TIN HIEU", KHONG PHAI AUC 0.5. Mot bo loc AUC
# 0.58 nghe co ve co ky nang, nhung neu sau khi loc van lo it hon viec khong loc
# gi thi no con te hon vo dung - no lam ta tuong minh dang duoc bao ve.
GATE_META_MIN_MAU_TRAIN = _int("GATE_META_MIN_MAU_TRAIN", 600)
GATE_META_MIN_LENH_GIU = _int("GATE_META_MIN_LENH_GIU", 30)

# Ty le giu lai phai nam trong khoang hop ly. Giu 3% la chon vai lenh may man
# trong so nhieu; giu 98% la bo loc dang lam nen chu khong loc gi.
GATE_META_TY_LE_GIU_MIN = _float("GATE_META_TY_LE_GIU_MIN", 0.15)
GATE_META_TY_LE_GIU_MAX = _float("GATE_META_TY_LE_GIU_MAX", 0.90)

# Ky vong sau khi loc phai duong VA phai hon ban khong loc mot bien du lon.
GATE_META_KY_VONG_MIN = _float("GATE_META_KY_VONG_MIN", 0.0005)
GATE_META_CAI_THIEN_MIN = _float("GATE_META_CAI_THIEN_MIN", 0.002)
GATE_META_PF_MIN = _float("GATE_META_PF_MIN", 1.10)

# AUC co ca san lan tran, cung ly do nhu ben AI policy: tren du lieu gia, AUC
# qua cao gan nhu luon la dac trung nhin thay tuong lai.
GATE_META_AUC_MIN = _float("GATE_META_AUC_MIN", 0.52)
GATE_META_AUC_MAX = _float("GATE_META_AUC_MAX", 0.80)
GATE_META_XAO_AUC_MAX = _float("GATE_META_XAO_AUC_MAX", 0.58)

# Duong ha cap tu dong khi chay that, giong AI policy.
GATE_META_MIN_LENH_THEO_DOI = _int("GATE_META_MIN_LENH_THEO_DOI", 30)

# ==========================================================
# Duong dan
# ==========================================================
# Cho phep doi cho de DB qua .env: huu ich khi deploy VPS, hoac khi thu muc
# du an nam tren mot mount khong ho tro file locking cua SQLite.
DB_PATH = os.getenv("DB_PATH") or os.path.join(BASE_DIR, "data", "trading.db")
LOG_PATH = os.path.join(BASE_DIR, "logs", "bot.log")
CACHE_DIR = os.path.join(BASE_DIR, "data", "cache")
