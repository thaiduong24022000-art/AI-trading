"""
Luu tru SQLite - Nang cap 6 va 7.

Mo hinh du lieu duoc thiet ke de tra loi duoc cau hoi "vi sao bot vao lenh nay"
sau ba thang nua. Moi quyet dinh deu luu kem LY DO, khong chi luu ket qua.
Day la nguyen lieu cho nhat ky AI hang dem va cho viec cai thien chien luoc.
"""
import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    symbol TEXT NOT NULL,
    regime TEXT,
    action TEXT NOT NULL,
    strength REAL,
    signals_json TEXT,
    weights_json TEXT,
    risk_json TEXT,
    llm_veto INTEGER DEFAULT 0,
    llm_reason TEXT,
    executed INTEGER DEFAULT 0,
    reason TEXT
);

CREATE TABLE IF NOT EXISTS lenh_dieu_khien (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    lenh TEXT NOT NULL,
    tham_so TEXT,
    trang_thai TEXT NOT NULL DEFAULT 'cho',
    ket_qua TEXT,
    xu_ly_luc REAL
);

CREATE TABLE IF NOT EXISTS trang_thai_bot (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    ts REAL NOT NULL,
    breaker_ngat INTEGER DEFAULT 0,
    breaker_ly_do TEXT,
    so_vi_the INTEGER DEFAULT 0,
    heat REAL DEFAULT 0,
    equity REAL,
    chien_luoc_bong TEXT
);

CREATE TABLE IF NOT EXISTS shadow_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    bar_ts INTEGER,
    symbol TEXT NOT NULL,
    chien_luoc TEXT NOT NULL,
    action TEXT NOT NULL,
    strength REAL,
    gia REAL,
    reason TEXT,
    ret_thuc REAL,
    nhan_xong INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    order_link_id TEXT UNIQUE,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    price REAL,
    stop_loss REAL,
    take_profit REAL,
    strategy TEXT,
    dry_run INTEGER DEFAULT 1,
    status TEXT,
    exchange_response TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    strategy TEXT,
    side TEXT,
    qty REAL,
    entry_price REAL,
    exit_price REAL,
    entry_ts REAL,
    exit_ts REAL,
    pnl REAL,
    pnl_pct REAL,
    exit_reason TEXT,
    dry_run INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS equity_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    equity REAL NOT NULL,
    open_positions INTEGER,
    heat REAL
);

CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    day TEXT,
    content TEXT,
    stats_json TEXT
);

-- Moi du doan cua AI policy, KE CA khi no chay o che do bong va khong anh
-- huong gi den lenh that. Day la so ghi chep de tra loi cau hoi "mo hinh dang
-- chay co con tot khong" bang du lieu THAT thay vi bang niem tin.
--
-- VI SAO GHI CA NHUNG LAN POLICY NOI HOLD: neu chi ghi lai nhung lan vao lenh
-- thi ta chi thay ket qua cua nhung quyet dinh da chon - do la thien lech chon
-- mau kinh dien, va no lam mo hinh trong dep hon thuc te mot cach co he thong.
-- Nhan triple-barrier tinh duoc cho MOI nen du ta co vao lenh hay khong, nen
-- ta luu duoc ca ket qua PHAN THUC TE cua nhung lan no bao dung yen.
CREATE TABLE IF NOT EXISTS policy_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    bar_ts INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    phien_ban TEXT NOT NULL,
    che_do TEXT,
    action TEXT,
    strength REAL,
    p_long REAL,
    p_short REAL,
    ev_long REAL,
    ev_short REAL,
    ly_do TEXT,
    ket_qua_ts REAL,
    ret_long REAL,
    ret_short REAL,
    ret_thuc REAL,
    nhan_xong INTEGER DEFAULT 0,
    UNIQUE(bar_ts, symbol, phien_ban)
);

CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy, exit_ts);
CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(ts);
CREATE INDEX IF NOT EXISTS idx_policy_pb ON policy_predictions(phien_ban, nhan_xong);
CREATE INDEX IF NOT EXISTS idx_policy_bar ON policy_predictions(symbol, bar_ts);
"""


class Storage:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_schema()

    @contextmanager
    def conn(self):
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # Cot them vao sau khi mot bang da ton tai. CREATE TABLE IF NOT EXISTS
    # KHONG them cot cho bang da co - DB cu se thieu cot mot cach im lang cho
    # den luc mot cau lenh SELECT no vo. Danh sach nay chay moi lan khoi dong,
    # va ALTER TABLE ADD COLUMN cua SQLite la thao tac re (chi sua metadata).
    COT_THEM_SAU = (
        ("shadow_signals", "ret_thuc", "REAL"),
        ("shadow_signals", "nhan_xong", "INTEGER DEFAULT 0"),
    )

    def _init_schema(self) -> None:
        with self.conn() as con:
            con.executescript(SCHEMA)
            for bang, cot, kieu in self.COT_THEM_SAU:
                co = {r["name"] for r in con.execute("PRAGMA table_info(%s)" % bang)}
                if cot not in co:
                    con.execute("ALTER TABLE %s ADD COLUMN %s %s" % (bang, cot, kieu))
                    logger.info("Da them cot %s.%s vao DB co san", bang, cot)

    # ---------- ghi ----------
    def log_decision(self, symbol: str, action: str, strength: float, regime: str,
                     signals: List, weights: Dict, risk: Dict = None,
                     llm_veto: bool = False, llm_reason: str = "",
                     executed: bool = False, reason: str = "") -> int:
        signals_json = json.dumps(
            [{"strategy": s.strategy, "action": s.action, "strength": s.strength,
              "reason": s.reason} for s in signals], ensure_ascii=False)
        with self.conn() as con:
            cur = con.execute(
                """INSERT INTO decisions
                   (ts, symbol, regime, action, strength, signals_json, weights_json,
                    risk_json, llm_veto, llm_reason, executed, reason)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (time.time(), symbol, regime, action, strength, signals_json,
                 json.dumps(weights), json.dumps(risk or {}), int(llm_veto),
                 llm_reason, int(executed), reason),
            )
            return cur.lastrowid

    def log_order(self, order_link_id: str, symbol: str, side: str, qty: float,
                  price: float = None, stop_loss: float = None, take_profit: float = None,
                  strategy: str = "", dry_run: bool = True, status: str = "submitted",
                  response: str = "") -> None:
        with self.conn() as con:
            con.execute(
                """INSERT OR REPLACE INTO orders
                   (ts, order_link_id, symbol, side, qty, price, stop_loss, take_profit,
                    strategy, dry_run, status, exchange_response)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (time.time(), order_link_id, symbol, side, qty, price, stop_loss,
                 take_profit, strategy, int(dry_run), status, response),
            )

    def log_trade(self, symbol: str, strategy: str, side: str, qty: float,
                  entry_price: float, exit_price: float, entry_ts: float,
                  exit_ts: float, pnl: float, exit_reason: str,
                  dry_run: bool = True) -> None:
        pnl_pct = pnl / (entry_price * qty) if entry_price and qty else 0.0
        with self.conn() as con:
            con.execute(
                """INSERT INTO trades
                   (symbol, strategy, side, qty, entry_price, exit_price, entry_ts,
                    exit_ts, pnl, pnl_pct, exit_reason, dry_run)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (symbol, strategy, side, qty, entry_price, exit_price, entry_ts,
                 exit_ts, pnl, pnl_pct, exit_reason, int(dry_run)),
            )

    def log_shadow_signal(self, symbol: str, chien_luoc: str, action: str,
                          strength: float, gia: float, bar_ts: int = 0,
                          reason: str = "") -> None:
        """Ghi tin hieu cua chien luoc luat dang chay che do BONG.

        Ghi CA nhung lan no noi HOLD. Chi ghi luc no muon vao lenh thi ho so
        chi con nhung luc no co y kien - do la thien lech chon mau, va khi
        cham diem che do bong ta se thay no quyet doan hon thuc te.
        """
        with self.conn() as con:
            con.execute(
                """INSERT INTO shadow_signals
                   (ts, bar_ts, symbol, chien_luoc, action, strength, gia, reason)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (time.time(), int(bar_ts or 0), symbol, chien_luoc, action,
                 float(strength or 0), float(gia or 0), reason[:500]),
            )

    def shadow_chua_co_ket_qua(self, truoc_bar_ts: int,
                               gioi_han: int = 5000) -> List[sqlite3.Row]:
        """Tin hieu bong da du gia de biet ket qua nhung chua duoc cham."""
        with self.conn() as con:
            return con.execute(
                """SELECT id, symbol, chien_luoc, action, bar_ts FROM shadow_signals
                   WHERE nhan_xong = 0 AND bar_ts > 0 AND bar_ts <= ?
                   ORDER BY id LIMIT ?""", (int(truoc_bar_ts), gioi_han)).fetchall()

    def cap_nhat_ket_qua_shadow(self, id_: int, ret_thuc: float) -> None:
        with self.conn() as con:
            con.execute(
                "UPDATE shadow_signals SET ret_thuc=?, nhan_xong=1 WHERE id=?",
                (float(ret_thuc), id_))

    def diem_shadow(self, chien_luoc: str) -> Dict:
        """Ket qua da cham cua mot chien luoc bong.

        CHI tinh tren tin hieu CO HANH DONG (BUY/SELL). Tin hieu HOLD van duoc
        ghi va van duoc cham de ho so khong bi thien lech chon mau, nhung ky
        vong moi lenh thi chi co nghia tren nhung lan no thuc su muon vao lenh.
        """
        with self.conn() as con:
            r = con.execute(
                """SELECT COUNT(*) AS n, AVG(ret_thuc) AS tb,
                          SUM(CASE WHEN ret_thuc > 0 THEN 1 ELSE 0 END) AS thang
                   FROM shadow_signals
                   WHERE chien_luoc = ? AND nhan_xong = 1
                     AND action IN ('BUY','SELL')""", (chien_luoc,)).fetchone()
            cho = con.execute(
                """SELECT COUNT(*) AS n FROM shadow_signals
                   WHERE chien_luoc = ? AND nhan_xong = 0
                     AND action IN ('BUY','SELL')""", (chien_luoc,)).fetchone()
        n = r["n"] or 0
        return {
            "so_tin_hieu_da_cham": n,
            "so_tin_hieu_cho_cham": cho["n"] or 0,
            "ky_vong_moi_lenh": float(r["tb"]) if r["tb"] is not None else None,
            "ty_le_thang": (r["thang"] / n) if n else None,
        }

    def thong_ke_shadow(self, chien_luoc: str = None, tu_ts: float = 0) -> List[sqlite3.Row]:
        """Dem tin hieu che do bong theo chien luoc - de cham truoc khi thang cap."""
        with self.conn() as con:
            if chien_luoc:
                return con.execute(
                    """SELECT chien_luoc, action, COUNT(*) AS n FROM shadow_signals
                       WHERE chien_luoc = ? AND ts >= ? GROUP BY chien_luoc, action""",
                    (chien_luoc, tu_ts)).fetchall()
            return con.execute(
                """SELECT chien_luoc, action, COUNT(*) AS n FROM shadow_signals
                   WHERE ts >= ? GROUP BY chien_luoc, action""", (tu_ts,)).fetchall()

    # ---------- kenh dieu khien UI -> bot ----------
    def them_lenh(self, lenh: str, tham_so: Dict = None) -> int:
        """Xep mot lenh dieu khien cho bot doc o vong sau.

        Kenh nay di qua DB thay vi mot cong mang: bot va web la hai tien trinh
        rieng, va mo them mot cong nghe lenh la mo them mot be mat tan cong.
        DB thi ca hai da dung chung san roi.
        """
        with self.conn() as con:
            cur = con.execute(
                "INSERT INTO lenh_dieu_khien (ts, lenh, tham_so) VALUES (?,?,?)",
                (time.time(), lenh, json.dumps(tham_so or {}, ensure_ascii=False)))
            return cur.lastrowid

    def lenh_cho_xu_ly(self, han_giay: float = 600) -> List[sqlite3.Row]:
        """Lenh dang cho, con han. Lenh qua han bi danh dau het han, KHONG chay.

        Ly do co han: bot tat ba ngay roi bat lai khong nen thuc hien mot lenh
        ai do xep tu ba ngay truoc - luc do boi canh da khac han, va mot lenh
        "reset breaker" tu qua khu se am tham xoa mot canh bao dang con dung.
        """
        moc = time.time() - han_giay
        with self.conn() as con:
            con.execute(
                "UPDATE lenh_dieu_khien SET trang_thai='het_han', xu_ly_luc=? "
                "WHERE trang_thai='cho' AND ts < ?", (time.time(), moc))
            return con.execute(
                "SELECT * FROM lenh_dieu_khien WHERE trang_thai='cho' ORDER BY id"
            ).fetchall()

    def danh_dau_lenh(self, id_: int, trang_thai: str, ket_qua: str = "") -> None:
        with self.conn() as con:
            con.execute(
                "UPDATE lenh_dieu_khien SET trang_thai=?, ket_qua=?, xu_ly_luc=? "
                "WHERE id=?", (trang_thai, ket_qua[:500], time.time(), id_))

    def ghi_trang_thai_bot(self, breaker_ngat: bool, breaker_ly_do: str,
                           so_vi_the: int, heat: float, equity: float = None,
                           chien_luoc_bong: str = "") -> None:
        """Nhip tim cua bot - de web biet bot dang nghi gi, khong chi biet
        tien trinh con song hay khong.
        """
        with self.conn() as con:
            con.execute(
                """INSERT INTO trang_thai_bot
                   (id, ts, breaker_ngat, breaker_ly_do, so_vi_the, heat, equity,
                    chien_luoc_bong)
                   VALUES (1,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     ts=excluded.ts, breaker_ngat=excluded.breaker_ngat,
                     breaker_ly_do=excluded.breaker_ly_do,
                     so_vi_the=excluded.so_vi_the, heat=excluded.heat,
                     equity=excluded.equity,
                     chien_luoc_bong=excluded.chien_luoc_bong""",
                (time.time(), int(bool(breaker_ngat)), breaker_ly_do or "",
                 int(so_vi_the), float(heat or 0),
                 float(equity) if equity is not None else None, chien_luoc_bong))

    def log_equity(self, equity: float, open_positions: int, heat: float) -> None:
        with self.conn() as con:
            con.execute(
                "INSERT INTO equity_snapshots (ts, equity, open_positions, heat) VALUES (?,?,?,?)",
                (time.time(), equity, open_positions, heat),
            )

    def log_journal(self, day: str, content: str, stats: Dict = None) -> None:
        with self.conn() as con:
            con.execute(
                "INSERT INTO journal (ts, day, content, stats_json) VALUES (?,?,?,?)",
                (time.time(), day, content, json.dumps(stats or {}, ensure_ascii=False)),
            )

    def log_policy_prediction(self, symbol: str, bar_ts: int, ket_qua,
                              che_do: str = "") -> None:
        """Ghi mot du doan cua policy. Trung (bar_ts, symbol, phien_ban) thi bo qua.

        Bo qua chu khong ghi de: vong lap co the chay lai tren cung mot cay nen
        4h nhieu lan (LOOP_INTERVAL_SECONDS = 5 phut), va lan ghi dau tien la
        lan duy nhat phan anh thong tin co tai thoi diem do.
        """
        with self.conn() as con:
            con.execute(
                """INSERT OR IGNORE INTO policy_predictions
                   (ts, bar_ts, symbol, phien_ban, che_do, action, strength,
                    p_long, p_short, ev_long, ev_short, ly_do)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (time.time(), int(bar_ts), symbol, ket_qua.phien_ban or "khong_mo_hinh",
                 che_do, ket_qua.action, ket_qua.strength, ket_qua.p_long,
                 ket_qua.p_short, ket_qua.ev_long, ket_qua.ev_short, ket_qua.ly_do),
            )

    def policy_chua_co_ket_qua(self, truoc_ts: int, gioi_han: int = 5000) -> List[sqlite3.Row]:
        """Cac du doan da du gia (nhan co the da nga ngu) nhung chua dien ket qua."""
        with self.conn() as con:
            return con.execute(
                """SELECT id, symbol, bar_ts, phien_ban FROM policy_predictions
                   WHERE nhan_xong = 0 AND bar_ts <= ?
                   ORDER BY bar_ts LIMIT ?""",
                (int(truoc_ts), gioi_han),
            ).fetchall()

    def cap_nhat_ket_qua_policy(self, id_: int, ret_long: float, ret_short: float,
                                action: str) -> None:
        thuc = ret_long if action == "BUY" else (ret_short if action == "SELL" else 0.0)
        with self.conn() as con:
            con.execute(
                """UPDATE policy_predictions
                   SET ret_long = ?, ret_short = ?, ret_thuc = ?, nhan_xong = 1,
                       ket_qua_ts = ?
                   WHERE id = ?""",
                (ret_long, ret_short, thuc, time.time(), id_),
            )

    def thong_ke_policy(self, phien_ban: str, chi_khi_vao_lenh: bool = True) -> Dict:
        """Ket qua THAT cua mot phien ban mo hinh khi chay truc tuyen.

        So sanh voi chi so kiem dinh trong meta cua chinh phien ban do la cach
        duy nhat phat hien mo hinh dang xuong cap ma khong phai doi den luc
        duong von noi cho ta biet.
        """
        dieu_kien = "AND action IN ('BUY','SELL')" if chi_khi_vao_lenh else ""
        with self.conn() as con:
            rows = con.execute(
                """SELECT ret_thuc FROM policy_predictions
                   WHERE phien_ban = ? AND nhan_xong = 1 %s""" % dieu_kien,
                (phien_ban,),
            ).fetchall()
        v = [r["ret_thuc"] for r in rows if r["ret_thuc"] is not None]
        if not v:
            return {"so_lenh": 0}
        thang = [x for x in v if x > 0]
        thua = [x for x in v if x <= 0]
        tong_thua = -sum(thua)
        return {
            "so_lenh": len(v),
            "loi_nhuan_tb": sum(v) / len(v),
            "ty_le_thang": len(thang) / len(v),
            "profit_factor": (sum(thang) / tong_thua) if tong_thua > 0 else float("inf"),
            "tong_loi_nhuan": sum(v),
        }

    # ---------- doc ----------
    def strategy_performance(self, lookback_days: int = None) -> Dict[str, float]:
        """Profit factor cuon chieu cho tung chien luoc, dung cho allocator."""
        lookback_days = lookback_days or config.PERFORMANCE_LOOKBACK_DAYS
        since = time.time() - lookback_days * 86400
        out: Dict[str, float] = {}
        with self.conn() as con:
            rows = con.execute(
                """SELECT strategy,
                          SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END) AS gross_win,
                          SUM(CASE WHEN pnl < 0 THEN -pnl ELSE 0 END) AS gross_loss,
                          COUNT(*) AS n
                   FROM trades WHERE exit_ts >= ? AND strategy IS NOT NULL
                   GROUP BY strategy""",
                (since,),
            ).fetchall()
        for r in rows:
            if r["n"] < 5:      # qua it lenh de ket luan bat cu dieu gi
                continue
            gl = r["gross_loss"] or 0.0
            gw = r["gross_win"] or 0.0
            out[r["strategy"]] = (gw / gl) if gl > 0 else 2.0
        return out

    def trades_of_day(self, day_start_ts: float, day_end_ts: float) -> List[sqlite3.Row]:
        with self.conn() as con:
            return con.execute(
                "SELECT * FROM trades WHERE exit_ts >= ? AND exit_ts < ? ORDER BY exit_ts",
                (day_start_ts, day_end_ts),
            ).fetchall()

    def decisions_of_day(self, day_start_ts: float, day_end_ts: float) -> List[sqlite3.Row]:
        with self.conn() as con:
            return con.execute(
                "SELECT * FROM decisions WHERE ts >= ? AND ts < ? ORDER BY ts",
                (day_start_ts, day_end_ts),
            ).fetchall()

    def last_equity(self) -> Optional[float]:
        with self.conn() as con:
            row = con.execute(
                "SELECT equity FROM equity_snapshots ORDER BY ts DESC LIMIT 1").fetchone()
        return row["equity"] if row else None
