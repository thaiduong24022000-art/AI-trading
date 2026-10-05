"""
Thuc thi lenh - Nang cap 7 (idempotency).

Hai dieu quan trong nhat trong file nay:

1. orderLinkId SINH XAC DINH tu (symbol, side, thoi diem nen, chien luoc).
   Timeout mang KHONG co nghia la lenh chua vao san. Neu retry mu, ban tao
   lenh trung. Voi orderLinkId co dinh, san se tu tu choi lenh thu hai.

2. DRY_RUN la mac dinh. Lenh that chi duoc gui khi DRY_RUN=False duoc dat
   mot cach co chu dich trong .env.
"""
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Optional

import config
from .risk_manager import Position, RiskDecision

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    success: bool
    order_link_id: str
    dry_run: bool
    message: str = ""
    position: Optional[Position] = None
    raw_response: Optional[dict] = None


def make_order_link_id(symbol: str, side: str, bar_timestamp: float, strategy: str) -> str:
    """ID xac dinh: cung mot tin hieu tren cung mot cay nen luon sinh cung ID.

    Nho vay retry sau timeout khong bao gio tao lenh thu hai.
    Bybit gioi han orderLinkId 36 ky tu.
    """
    raw = "%s|%s|%d|%s" % (symbol, side, int(bar_timestamp), strategy)
    digest = hashlib.sha1(raw.encode()).hexdigest()[:16]
    return "bot_%s" % digest


class Executor:
    def __init__(self, client=None, storage=None, cfg=config):
        self.client = client
        self.storage = storage
        self.cfg = cfg

    def _round_qty(self, symbol: str, qty: float) -> float:
        """Lam tron khoi luong theo buoc nhay cua san (neu lay duoc thong tin)."""
        if self.client is None:
            return qty
        try:
            info = self.client.get_instrument_info(symbol)
            if not info:
                return qty
            step = float(info.get("lotSizeFilter", {}).get("qtyStep")
                         or info.get("lotSizeFilter", {}).get("basePrecision") or 0)
            min_qty = float(info.get("lotSizeFilter", {}).get("minOrderQty") or 0)
            if step > 0:
                qty = int(qty / step) * step
            if min_qty and qty < min_qty:
                return 0.0
            return qty
        except Exception as e:
            logger.warning("Khong lay duoc buoc nhay khoi luong cho %s: %s", symbol, e)
            return qty

    def open_position(self, symbol: str, side: str, decision: RiskDecision,
                      entry_price: float, bar_timestamp: float,
                      strategy: str = "") -> ExecutionResult:
        if not decision.approved:
            return ExecutionResult(False, "", self.cfg.DRY_RUN,
                                   "risk manager tu choi: %s" % "; ".join(decision.reasons))

        link_id = make_order_link_id(symbol, side, bar_timestamp, strategy)
        qty = self._round_qty(symbol, decision.qty)
        if qty <= 0:
            return ExecutionResult(False, link_id, self.cfg.DRY_RUN,
                                   "khoi luong sau lam tron = 0 (nho hon minOrderQty)")

        position = Position(
            symbol=symbol, side=side, qty=qty, entry_price=entry_price,
            stop_loss=decision.stop_loss, take_profit=decision.take_profit,
            strategy=strategy,
        )

        if self.cfg.DRY_RUN:
            msg = ("[DRY-RUN] SE dat lenh %s %s qty=%.6f @ %.2f sl=%.2f tp=%.2f"
                   % (side, symbol, qty, entry_price, decision.stop_loss, decision.take_profit))
            logger.info(msg)
            if self.storage:
                self.storage.log_order(link_id, symbol, side, qty, entry_price,
                                       decision.stop_loss, decision.take_profit,
                                       strategy, dry_run=True, status="dry_run")
            return ExecutionResult(True, link_id, True, msg, position)

        if self.client is None:
            return ExecutionResult(False, link_id, False, "chua co ket noi san")

        try:
            resp = self.client.place_order(
                symbol=symbol, side=side, qty=qty, order_type="Market",
                stop_loss="%.8f" % decision.stop_loss,
                take_profit="%.8f" % decision.take_profit,
                order_link_id=link_id,
            )
            ret_code = resp.get("retCode", -1)
            if ret_code != 0:
                msg = "san tu choi lenh: %s" % resp.get("retMsg")
                logger.error(msg)
                if self.storage:
                    self.storage.log_order(link_id, symbol, side, qty, entry_price,
                                           decision.stop_loss, decision.take_profit,
                                           strategy, dry_run=False, status="rejected",
                                           response=str(resp))
                return ExecutionResult(False, link_id, False, msg, raw_response=resp)

            logger.info("Da dat lenh %s %s qty=%.6f (id=%s)", side, symbol, qty, link_id)
            if self.storage:
                self.storage.log_order(link_id, symbol, side, qty, entry_price,
                                       decision.stop_loss, decision.take_profit,
                                       strategy, dry_run=False, status="filled",
                                       response=str(resp))
            return ExecutionResult(True, link_id, False, "da dat lenh", position, resp)

        except Exception as e:
            # KHONG retry o day. Timeout co the nghia la lenh DA vao san.
            # Vong lap ke tiep se doi soat lai voi san truoc khi lam gi them.
            msg = "loi khi dat lenh (co the lenh DA vao san - se doi soat o vong sau): %s" % e
            logger.error(msg)
            if self.storage:
                self.storage.log_order(link_id, symbol, side, qty, entry_price,
                                       decision.stop_loss, decision.take_profit,
                                       strategy, dry_run=False, status="unknown",
                                       response=str(e))
            return ExecutionResult(False, link_id, False, msg)

    def close_position(self, position: Position, exit_price: float,
                       reason: str = "signal", bar_timestamp: float = None) -> ExecutionResult:
        """Dong vi the tai gia thi truong.

        bar_timestamp lam orderLinkId XAC DINH theo cay nen thay vi theo dong ho.
        Quan trong khi lenh dong duoc thu lai o vong sau (vi du lop bao ve stop
        chay lai moi vong): voi time.time(), moi lan thu sinh mot ID moi, va mot
        timeout mang co the thanh hai lenh dong chong len nhau. Voi moc nen,
        lan thu thu hai trong cung cay nen mang dung ID cu va bi san tu choi -
        do la ca y nghia cua orderLinkId.
        """
        close_side = "Sell" if position.side == "Buy" else "Buy"
        link_id = make_order_link_id(
            position.symbol, "close_" + close_side,
            time.time() if bar_timestamp is None else bar_timestamp,
            position.strategy)

        if self.cfg.DRY_RUN:
            msg = "[DRY-RUN] SE dong vi the %s @ %.2f (%s)" % (position.symbol, exit_price, reason)
            logger.info(msg)
            return ExecutionResult(True, link_id, True, msg, position)

        if self.client is None:
            return ExecutionResult(False, link_id, False, "chua co ket noi san")

        try:
            resp = self.client.place_order(
                symbol=position.symbol, side=close_side, qty=position.qty,
                order_type="Market", order_link_id=link_id, reduce_only=True,
            )
            ok = resp.get("retCode", -1) == 0
            return ExecutionResult(ok, link_id, False,
                                   "dong vi the: %s" % resp.get("retMsg"), position, resp)
        except Exception as e:
            logger.error("Loi khi dong vi the %s: %s", position.symbol, e)
            return ExecutionResult(False, link_id, False, str(e))
