"""
Risk engine - Nang cap 3 va 7. Day la module quan trong nhat cua he thong.

Nguyen tac trung tam: co dinh RUI RO moi lenh, khong co dinh GIA TRI lenh.
  - Stop-loss dat theo ATR (bien dong thuc te cua thi truong).
  - Khoi luong tinh nguoc tu stop: neu cham stop thi mat dung R% von.
  => Bien dong cao thi khoi luong tu dong nho lai. Bien dong thap thi lon len.
     Rui ro moi lenh la hang so, du giao dich BTC hay mot altcoin dong nat.

Ngoai ra co ba lop chan o cap danh muc ma sizing tung lenh khong the thay:
  - Portfolio heat: tong rui ro dang mo khong vuot MAX_PORTFOLIO_HEAT.
  - Tran tuong quan: BTC/ETH/SOL tuong quan ~0.85-0.9, mo ca ba khong phai
    da dang hoa ma la mot lenh gap ba.
  - Circuit breakers: dung han khi du lieu/thi truong/API co dau hieu bat thuong.
"""
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)


@dataclass
class Position:
    symbol: str
    side: str            # "Buy" | "Sell"
    qty: float
    entry_price: float
    stop_loss: float
    take_profit: float
    strategy: str = ""
    opened_at: float = field(default_factory=time.time)

    @property
    def risk_amount(self) -> float:
        """So tien se mat neu cham stop-loss."""
        return abs(self.entry_price - self.stop_loss) * self.qty

    @property
    def notional(self) -> float:
        return self.entry_price * self.qty


@dataclass
class RiskDecision:
    approved: bool
    qty: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_amount: float = 0.0
    reasons: List[str] = field(default_factory=list)

    def reject(self, reason: str) -> "RiskDecision":
        self.approved = False
        self.reasons.append(reason)
        return self


class CircuitBreaker:
    """Cac dieu kien khien bot NGUNG MO LENH MOI.

    Luu y: cham circuit breaker khong tu dong dong cac lenh dang co
    (tru truong hop drawdown ngay), vi dong lenh hang loat luc thi truong
    hon loan thuong lam moi thu te hon. No chi ngung mo them va bao nguoi.
    """

    def __init__(self, cfg=config):
        self.cfg = cfg
        self.tripped = False
        self.reason = ""
        self.consecutive_api_errors = 0
        self.consecutive_losses = 0
        self.day = date.today()
        self.day_start_equity: Optional[float] = None

    def reset_daily(self, equity: float) -> None:
        self.day = date.today()
        self.day_start_equity = equity
        self.consecutive_losses = 0
        if self.tripped and self.reason.startswith("drawdown"):
            self.tripped = False
            self.reason = ""
            logger.info("Reset circuit breaker theo ngay moi")

    def record_api_error(self) -> None:
        self.consecutive_api_errors += 1
        if self.consecutive_api_errors >= self.cfg.MAX_CONSECUTIVE_API_ERRORS:
            self.trip("api_errors: %d loi lien tiep" % self.consecutive_api_errors)

    def record_api_success(self) -> None:
        self.consecutive_api_errors = 0

    def record_trade_result(self, pnl: float) -> None:
        if pnl < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.cfg.MAX_CONSECUTIVE_LOSSES:
                self.trip("consecutive_losses: %d lenh thua lien tiep" % self.consecutive_losses)
        else:
            self.consecutive_losses = 0

    def check_equity(self, equity: float) -> None:
        if date.today() != self.day:
            self.reset_daily(equity)
        if self.day_start_equity is None:
            self.day_start_equity = equity
            return
        if self.day_start_equity <= 0:
            return
        dd = (self.day_start_equity - equity) / self.day_start_equity
        if dd >= self.cfg.MAX_DAILY_DRAWDOWN:
            self.trip("drawdown ngay %.2f%% >= nguong %.2f%%" % (dd * 100, self.cfg.MAX_DAILY_DRAWDOWN * 100))

    def check_data_freshness(self, last_bar_timestamp: float) -> None:
        age = time.time() - last_bar_timestamp
        if age > self.cfg.MAX_DATA_STALENESS_SECONDS:
            self.trip("du lieu cu %.0f giay > nguong %d" % (age, self.cfg.MAX_DATA_STALENESS_SECONDS))

    def check_price_jump(self, bar_range: float, atr_value: float) -> None:
        if atr_value and atr_value > 0 and bar_range / atr_value > self.cfg.MAX_BAR_JUMP_ATR:
            self.trip("gia nhay %.1fx ATR trong mot nen" % (bar_range / atr_value))

    def trip(self, reason: str) -> None:
        if not self.tripped:
            logger.error("CIRCUIT BREAKER KICH HOAT: %s", reason)
        self.tripped = True
        self.reason = reason

    def manual_reset(self, log: bool = True) -> None:
        # log=False danh cho backtest: mot lan chay co the reset hang tram lan,
        # ghi log het se lam ngap output cua walk-forward.
        if log:
            logger.warning("Circuit breaker duoc reset thu cong: %s", self.reason)
        self.tripped = False
        self.reason = ""
        self.consecutive_api_errors = 0
        self.consecutive_losses = 0


class RiskManager:
    def __init__(self, cfg=config, breaker: Optional[CircuitBreaker] = None):
        self.cfg = cfg
        self.breaker = breaker or CircuitBreaker(cfg)
        self.positions: Dict[str, Position] = {}

    # ---------- theo doi vi the ----------
    def register_position(self, pos: Position) -> None:
        self.positions[pos.symbol] = pos

    def remove_position(self, symbol: str) -> Optional[Position]:
        return self.positions.pop(symbol, None)

    def sync_positions(self, positions: Dict[str, Position]) -> None:
        """Dong bo tu san (nguon su that), dung sau reconciliation."""
        self.positions = dict(positions)

    # ---------- tinh toan ----------
    def cluster_of(self, symbol: str) -> str:
        return self.cfg.CORRELATION_CLUSTERS.get(symbol, self.cfg.DEFAULT_CLUSTER)

    def current_heat(self, equity: float) -> float:
        """Tong rui ro dang mo, tinh theo ty le tren von."""
        if equity <= 0:
            return 1.0
        return sum(p.risk_amount for p in self.positions.values()) / equity

    def compute_stop_and_target(self, entry_price: float, atr_value: float, side: str):
        stop_dist = self.cfg.ATR_STOP_MULT * atr_value
        tp_dist = self.cfg.ATR_TP_MULT * atr_value
        if side == "Buy":
            return entry_price - stop_dist, entry_price + tp_dist
        return entry_price + stop_dist, entry_price - tp_dist

    def size_position(self, equity: float, entry_price: float, stop_loss: float,
                      strength: float = 1.0) -> float:
        """Khoi luong sao cho cham stop = mat dung RISK_PER_TRADE * equity.

        strength (0..1) cho phep giam quy mo khi tin hieu yeu, nhung khong
        bao gio tang qua muc rui ro chuan.
        """
        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit <= 0 or entry_price <= 0 or equity <= 0:
            return 0.0
        risk_budget = equity * self.cfg.RISK_PER_TRADE * max(0.0, min(1.0, strength))
        qty = risk_budget / risk_per_unit

        # Tran cung theo gia tri lenh: khong de mot lenh chiem qua nhieu von
        max_notional = equity * self.cfg.MAX_POSITION_NOTIONAL_PCT
        if qty * entry_price > max_notional:
            qty = max_notional / entry_price
        return qty

    # ---------- kiem duyet lenh ----------
    def evaluate(self, symbol: str, side: str, entry_price: float, atr_value: float,
                 equity: float, strength: float = 1.0) -> RiskDecision:
        """Cong kiem duyet cuoi cung truoc khi mot lenh duoc gui di."""
        decision = RiskDecision(approved=True)

        if self.breaker.tripped:
            return decision.reject("circuit breaker dang bat: %s" % self.breaker.reason)

        if equity <= 0:
            return decision.reject("equity khong hop le")

        if atr_value is None or atr_value <= 0 or math.isnan(atr_value):
            return decision.reject("ATR khong hop le - khong the dat stop an toan")

        if side == "Sell" and not self.cfg.ALLOW_SHORT:
            return decision.reject("ALLOW_SHORT=False (spot khong ban khong)")

        if symbol in self.positions:
            return decision.reject("da co vi the mo cho %s" % symbol)

        if len(self.positions) >= self.cfg.MAX_OPEN_POSITIONS:
            return decision.reject("da dat toi da %d vi the mo" % self.cfg.MAX_OPEN_POSITIONS)

        # Tran tuong quan: dem so vi the trong cung cum
        cluster = self.cluster_of(symbol)
        same_cluster = sum(1 for s in self.positions if self.cluster_of(s) == cluster)
        if same_cluster >= self.cfg.MAX_POSITIONS_PER_CLUSTER:
            return decision.reject(
                "cum '%s' da co %d vi the (tran %d) - mo them chi la nhan doi cung mot cuoc dat cuoc"
                % (cluster, same_cluster, self.cfg.MAX_POSITIONS_PER_CLUSTER))

        stop_loss, take_profit = self.compute_stop_and_target(entry_price, atr_value, side)
        qty = self.size_position(equity, entry_price, stop_loss, strength)
        if qty <= 0:
            return decision.reject("khoi luong tinh ra bang 0")

        risk_amount = abs(entry_price - stop_loss) * qty

        # Portfolio heat: tong rui ro sau khi them lenh nay
        projected_heat = self.current_heat(equity) + risk_amount / equity
        if projected_heat > self.cfg.MAX_PORTFOLIO_HEAT:
            return decision.reject(
                "portfolio heat %.2f%% vuot tran %.2f%%"
                % (projected_heat * 100, self.cfg.MAX_PORTFOLIO_HEAT * 100))

        decision.qty = qty
        decision.stop_loss = stop_loss
        decision.take_profit = take_profit
        decision.risk_amount = risk_amount
        decision.reasons.append(
            "qty=%.6f risk=%.2f (%.2f%% von) stop=%.2f tp=%.2f heat=%.2f%%"
            % (qty, risk_amount, risk_amount / equity * 100, stop_loss, take_profit, projected_heat * 100))
        return decision
