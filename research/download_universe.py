"""
Tai vu tru nhieu ma de lam mat cat ngang cho AI policy.

VI SAO CAN BE RONG: xep hang tuong doi chi co y nghia khi co du ma de xep.
Bon ma lon tuong quan 0.85-0.9 khong phai mot mat cat ngang - "chon cai tot nhat
trong bon thu gan giong nhau" gan nhu la chon ngau nhien.

VI SAO LOC THEO LICH SU: mot ma moi len san 3 thang khong the tham gia
walk-forward nhieu nam. Te hon, neu chi giu cac ma "con song den hom nay" thi
ta dinh survivorship bias - nen o day ta giu MOI ma du dai, ke ca ma da chet
thanh khoan, va ghi ro han che nay.

    python -m research.download_universe --top 40 --interval 240 --min-bars 6000
"""
import argparse
import sys
import time

import config
from src import datafeed

LOAI_TRU = ("USDC", "USDE", "FDUSD", "TUSD", "DAI", "USD1", "STETH", "WBTC", "WBETH")


def _lay_top_bybit(n: int):
    from pybit.unified_trading import HTTP
    rows = HTTP(testnet=config.DATA_TESTNET).get_tickers(
        category="spot").get("result", {}).get("list", [])
    out = []
    for r in rows:
        sym = r.get("symbol", "")
        if not sym.endswith("USDT") or any(x in sym for x in LOAI_TRU):
            continue
        try:
            out.append((sym, float(r.get("turnover24h") or 0)))
        except ValueError:
            continue
    out.sort(key=lambda x: -x[1])
    return [s for s, _ in out[:n]]


def _lay_top_okx(n: int):
    import requests
    from src.okx_client import _from_okx_symbol
    resp = requests.get("https://www.okx.com/api/v5/market/tickers",
                        params={"instType": "SPOT"}, timeout=15)
    rows = resp.json().get("data", [])
    out = []
    for r in rows:
        inst_id = r.get("instId", "")
        if not inst_id.endswith("-USDT"):
            continue
        sym = _from_okx_symbol(inst_id)
        if any(x in sym for x in LOAI_TRU):
            continue
        try:
            # volCcy24h = khoi luong 24h theo dong tien bao gia (USDT) - tuong
            # duong turnover24h cua Bybit.
            out.append((sym, float(r.get("volCcy24h") or 0)))
        except ValueError:
            continue
    out.sort(key=lambda x: -x[1])
    return [s for s, _ in out[:n]]


def lay_top(n: int):
    return _lay_top_okx(n) if config.EXCHANGE == "okx" else _lay_top_bybit(n)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--interval", default="240")
    ap.add_argument("--bars", type=int, default=12000)
    ap.add_argument("--min-bars", type=int, default=6000,
                    help="bo ma khong du lich su cho walk-forward")
    ap.add_argument("--symbols", default=None, help="danh sach tu chon, phay ngan cach")
    args = ap.parse_args()

    from src.exchange import build_client
    client = build_client(config, testnet=config.DATA_TESTNET)

    syms = ([s.strip().upper() for s in args.symbols.split(",")] if args.symbols
            else lay_top(args.top))
    print("Nguon: %s (%s) | %d ma | khung %s"
          % (config.EXCHANGE, "TESTNET (!)" if config.DATA_TESTNET else "mainnet",
             len(syms), args.interval))

    giu, bo = [], []
    for i, sym in enumerate(syms, 1):
        try:
            df = datafeed.download_history(client, sym, args.interval,
                                           total_bars=args.bars, use_cache=True)
        except Exception as e:
            print("%3d. %-14s LOI: %s" % (i, sym, str(e)[:60]))
            bo.append((sym, 0))
            continue
        n = len(df)
        if n >= args.min_bars:
            giu.append(sym)
            print("%3d. %-14s %6d nen  %s -> %s  GIU"
                  % (i, sym, n, str(df["datetime"].iloc[0])[:10],
                     str(df["datetime"].iloc[-1])[:10]))
        else:
            bo.append((sym, n))
            print("%3d. %-14s %6d nen  (< %d) bo" % (i, sym, n, args.min_bars))
        time.sleep(0.15)

    print("\n%d ma du dieu kien, %d ma bi bo." % (len(giu), len(bo)))
    print("---VU TRU---")
    print(",".join(giu))
    return 0


if __name__ == "__main__":
    sys.exit(main())
