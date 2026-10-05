"""
Phase 0 - Strategy Validation.

CAU HOI: co chien luoc nao co bien do duong khong, o khung nao, regime nao,
va no co GIU DUOC tren nhieu ma khac nhau khong?

    python run_phase0.py                                      # BTC, ca 3 khung
    python run_phase0.py --symbols BTCUSDT,ETHUSDT --timeframes 60

BON RANG BUOC de ket qua co nghia:

1. KHONG TUNE THAM SO. Dung default_params. Khong co tim kiem tham so thi
   khong co overfit tu tim kiem - do la thu lam mot lan backtest don tro nen
   hop le.

2. CUNG MOT KY cho moi ma va moi khung. Neu khong cat ve chung mot khoang, cau
   hoi "4H co hon 1H khong" bi lan voi "2021 khac 2022 khong".

3. CHAY CA LONG-ONLY LAN LONG+SHORT, vi voi ALLOW_SHORT=False thi 48% tin hieu
   bi chan sach - khong the phan biet "chien luoc te" voi "ta chi lay mot nua".

4. NHIEU MA la kiem dinh manh hon nhieu du lieu cua CUNG mot ma. Neu mot bien do
   chi xuat hien tren BTC thi do la may; neu no xuat hien tren ca bon thi no co
   the la cau truc that.
   NHUNG: BTC/ETH/SOL/BNB tuong quan 0.85-0.9, nen bon ma KHONG phai bon phep
   thu doc lap. Coi chung nhu bon bang chung rieng biet la tu lua - dung chinh
   lap luan cua Nang cap 3 ve tran tuong quan.

Khong ML, khong LLM trong file nay.
"""
import argparse
import os
import sys
import types
from typing import Dict, List

import pandas as pd

import config
from backtest import engine, metrics
from src import datafeed, indicators
from src.strategies import ALL_STRATEGIES, build_default_ensemble

LABELS = {"60": "1H", "240": "4H", "D": "1D"}
INITIAL_EQUITY = 10000.0
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "reports")
MODES = (("long-only", False), ("long+short", True))


def cfg_for(allow_short: bool):
    c = types.SimpleNamespace(**{k: getattr(config, k) for k in dir(config) if k.isupper()})
    c.ALLOW_SHORT = allow_short
    return c


def load(symbol: str, interval: str) -> pd.DataFrame:
    df = datafeed.load_cache(symbol, interval)
    if df is None:
        raise SystemExit(
            "Thieu cache %s khung %s. Chay: python run_backtest.py download "
            "--symbol %s --interval %s --bars 35000" % (symbol, interval, symbol, interval))
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df


def buy_hold(df: pd.DataFrame, n_curve: int) -> float:
    off = max(0, len(df) - n_curve - 1)
    c = df["close"].to_numpy()[off:]
    return (c[-1] / c[0] - 1) if len(c) > 1 else 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 0 - Strategy Validation")
    ap.add_argument("--symbols", default="BTCUSDT")
    ap.add_argument("--timeframes", default="60,240,D")
    args = ap.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    intervals = [t.strip() for t in args.timeframes.split(",") if t.strip()]

    frames = {(s, iv): load(s, iv) for s in symbols for iv in intervals}
    goc = {k: (v["datetime"].iloc[0], v["datetime"].iloc[-1]) for k, v in frames.items()}

    start = max(v[0] for v in goc.values())
    end = min(v[1] for v in goc.values())
    for k, f in frames.items():
        frames[k] = f[(f["datetime"] >= start) & (f["datetime"] <= end)].reset_index(drop=True)

    warmup = indicators.warmup_bars()
    print("=" * 112)
    print("PHASE 0 - STRATEGY VALIDATION")
    print("Ma: %s | Khung: %s" % (", ".join(symbols),
                                  ", ".join(LABELS.get(i, i) for i in intervals)))
    print("Ky chung: %s -> %s" % (str(start)[:16], str(end)[:16]))
    print("Lich su goc tung nguon (truoc khi cat ve ky chung):")
    for (s, iv), (a, b) in sorted(goc.items()):
        print("   %-9s %-3s %s -> %s" % (s, LABELS.get(iv, iv), str(a)[:10], str(b)[:10]))
    print("So nen dung duoc sau %d nen warmup:" % warmup)
    for (s, iv), f in sorted(frames.items()):
        n = len(f) - warmup
        print("   %-9s %-3s %6d %s" % (s, LABELS.get(iv, iv), max(0, n),
                                       "<-- QUA IT" if n < 400 else ""))
    print("Chi phi: taker %.3f%%, slippage %.3f%% moi chieu | Tham so: MAC DINH"
          % (config.FEE_TAKER * 100, config.SLIPPAGE * 100))
    print("Funding: spot khong co. Long+short ngu y futures -> funding CHUA mo hinh hoa.")
    print("=" * 112)

    rows: List[Dict] = []
    regime_rows: List[Dict] = []
    trades_by_key: Dict[tuple, list] = {}

    for symbol in symbols:
        for interval in intervals:
            df = indicators.add_indicators(frames[(symbol, interval)])
            bpy = metrics.bars_per_year(interval)
            for mode, allow_short in MODES:
                cfg = cfg_for(allow_short)
                combos = [(c.name, [c()], False) for c in ALL_STRATEGIES]
                combos.append(("ENSEMBLE", build_default_ensemble(), True))
                for name, strats, use_regime in combos:
                    res = engine.run(df, strats, INITIAL_EQUITY, cfg,
                                     use_regime=use_regime, symbol=symbol)
                    m = metrics.compute(res.trades, res.equity_curve, INITIAL_EQUITY,
                                        bars_per_year=bpy)
                    rows.append({
                        "symbol": symbol, "timeframe": LABELS.get(interval, interval),
                        "strategy": name, "mode": mode,
                        "trades": m.num_trades, "win_rate": m.win_rate,
                        "profit_factor": m.profit_factor, "expectancy": m.expectancy,
                        "net_pnl_pct": m.total_return, "sharpe": m.sharpe,
                        "max_dd": m.max_drawdown, "fees": m.total_fees,
                        "slippage": sum(t.get("slippage", 0.0) for t in res.trades),
                        "buy_hold": buy_hold(df, len(res.equity_curve)),
                    })
                    trades_by_key[(name, mode, LABELS.get(interval, interval))] = \
                        trades_by_key.get((name, mode, LABELS.get(interval, interval)), []) \
                        + res.trades
                    for reg, s in metrics.by_regime(res.trades).items():
                        regime_rows.append({
                            "symbol": symbol, "timeframe": LABELS.get(interval, interval),
                            "strategy": name, "mode": mode, "regime": reg,
                            "trades": int(s["num_trades"]), "pnl": s["pnl"]})

    table = pd.DataFrame(rows)

    hdr = ("%-9s %-4s %-17s %-11s %6s %7s %7s %10s %9s %8s %8s"
           % ("Symbol", "TF", "Strategy", "Mode", "Lenh", "Win%", "PF", "Expect",
              "NetPnL%", "Sharpe", "MaxDD%"))
    for mode, _ in MODES:
        print("\n" + "=" * 112)
        print("CHE DO: %s" % mode.upper())
        print("=" * 112)
        print(hdr)
        print("-" * 112)
        for symbol in symbols:
            for interval in intervals:
                lbl = LABELS.get(interval, interval)
                sub = table[(table["mode"] == mode) & (table["symbol"] == symbol)
                            & (table["timeframe"] == lbl)]
                for _, r in sub.iterrows():
                    pf = ("inf" if r["profit_factor"] == float("inf")
                          else "%.2f" % r["profit_factor"])
                    print("%-9s %-4s %-17s %-11s %6d %7.1f %7s %10.2f %9.2f %8.2f %8.2f%s"
                          % (r["symbol"], r["timeframe"], r["strategy"], r["mode"],
                             r["trades"], r["win_rate"] * 100, pf, r["expectancy"],
                             r["net_pnl_pct"] * 100, r["sharpe"], r["max_dd"] * 100,
                             " (!)" if r["trades"] < 30 else ""))
                if len(sub):
                    print("%-9s %-4s %-17s %-11s %6s %7s %7s %10s %9.2f"
                          % (symbol, lbl, "BUY & HOLD", "-", "-", "-", "-", "-",
                             sub["buy_hold"].iloc[0] * 100))
                print("-" * 112)
        print("(!) = duoi 30 lenh: win rate va PF o day khong ket luan duoc gi")

    # Gop tat ca ma lai: bien do co giu duoc khi doi tai san khong?
    print("\n" + "=" * 112)
    print("GOP TAT CA MA (gop o muc LENH, khong phai trung binh cac ty le)")
    print("Luu y: cac ma nay tuong quan 0.85-0.9 nen day KHONG phai %d phep thu doc lap."
          % len(symbols))
    print("=" * 112)
    print("%-17s %-11s %-4s %6s %7s %7s %10s %12s %8s"
          % ("Strategy", "Mode", "TF", "Lenh", "Win%", "PF", "Expect", "Tong PnL", "Ma lai"))
    print("-" * 112)
    for (name, mode, lbl), trs in sorted(trades_by_key.items()):
        if not trs:
            continue
        pnls = pd.Series([t["pnl"] for t in trs])
        win, loss = pnls[pnls > 0].sum(), -pnls[pnls < 0].sum()
        pf = (win / loss) if loss > 0 else float("inf")
        n_lai = sum(1 for s in symbols
                    if sum(t["pnl"] for t in trs if t["symbol"] == s) > 0)
        print("%-17s %-11s %-4s %6d %7.1f %7s %10.2f %12.2f %6d/%d"
              % (name, mode, lbl, len(pnls), (pnls > 0).mean() * 100,
                 "inf" if pf == float("inf") else "%.2f" % pf,
                 pnls.mean(), pnls.sum(), n_lai, len(symbols)))

    print("\n" + "=" * 112)
    print("EDGE THEO REGIME - chi cac dong DUONG va >= 5 lenh")
    print("=" * 112)
    rt = pd.DataFrame(regime_rows)
    duong = rt[(rt["trades"] >= 5) & (rt["pnl"] > 0)].sort_values("pnl", ascending=False)
    if len(duong):
        print("%-9s %-4s %-17s %-11s %-10s %6s %12s"
              % ("Symbol", "TF", "Strategy", "Mode", "Regime", "Lenh", "PnL"))
        print("-" * 112)
        for _, r in duong.iterrows():
            print("%-9s %-4s %-17s %-11s %-10s %6d %12.2f"
                  % (r["symbol"], r["timeframe"], r["strategy"], r["mode"],
                     r["regime"], r["trades"], r["pnl"]))
        con_lai = rt[(rt["trades"] >= 5) & (rt["pnl"] <= 0)]
        print("\n(%d dong con lai deu AM - xem CSV)" % len(con_lai))
    else:
        print("Khong co dong nao duong.")

    os.makedirs(OUT_DIR, exist_ok=True)
    table.to_csv(os.path.join(OUT_DIR, "phase0_tong_hop.csv"), index=False)
    rt.to_csv(os.path.join(OUT_DIR, "phase0_theo_regime.csv"), index=False)
    print("\nDa luu CSV vao %s" % OUT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
