"""
Nhat ky giao dich hang dem - Nang cap 6.

Day la noi LLM tao gia tri ro rang nhat, va la thu gan nhu khong bot retail
nao co: moi dem doc lai toan bo lenh trong ngay kem ly do vao/ra va ket qua,
roi viet mot ban phe binh ngan.

Sau ba thang, tap hop cac ban phe binh nay co khi dang gia hon ca chien luoc
ban dau, vi no chi ra nhung mau hinh ma bang so lieu khong noi.

QUAN TRONG: nhat ky KHONG duoc tu dong sua tham so. Con nguoi doc va quyet dinh.
De LLM tu chinh tham so theo ket qua ngan han la con duong ngan nhat den
overfit theo thoi gian thuc.
"""
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    anthropic = None
    ANTHROPIC_AVAILABLE = False


JOURNAL_PROMPT = """Ban la nguoi phan tich nhat ky giao dich cho mot bot crypto.

Duoi day la toan bo hoat dong cua bot trong ngay {day}.

THONG KE:
{stats}

CAC LENH DA DONG:
{trades}

CAC QUYET DINH (ke ca quyet dinh khong vao lenh):
{decisions}

Hay viet mot ban phe binh NGAN (toi da 250 tu, tieng Viet) tra loi:
1. Lenh nao sai, va sai vi CHIEN LUOC sai, vi THUC THI te, hay chi vi XUI?
   Phan biet ba thu nay la phan quan trong nhat.
2. Co tin hieu/mau hinh nao lap di lap lai ma luon thua khong?
3. Co dau hieu nao dang lo ve quan tri rui ro khong?

Thang than, khong an ui. Neu ngay hom nay khong co gi dang noi thi noi vay,
dung co tim y nghia trong nhieu ngau nhien - phan lon cac ngay giao dich
la nhieu, va nham lan nhieu voi tin hieu la sai lam pho bien nhat."""


class TradingJournal:
    def __init__(self, storage, cfg=config):
        self.storage = storage
        self.cfg = cfg
        self.client = None
        if cfg.ENABLE_NIGHTLY_JOURNAL and ANTHROPIC_AVAILABLE and cfg.ANTHROPIC_API_KEY:
            self.client = anthropic.Anthropic(api_key=cfg.ANTHROPIC_API_KEY)

    def _day_bounds(self, day: Optional[datetime] = None):
        day = day or datetime.now()
        start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.timestamp(), (start + timedelta(days=1)).timestamp()

    def collect_stats(self, day: Optional[datetime] = None) -> Dict:
        start_ts, end_ts = self._day_bounds(day)
        trades = self.storage.trades_of_day(start_ts, end_ts)
        decisions = self.storage.decisions_of_day(start_ts, end_ts)

        pnls = [t["pnl"] for t in trades]
        wins = [p for p in pnls if p > 0]
        return {
            "so_lenh": len(trades),
            "so_quyet_dinh": len(decisions),
            "so_lenh_thang": len(wins),
            "win_rate": (len(wins) / len(pnls)) if pnls else 0.0,
            "tong_pnl": sum(pnls),
            "lenh_lon_nhat": max(pnls) if pnls else 0.0,
            "lenh_te_nhat": min(pnls) if pnls else 0.0,
            "so_lan_bi_llm_chan": sum(1 for d in decisions if d["llm_veto"]),
        }

    def generate(self, day: Optional[datetime] = None) -> Optional[str]:
        """Sinh ban phe binh cho mot ngay va luu vao database."""
        day = day or datetime.now()
        day_str = day.strftime("%Y-%m-%d")
        stats = self.collect_stats(day)

        if stats["so_quyet_dinh"] == 0:
            logger.info("Ngay %s khong co hoat dong nao - bo qua nhat ky", day_str)
            return None

        if self.client is None:
            content = ("Nhat ky tu dong (chua bat LLM): %s"
                       % json.dumps(stats, ensure_ascii=False))
            self.storage.log_journal(day_str, content, stats)
            return content

        start_ts, end_ts = self._day_bounds(day)
        trades = self.storage.trades_of_day(start_ts, end_ts)
        decisions = self.storage.decisions_of_day(start_ts, end_ts)

        trades_text = "\n".join(
            "- %s %s qty=%.6f vao=%.2f ra=%.2f pnl=%.2f (%s) [%s]"
            % (t["symbol"], t["side"], t["qty"], t["entry_price"], t["exit_price"],
               t["pnl"], t["exit_reason"], t["strategy"])
            for t in trades) or "(khong co lenh nao dong trong ngay)"

        decisions_text = "\n".join(
            "- %s %s strength=%.2f regime=%s executed=%s: %s"
            % (d["symbol"], d["action"], d["strength"] or 0, d["regime"],
               bool(d["executed"]), (d["reason"] or "")[:150])
            for d in decisions[:60]) or "(khong co quyet dinh nao)"

        prompt = JOURNAL_PROMPT.format(
            day=day_str,
            stats=json.dumps(stats, ensure_ascii=False, indent=2),
            trades=trades_text,
            decisions=decisions_text,
        )

        try:
            resp = self.client.messages.create(
                model=self.cfg.LLM_MODEL,
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
                timeout=60,
            )
            content = "".join(b.text for b in resp.content if hasattr(b, "text"))
            self.storage.log_journal(day_str, content, stats)
            logger.info("Da tao nhat ky cho ngay %s", day_str)
            return content
        except Exception as e:
            logger.error("Khong tao duoc nhat ky: %s", e)
            return None
