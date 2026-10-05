"""
Backtest engine - Nang cap 4.

BON QUY TAC TRUNG THUC duoc cai cung trong file nay:

1. KHONG LOOKAHEAD. Tin hieu tai nen i chi nhin du lieu den het nen i (da dong).
   Lenh khop tai gia MO CUA cua nen i+1. Khong bao gio khop tai gia dong cua
   chinh cay nen sinh ra tin hieu - do la cach tu lua pho bien nhat va no lam
   moi chien luoc trong dep hon that.

2. CO PHI VA SLIPPAGE ca hai chieu. Mot vong mua-ban spot ton ~0.2%.
   Rat nhieu "chien luoc thang" bien mat hoan toan sau buoc nay.

3. STOP/TP KIEM TRA TRONG NEN, gia dinh BI QUAN: neu mot nen cham ca stop lan
   take-profit, coi nhu cham STOP truoc. Ta khong biet thu tu trong nen, va doan
   theo huong co loi cho minh cung la mot dang lookahead.

4. SIZING THAT: dung chinh RiskManager cua bot live, khong phai all-in moi lenh.
   Backtest voi sizing khac live thi ket qua khong chuyen giao duoc.
"""
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

import numpy as np
import pandas as pd

import config
from src import indicators
from src import regime as regime_mod
from src.allocator import Allocation, allocate, combine_signals
from src.risk_manager import CircuitBreaker, Position, RiskManager
from src.strategies.base import BUY, HOLD, SELL, Strategy

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    trades: List[dict] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    initial_equity: float = 10000.0
    rejected_by_risk: int = 0
    signals_generated: int = 0
    breaker_trips: int = 0


def _apply_slippage(price: float, side: str, cfg) -> float:
    """Slippage luon lam gia te di cho nguoi dat lenh."""
    return price * (1.0 + cfg.SLIPPAGE) if side == "Buy" else price * (1.0 - cfg.SLIPPAGE)


def run(
    df: pd.DataFrame,
    strategies: Sequence[Strategy],
    initial_equity: float = 10000.0,
    cfg=config,
    use_regime: bool = True,
    symbol: str = "BACKTEST",
) -> BacktestResult:
    """Chay backtest bar-by-bar tren mot ma.

    use_regime=False: bo qua phan loai regime va allocator, cac chien luoc
    duoc coi trong so bang nhau. Dung khi kiem dinh MOT chien luoc rieng le
    (walk-forward) - luc do ta danh gia chinh chien luoc do, khong phai ensemble.
    """
    if "atr" not in df.columns:
        df = indicators.add_indicators(df)
    df = df.reset_index(drop=True)

    # Tinh truoc chi bao rieng cua tung chien luoc MOT LAN.
    # Bo buoc nay thi backtest la O(n^2) va walk-forward khong chay noi.
    for strat in strategies:
        df = strat.prepare(df)

    result = BacktestResult(initial_equity=initial_equity)
    warmup = max(indicators.warmup_bars(), 60)
    if len(df) <= warmup + 5:
        logger.warning("Khong du du lieu de backtest (%d nen)", len(df))
        result.equity_curve = pd.Series([initial_equity])
        return result

    # Vong lap nong: dung numpy thay vi df.iloc de tranh tao Series moi nen
    open_ = df["open"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    atr_arr = df["atr"].to_numpy(dtype=float)
    ts_arr = (df["timestamp"].to_numpy() if "timestamp" in df.columns
              else np.arange(len(df), dtype=float))

    equal_weights = Allocation(weights={s.name: 1.0 for s in strategies}, regime="n/a")

    # Moc ngay theo TIMESTAMP CUA NEN, khong theo dong ho he thong.
    # CircuitBreaker.reset_daily() dua vao date.today(), ma trong backtest
    # "hom nay" khong bao gio doi -> consecutive_losses khong bao gio ve 0 va
    # ca lan chay chet han o chuoi thua dau tien. Ban live khong co van de nay
    # vi ngay that su troi qua.
    has_ts = "timestamp" in df.columns
    day_arr = (ts_arr.astype("int64") // 86_400_000) if has_ts else None

    equity = initial_equity
    equity_history: List[float] = []
    breaker = CircuitBreaker(cfg)
    rm = RiskManager(cfg, breaker)
    position: Optional[Position] = None
    entry_ts = None
    entry_fees = 0.0
    entry_slip = 0.0
    entry_regime = regime_mod.UNKNOWN

    def close_position(pos: Position, raw_price: float, reason: str, bar_i: int) -> float:
        """Dong vi the tai raw_price, tra ve pnl da tru phi hai chieu."""
        close_side = "Sell" if pos.side == "Buy" else "Buy"
        fill = _apply_slippage(raw_price, close_side, cfg)
        exit_fee = fill * pos.qty * cfg.FEE_TAKER
        exit_slip = abs(fill - raw_price) * pos.qty
        gross = ((fill - pos.entry_price) * pos.qty if pos.side == "Buy"
                 else (pos.entry_price - fill) * pos.qty)
        pnl = gross - exit_fee - entry_fees
        result.trades.append({
            "symbol": symbol, "strategy": pos.strategy, "side": pos.side, "qty": pos.qty,
            "entry_price": pos.entry_price, "exit_price": fill,
            "entry_ts": entry_ts, "exit_ts": ts_arr[bar_i],
            "pnl": pnl, "pnl_pct": pnl / initial_equity,
            "fees": entry_fees + exit_fee, "exit_reason": reason,
            "slippage": entry_slip + exit_slip,
            "bars_held": bar_i - int(pos.opened_at or bar_i),
            "regime": entry_regime,
        })
        breaker.record_trade_result(pnl)
        rm.remove_position(pos.symbol)
        return pnl

    current_day = day_arr[warmup] if has_ts else None

    for i in range(warmup, len(df) - 1):
        nxt = i + 1

        # ---------- 0. Sang ngay moi ----------
        if has_ts and day_arr[nxt] != current_day:
            current_day = day_arr[nxt]
            breaker.reset_daily(equity)
            if breaker.tripped:
                # Ban live doi NGUOI kiem tra roi reset. Backtest gia dinh nguoi
                # do lam viec do vao dau ngay hom sau, va DEM lai so lan phai lam:
                # mot chien luoc bat breaker 30 lan la chien luoc khong van hanh
                # duoc, du bang lai/lo cua no co dep den dau.
                result.breaker_trips += 1
                breaker.manual_reset(log=False)

        # ---------- 1. Stop-loss / take-profit ----------
        if position is not None:
            if position.side == "Buy":
                hit_stop = low[nxt] <= position.stop_loss
                hit_tp = high[nxt] >= position.take_profit
            else:
                hit_stop = high[nxt] >= position.stop_loss
                hit_tp = low[nxt] <= position.take_profit

            # Gia dinh bi quan: cham ca hai trong mot nen -> stop truoc
            if hit_stop:
                equity += close_position(position, position.stop_loss, "stop_loss", nxt)
                position, entry_fees, entry_slip = None, 0.0, 0.0
            elif hit_tp:
                equity += close_position(position, position.take_profit, "take_profit", nxt)
                position, entry_fees, entry_slip = None, 0.0, 0.0

        # ---------- 2. Tin hieu cho nen nay ----------
        action, strength = HOLD, 0.0
        signals: List = []
        reg = None
        if not breaker.tripped:
            signals = [s.generate_at(df, i) for s in strategies]
            if any(s.is_actionable for s in signals):
                if use_regime:
                    reg = regime_mod.classify_at(df, i, cfg)
                    alloc = allocate(strategies, reg, performance=None, cfg=cfg)
                else:
                    alloc = equal_weights
                action, strength, _ = combine_signals(signals, alloc, cfg)

        # ---------- 2b. Thoat khi tin hieu dao chieu ----------
        # Trend-following phai thoat khi xu huong quay dau, khong doi cham stop.
        # Bo qua buoc nay lam backtest trong te hon thuc te dang ke.
        if position is not None and action in (BUY, SELL):
            is_opposite = ((position.side == "Buy" and action == SELL)
                           or (position.side == "Sell" and action == BUY))
            if is_opposite:
                equity += close_position(position, open_[nxt], "signal_reverse", nxt)
                position, entry_fees, entry_slip = None, 0.0, 0.0

        # ---------- 3. Vao lenh moi ----------
        if position is None and not breaker.tripped and action in (BUY, SELL):
            result.signals_generated += 1
            side = "Buy" if action == BUY else "Sell"
            raw_entry = float(open_[nxt])
            entry_price = _apply_slippage(raw_entry, side, cfg)
            atr_value = float(atr_arr[i]) if not np.isnan(atr_arr[i]) else 0.0

            decision = rm.evaluate(symbol, side, entry_price, atr_value, equity, strength)
            if decision.approved:
                entry_fees = entry_price * decision.qty * cfg.FEE_TAKER
                entry_slip = abs(entry_price - raw_entry) * decision.qty
                # Nhan regime luc vao lenh: can cho cong "co lai o >= 2/3 regime".
                # Tinh ca khi use_regime=False, vi day la NHAN de danh gia sau,
                # khong tham gia vao quyet dinh vao lenh.
                if reg is None:
                    reg = regime_mod.classify_at(df, i, cfg)
                entry_regime = reg.regime
                winner = max((s for s in signals if s.action == action),
                             key=lambda s: s.strength, default=None)
                position = Position(
                    symbol=symbol, side=side, qty=decision.qty, entry_price=entry_price,
                    stop_loss=decision.stop_loss, take_profit=decision.take_profit,
                    strategy=winner.strategy if winner else "ensemble", opened_at=i,
                )
                rm.register_position(position)
                entry_ts = ts_arr[nxt]
            else:
                result.rejected_by_risk += 1

        # ---------- 4. Ghi von (mark-to-market) ----------
        if position is not None:
            mark = float(close[nxt])
            unrealized = ((mark - position.entry_price) * position.qty if position.side == "Buy"
                          else (position.entry_price - mark) * position.qty)
            equity_history.append(equity + unrealized)
        else:
            equity_history.append(equity)

        breaker.check_equity(equity_history[-1])

    result.equity_curve = pd.Series(equity_history)
    return result
