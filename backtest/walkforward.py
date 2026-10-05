"""
Walk-forward analysis + cong thong ke - Nang cap 4.

VAN DE MA FILE NAY GIAI QUYET:
Toi uu tham so tren toan bo lich su roi khoe ket qua la overfit kinh dien.
Voi du lieu du dai va du tham so, ban LUON tim duoc bo tham so trong tuyet voi
trong qua khu va vo dung trong tuong lai.

CACH LAM DUNG:
  - Chia lich su thanh cac cua so truot: toi uu tren train, kiem dinh tren test.
  - Chi ket qua tren phan TEST (out-of-sample) moi duoc tinh.
  - So sanh hieu suat IS va OOS: neu OOS te hon nhieu -> da overfit.

Chien luoc chi duoc dua len live khi vuot TAT CA cong thong ke o cuoi file.
"""
import itertools
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Type

import numpy as np
import pandas as pd

import config
from src import indicators
from src import regime as regime_mod
from src.strategies.base import Strategy
from . import engine, metrics

logger = logging.getLogger(__name__)


# Grid tham so cho tung chien luoc. Co y giu NHO:
# grid cang lon, xac suat tim duoc bo tham so dep do may rui cang cao.
PARAM_GRIDS: Dict[str, Dict[str, Sequence]] = {
    "trend_following": {"ema_fast": [10, 20, 30], "ema_slow": [50, 100], "adx_min": [20.0, 25.0, 30.0]},
    "mean_reversion": {"rsi_oversold": [25.0, 30.0], "rsi_overbought": [70.0, 75.0], "adx_max": [20.0, 25.0]},
    "breakout": {"channel_period": [15, 20, 30], "volume_mult": [1.3, 1.5, 2.0]},
}


@dataclass
class WindowResult:
    train_start: int
    train_end: int
    test_end: int
    best_params: Dict
    is_metrics: metrics.Metrics
    oos_metrics: metrics.Metrics
    trades: List[dict] = field(default_factory=list)


@dataclass
class WalkForwardReport:
    strategy: str
    windows: List[WindowResult] = field(default_factory=list)
    oos_metrics: metrics.Metrics = field(default_factory=metrics.Metrics)
    is_metrics_avg: metrics.Metrics = field(default_factory=metrics.Metrics)
    gates_passed: bool = False
    gate_details: Dict[str, bool] = field(default_factory=dict)
    gate_messages: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "=" * 70,
            "WALK-FORWARD: %s" % self.strategy,
            "  So cua so: %d" % len(self.windows),
            "  OOS: %s" % self.oos_metrics.summary(),
            "  IS trung binh Sharpe: %.2f" % self.is_metrics_avg.sharpe,
            "-" * 70,
            "  CONG THONG KE: %s" % ("DAT" if self.gates_passed else "KHONG DAT"),
        ]
        lines.extend("    %s" % m for m in self.gate_messages)
        lines.append("=" * 70)
        return "\n".join(lines)


def _param_combinations(grid: Dict[str, Sequence]) -> List[Dict]:
    if not grid:
        return [{}]
    keys = list(grid)
    return [dict(zip(keys, values)) for values in itertools.product(*(grid[k] for k in keys))]


def walk_forward(
    df: pd.DataFrame,
    strategy_cls: Type[Strategy],
    train_bars: int = 4320,     # ~6 thang khung 1h
    test_bars: int = 1440,      # ~2 thang
    step_bars: int = 1440,
    initial_equity: float = 10000.0,
    cfg=config,
    param_grid: Dict[str, Sequence] = None,
    bars_per_year: int = 8760,
) -> WalkForwardReport:
    """Chay walk-forward cho MOT chien luoc.

    bars_per_year phai khop voi khung thoi gian cua df (metrics.bars_per_year()).
    De mac dinh 8760 khi chay khung 4h se thoi phong Sharpe len gap 2, va cong
    Sharpe >= 1.0 se cho di qua nhung chien luoc dang le truot.
    """
    if "atr" not in df.columns:
        df = indicators.add_indicators(df)
    df = df.reset_index(drop=True)

    grid = param_grid if param_grid is not None else PARAM_GRIDS.get(strategy_cls.name, {})
    combos = _param_combinations(grid)
    report = WalkForwardReport(strategy=strategy_cls.name)

    warmup = indicators.warmup_bars()
    start = 0
    equity = initial_equity
    all_oos_trades: List[dict] = []
    oos_equity_parts: List[pd.Series] = []
    is_sharpes: List[float] = []

    while start + train_bars + test_bars <= len(df):
        train_df = df.iloc[start: start + train_bars]
        test_df = df.iloc[start + train_bars - warmup: start + train_bars + test_bars]

        # --- toi uu tren train ---
        best_params, best_score, best_is = None, -np.inf, None
        for params in combos:
            strat = strategy_cls(**params)
            res = engine.run(train_df, [strat], initial_equity, cfg, use_regime=False, symbol="BACKTEST")
            m = metrics.compute(res.trades, res.equity_curve, initial_equity, bars_per_year)
            # Doi toi thieu vai lenh, neu khong Sharpe khong co y nghia
            score = m.sharpe if m.num_trades >= 5 else -np.inf
            if score > best_score:
                best_params, best_score, best_is = params, score, m

        if best_params is None:
            best_params, best_is = combos[0], metrics.Metrics()

        # --- kiem dinh tren test (out-of-sample) ---
        strat = strategy_cls(**best_params)
        res = engine.run(test_df, [strat], equity, cfg, use_regime=False, symbol="BACKTEST")
        oos_m = metrics.compute(res.trades, res.equity_curve, equity, bars_per_year)

        report.windows.append(WindowResult(
            train_start=start, train_end=start + train_bars,
            test_end=start + train_bars + test_bars,
            best_params=best_params, is_metrics=best_is, oos_metrics=oos_m,
            trades=res.trades,
        ))
        all_oos_trades.extend(res.trades)
        if len(res.equity_curve):
            oos_equity_parts.append(res.equity_curve)
            equity = float(res.equity_curve.iloc[-1])
        if best_is and best_is.num_trades >= 5:
            is_sharpes.append(best_is.sharpe)

        start += step_bars

    if oos_equity_parts:
        combined = pd.concat(oos_equity_parts, ignore_index=True)
        report.oos_metrics = metrics.compute(all_oos_trades, combined, initial_equity,
                                             bars_per_year)
    report.is_metrics_avg = metrics.Metrics(sharpe=float(np.mean(is_sharpes)) if is_sharpes else 0.0)

    _apply_gates(report, cfg)
    return report


def _apply_gates(report: WalkForwardReport, cfg=config) -> None:
    """Cong thong ke - chien luoc phai vuot TAT CA moi duoc len live."""
    m = report.oos_metrics
    checks = {}

    checks["so_lenh"] = m.num_trades >= cfg.GATE_MIN_TRADES
    report.gate_messages.append(
        "So lenh OOS: %d (can >= %d) -> %s"
        % (m.num_trades, cfg.GATE_MIN_TRADES, "OK" if checks["so_lenh"] else "THIEU"))

    checks["sharpe"] = m.sharpe >= cfg.GATE_MIN_SHARPE
    report.gate_messages.append(
        "Sharpe OOS: %.2f (can >= %.2f) -> %s"
        % (m.sharpe, cfg.GATE_MIN_SHARPE, "OK" if checks["sharpe"] else "KHONG DAT"))

    checks["drawdown"] = m.max_drawdown <= cfg.GATE_MAX_DRAWDOWN
    report.gate_messages.append(
        "Max drawdown: %.2f%% (can <= %.2f%%) -> %s"
        % (m.max_drawdown * 100, cfg.GATE_MAX_DRAWDOWN * 100,
           "OK" if checks["drawdown"] else "QUA SAU"))

    checks["profit_factor"] = m.profit_factor >= cfg.GATE_MIN_PROFIT_FACTOR
    report.gate_messages.append(
        "Profit factor: %.2f (can >= %.2f) -> %s"
        % (m.profit_factor, cfg.GATE_MIN_PROFIT_FACTOR,
           "OK" if checks["profit_factor"] else "KHONG DAT"))

    # Co lai o it nhat 2 trong 3 regime. Mot chien luoc chi lai trong dung mot
    # loai thi truong se chet ngay khi thi truong doi che do.
    # LUU Y khi doc ket qua: ba chien luoc goc la CHUYEN GIA THEO REGIME
    # (Nang cap 2), nen chuyen dung mot minh chung thuong truot cong nay.
    # Do la thong tin dung: no noi rang chien luoc do khong duoc chay don doc,
    # chu khong noi rang no vo dung trong ensemble.
    regime_stats = metrics.by_regime([t for w in report.windows for t in w.trades])
    profitable = [r for r in regime_mod.ALL_REGIMES
                  if regime_stats.get(r, {}).get("pnl", 0.0) > 0]
    checks["regime"] = len(profitable) >= 2
    detail = ", ".join(
        "%s(n=%d, pnl=%+.2f)" % (r, regime_stats[r]["num_trades"], regime_stats[r]["pnl"])
        for r in regime_mod.ALL_REGIMES if r in regime_stats) or "khong co lenh"
    report.gate_messages.append(
        "Co lai theo regime: %d/3 [%s] -> %s"
        % (len(profitable), detail, "OK" if checks["regime"] else "PHU THUOC MOT REGIME"))

    is_sharpe = report.is_metrics_avg.sharpe
    if is_sharpe > 0:
        degradation = 1.0 - (m.sharpe / is_sharpe)
        checks["overfit"] = degradation <= cfg.GATE_MAX_DEGRADATION
        report.gate_messages.append(
            "Suy giam IS->OOS: %.0f%% (can <= %.0f%%) -> %s"
            % (degradation * 100, cfg.GATE_MAX_DEGRADATION * 100,
               "OK" if checks["overfit"] else "DAU HIEU OVERFIT"))
    else:
        checks["overfit"] = False
        report.gate_messages.append("Suy giam IS->OOS: khong danh gia duoc (IS Sharpe <= 0)")

    report.gate_details = checks
    report.gates_passed = all(checks.values())
