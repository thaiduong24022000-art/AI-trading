"""
Diem vao cho backtest va walk-forward - Nang cap 4.

    python run_backtest.py download    --symbol BTCUSDT --bars 8000
    python run_backtest.py backtest    --symbol BTCUSDT
    python run_backtest.py walkforward --strategy all

Ba lenh nay tuong ung ba viec khac nhau:

  download    tai lich su ve cache CSV (can pybit + mang).
  backtest    chay CA ENSEMBLE mot lan tren toan bo du lieu. Dung de xem he
              thong co chay dung khong, KHONG dung de ket luan chien luoc lai.
  walkforward toi uu tren train / kiem dinh tren test, truot cua so. Chi so
              out-of-sample cua lenh nay moi la thu duy nhat dang tin, va chi
              no moi quyet dinh mot chien luoc co duoc len live hay khong.

Neu ban dinh nhin mot con so de quyet dinh, hay nhin so cua walkforward.
"""
import argparse
import logging
import os
import sys
from typing import Dict, List, Optional

import pandas as pd

import config
from backtest import engine, metrics, report, walkforward
from src import datafeed, indicators
from src.strategies import ALL_STRATEGIES, build_default_ensemble

logger = logging.getLogger("backtest")

STRATEGY_BY_NAME = {cls.name: cls for cls in ALL_STRATEGIES}


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)-7s %(name)s | %(message)s",
        stream=sys.stdout,
    )


def print_cost_assumptions() -> None:
    """Chi phi phai duoc nhin thay trong moi lan chay.

    Mot chien luoc nham bien dong 0.3%/lenh nghe hap dan cho den khi tru phi.
    In ra day de khong ai quen ket qua nay duoc tinh voi chi phi nao.
    """
    roundtrip = (config.FEE_TAKER + config.SLIPPAGE) * 2
    print("Chi phi ap dung: phi taker %.3f%% | slippage %.3f%% moi chieu "
          "=> mot vong mua-ban ton %.3f%%"
          % (config.FEE_TAKER * 100, config.SLIPPAGE * 100, roundtrip * 100))


def load_data(args) -> Optional[pd.DataFrame]:
    """Lay du lieu theo thu tu uu tien: --csv > --synthetic > cache CSV."""
    if args.csv:
        df = pd.read_csv(args.csv)
        print("Nguon du lieu: %s (%d nen)" % (args.csv, len(df)))
        return df

    if args.synthetic:
        df = datafeed.synthetic_ohlcv(n=args.bars, seed=args.seed)
        print("!" * 70)
        print("DU LIEU TONG HOP (ngau nhien) - chi de kiem tra code chay dung.")
        print("Loi/lo tren du lieu nay KHONG co y nghia du bao. Neu mot chien")
        print("luoc 'co lai' tren nhieu ngau nhien, do la dau hieu overfit.")
        print("!" * 70)
        return df

    interval = getattr(args, "interval", None) or config.KLINE_INTERVAL
    df = datafeed.load_cache(args.symbol, interval)
    if df is None:
        print("Khong co cache cho %s khung %s." % (args.symbol, interval))
        print("Chay truoc:  python run_backtest.py download --symbol %s --interval %s"
              % (args.symbol, interval))
        print("Hoac test code voi du lieu gia:  them co --synthetic")
        return None
    print("Nguon du lieu: cache %s khung %s (%d nen)" % (args.symbol, interval, len(df)))
    return df


def _group_pnl(trades: List[dict], key: str) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for t in trades:
        bucket = out.setdefault(t.get(key) or "?", {"n": 0.0, "pnl": 0.0, "wins": 0.0})
        bucket["n"] += 1
        bucket["pnl"] += float(t.get("pnl", 0.0))
        bucket["wins"] += 1 if float(t.get("pnl", 0.0)) > 0 else 0
    return out


def _print_breakdown(title: str, groups: Dict[str, Dict[str, float]]) -> None:
    if not groups:
        return
    print("\n%s" % title)
    for name, s in sorted(groups.items(), key=lambda kv: -kv[1]["pnl"]):
        win_rate = s["wins"] / s["n"] * 100 if s["n"] else 0.0
        print("  %-18s lenh=%3d | win=%5.1f%% | pnl=%+10.2f" % (name, s["n"], win_rate, s["pnl"]))


# ==========================================================
# Lenh: download
# ==========================================================
def cmd_download(args) -> int:
    try:
        from src.exchange import build_client
        # Du lieu lich su luon tu mainnet - xem chu thich DATA_TESTNET trong config.
        client = build_client(config, testnet=config.DATA_TESTNET)
        print("Nguon du lieu: %s (%s)" % (config.EXCHANGE,
              "TESTNET (!)" if config.DATA_TESTNET else "mainnet"))
    except ImportError as e:
        print("Khong tai duoc du lieu: %s" % e)
        return 1
    except Exception as e:
        print("Loi ket noi san: %s" % e)
        return 1

    interval = args.interval or config.KLINE_INTERVAL
    df = datafeed.download_history(client, args.symbol, interval,
                                   total_bars=args.bars, use_cache=False)
    if df.empty:
        print("San khong tra ve du lieu nao.")
        return 1
    print("Da tai %d nen %s khung %s (%s -> %s)"
          % (len(df), args.symbol, interval, df["datetime"].iloc[0], df["datetime"].iloc[-1]))
    return 0


# ==========================================================
# Lenh: backtest
# ==========================================================
def cmd_backtest(args) -> int:
    df = load_data(args)
    if df is None:
        return 1
    if len(df) < indicators.warmup_bars() + 50:
        print("Chi co %d nen, can it nhat %d de co tin hieu hop le."
              % (len(df), indicators.warmup_bars() + 50))
        return 1

    print_cost_assumptions()
    strategies = ([STRATEGY_BY_NAME[args.strategy]()] if args.strategy != "all"
                  else build_default_ensemble())
    print("Chien luoc: %s | regime switching: %s"
          % (", ".join(s.name for s in strategies), "co" if not args.no_regime else "khong"))

    bpy = metrics.bars_per_year(args.interval or config.KLINE_INTERVAL)
    result = engine.run(df, strategies, initial_equity=args.equity, cfg=config,
                        use_regime=not args.no_regime, symbol=args.symbol)
    m = metrics.compute(result.trades, result.equity_curve, args.equity, bars_per_year=bpy)

    print("\n" + "=" * 70)
    print("KET QUA BACKTEST: %s" % args.symbol)
    print("=" * 70)
    print("  %s" % m.summary())
    print("  Von cuoi: %.2f (bat dau %.2f)" % (m.final_equity, args.equity))
    print("  Ky vong moi lenh: %+.2f | thang TB %+.2f | thua TB %+.2f"
          % (m.expectancy, m.avg_win, m.avg_loss))
    print("  Tin hieu duoc risk engine cho qua: %d | bi tu choi: %d"
          % (result.signals_generated, result.rejected_by_risk))
    if result.breaker_trips:
        print("  Circuit breaker bat %d lan (moi lan la mot lan can NGUOI vao xem)"
              % result.breaker_trips)

    if m.num_trades and m.total_fees:
        gross = m.final_equity - args.equity + m.total_fees
        print("  Lai TRUOC phi: %+.2f -> SAU phi: %+.2f (phi an mat %.2f)"
              % (gross, m.final_equity - args.equity, m.total_fees))

    _print_breakdown("Theo chien luoc:", _group_pnl(result.trades, "strategy"))
    _print_breakdown("Theo regime luc vao lenh:", _group_pnl(result.trades, "regime"))
    _print_breakdown("Theo ly do thoat:", _group_pnl(result.trades, "exit_reason"))

    print("\nLUU Y: day la backtest MOT LAN tren toan bo du lieu. No cho biet he")
    print("thong co chay dung khong. No KHONG du de ket luan chien luoc co lai:")
    print("dung 'walkforward' cho viec do.")

    if args.save_trades and result.trades:
        pd.DataFrame(result.trades).to_csv(args.save_trades, index=False)
        print("\nDa luu %d lenh vao %s" % (len(result.trades), args.save_trades))

    if args.report:
        path = report.render(result, m, df, config, args.symbol, args.equity,
                             [s.name for s in strategies], args.report)
        print("\nDa sinh bao cao HTML: %s" % os.path.abspath(path))
        print("Mo bang trinh duyet de xem duong von va bang phan tich.")
    return 0


# ==========================================================
# Lenh: walkforward
# ==========================================================
def cmd_walkforward(args) -> int:
    df = load_data(args)
    if df is None:
        return 1

    needed = args.train_bars + args.test_bars
    if len(df) < needed:
        print("Chi co %d nen nhung mot cua so can %d (train %d + test %d)."
              % (len(df), needed, args.train_bars, args.test_bars))
        print("Tai them du lieu, hoac giam --train-bars/--test-bars.")
        return 1

    print_cost_assumptions()
    df = indicators.add_indicators(df)
    names = list(STRATEGY_BY_NAME) if args.strategy == "all" else [args.strategy]
    print("Cua so: train=%d nen, test=%d nen, buoc=%d nen | so cua so ~%d"
          % (args.train_bars, args.test_bars, args.step_bars,
             max(0, (len(df) - needed) // args.step_bars + 1)))

    reports = []
    for name in names:
        print("\nDang chay walk-forward cho %s ..." % name)
        report = walkforward.walk_forward(
            df, STRATEGY_BY_NAME[name],
            train_bars=args.train_bars, test_bars=args.test_bars,
            step_bars=args.step_bars, initial_equity=args.equity, cfg=config,
            bars_per_year=metrics.bars_per_year(args.interval or config.KLINE_INTERVAL),
        )
        print(report.summary())
        reports.append(report)

    print("\n" + "=" * 70)
    print("TONG KET - chien luoc nao du dieu kien len live")
    print("=" * 70)
    for r in reports:
        print("  %-18s %s" % (r.strategy, "DAT" if r.gates_passed else "KHONG DAT"))
    if not any(r.gates_passed for r in reports):
        print("\nKhong chien luoc nao vuot cong. Day la ket qua BINH THUONG va")
        print("dung dan - cong duoc dat cao co chu dich. Khong ha nguong cong de")
        print("cho chien luoc di qua: nguong ton tai chinh de chan viec do.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backtest va walk-forward cho AI Trade Bot v2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p):
        p.add_argument("--symbol", default="BTCUSDT")
        p.add_argument("--equity", type=float, default=10000.0)
        p.add_argument("--csv", help="doc du lieu tu file CSV cu the")
        p.add_argument("--synthetic", action="store_true",
                       help="dung du lieu ngau nhien de kiem tra code (khong co y nghia loi/lo)")
        p.add_argument("--bars", type=int, default=3000, help="so nen khi dung --synthetic")
        p.add_argument("--seed", type=int, default=42)
        p.add_argument("--interval", default=None,
                       help="60=1h, 240=4h, D=1 ngay (mac dinh: theo config)")

    p_dl = sub.add_parser("download", help="tai lich su tu Bybit ve cache")
    p_dl.add_argument("--symbol", default="BTCUSDT")
    p_dl.add_argument("--bars", type=int, default=8000)
    p_dl.add_argument("--interval", default=None,
                      help="60=1h, 240=4h, D=1 ngay (mac dinh: theo config)")
    p_dl.set_defaults(func=cmd_download)

    p_bt = sub.add_parser("backtest", help="chay backtest mot lan tren toan bo du lieu")
    add_common(p_bt)
    p_bt.add_argument("--strategy", default="all", choices=["all"] + list(STRATEGY_BY_NAME))
    p_bt.add_argument("--no-regime", action="store_true",
                      help="bo regime switching, cac chien luoc trong so bang nhau")
    p_bt.add_argument("--save-trades", help="xuat danh sach lenh ra file CSV")
    p_bt.add_argument("--report", nargs="?", const="bao_cao_backtest.html",
                      help="sinh bao cao HTML (mac dinh: bao_cao_backtest.html)")
    p_bt.set_defaults(func=cmd_backtest)

    p_wf = sub.add_parser("walkforward", help="walk-forward + cong thong ke (ket qua dang tin)")
    add_common(p_wf)
    p_wf.add_argument("--strategy", default="all", choices=["all"] + list(STRATEGY_BY_NAME))
    p_wf.add_argument("--train-bars", type=int, default=4320, help="~6 thang khung 1h")
    p_wf.add_argument("--test-bars", type=int, default=1440, help="~2 thang khung 1h")
    p_wf.add_argument("--step-bars", type=int, default=1440)
    p_wf.set_defaults(func=cmd_walkforward)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
