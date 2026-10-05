"""
Thu thap vi cau truc so lenh - du lieu DUY NHAT con lai chua thu.

VI SAO CAN CHAY TU HOM NAY:
OHLCV, funding va open interest deu tai lai duoc qua khu, va ca ba deu da do:
IC ~ 0. So lenh thi KHONG tai lai duoc - san khong luu lich su L2 cho ai ca.
Ngay nao khong thu la mot ngay lui thoi diem co the kiem dinh. Vi vay file nay
duoc viet de chay lien tuc nhieu thang, khong phai de chay mot lan.

LUU GI: khong luu tick tho (hang GB moi ngay va phan lon la nhieu), ma luu
DAC TRUNG da tong hop theo phut. Doi lai la mat kha nang phat lai sau nay -
mot danh doi co y thuc: thu duoc 6 thang du lieu dung duoc quan trong hon thu
duoc 2 tuan du lieu hoan hao roi het o cung.

DAC TRUNG: mat can bang khoi luong hai ben so lenh la thu ma gia va khoi luong
khong the hien. Khi ben mua day hon ben ban mot cach ben bi, do la ap luc that
chu khong phai mot cay nen dep.

    python -m research.collect_orderbook --symbols BTCUSDT,ETHUSDT --depth 50
"""
import argparse
import csv
import logging
import os
import signal
import sys
import threading
import time
from collections import defaultdict
from typing import Dict, List

import config

logger = logging.getLogger("orderbook")

THU_MUC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "orderbook")
COT = ["timestamp", "datetime", "symbol", "n_mau", "mid", "spread_bps",
       "imb_1", "imb_5", "imb_20", "imb_5_std",
       "depth_bid", "depth_ask", "micro_dev"]

_dung = threading.Event()


class SoLenh:
    """Giu trang thai so lenh cho mot ma va tong hop dac trung theo phut."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.bids: Dict[float, float] = {}
        self.asks: Dict[float, float] = {}
        self.mau: List[dict] = []
        self.khoa = threading.Lock()

    def cap_nhat(self, data: dict, loai: str) -> None:
        with self.khoa:
            if loai == "snapshot":
                self.bids.clear()
                self.asks.clear()
            for gia, sl in data.get("b", []):
                g, s = float(gia), float(sl)
                if s == 0:
                    self.bids.pop(g, None)
                else:
                    self.bids[g] = s
            for gia, sl in data.get("a", []):
                g, s = float(gia), float(sl)
                if s == 0:
                    self.asks.pop(g, None)
                else:
                    self.asks[g] = s

    def lay_mau(self) -> None:
        """Chup mot mau dac trung tu trang thai hien tai."""
        with self.khoa:
            if not self.bids or not self.asks:
                return
            b = sorted(self.bids.items(), key=lambda x: -x[0])
            a = sorted(self.asks.items(), key=lambda x: x[0])

        bid, ask = b[0][0], a[0][0]
        if bid <= 0 or ask <= bid:
            return
        mid = (bid + ask) / 2.0

        def imb(n: int) -> float:
            vb = sum(v for _, v in b[:n])
            va = sum(v for _, v in a[:n])
            t = vb + va
            return (vb - va) / t if t > 0 else 0.0

        vb1, va1 = b[0][1], a[0][1]
        # Microprice: gia "that" co trong so theo khoi luong doi dien. Lech khoi
        # mid la ap luc tuc thoi - mot trong nhung tin hieu vi cau truc co ban nhat.
        micro = (bid * va1 + ask * vb1) / (vb1 + va1) if (vb1 + va1) > 0 else mid

        self.mau.append({
            "mid": mid,
            "spread_bps": (ask - bid) / mid * 10000.0,
            "imb_1": imb(1), "imb_5": imb(5), "imb_20": imb(20),
            "depth_bid": sum(v * p for p, v in b[:20]),
            "depth_ask": sum(v * p for p, v in a[:20]),
            "micro_dev": (micro - mid) / mid * 10000.0,
        })

    def gop_phut(self, moc_ms: int) -> dict:
        mau, self.mau = self.mau, []
        if not mau:
            return {}
        n = len(mau)

        def tb(k):
            return sum(m[k] for m in mau) / n

        tb5 = tb("imb_5")
        std5 = (sum((m["imb_5"] - tb5) ** 2 for m in mau) / n) ** 0.5
        return {
            "timestamp": moc_ms,
            "datetime": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(moc_ms / 1000)),
            "symbol": self.symbol, "n_mau": n,
            "mid": round(tb("mid"), 8),
            "spread_bps": round(tb("spread_bps"), 4),
            "imb_1": round(tb("imb_1"), 5), "imb_5": round(tb5, 5),
            "imb_20": round(tb("imb_20"), 5), "imb_5_std": round(std5, 5),
            "depth_bid": round(tb("depth_bid"), 2),
            "depth_ask": round(tb("depth_ask"), 2),
            "micro_dev": round(tb("micro_dev"), 4),
        }


def duong_dan_ngay() -> str:
    os.makedirs(THU_MUC, exist_ok=True)
    return os.path.join(THU_MUC, "ob_%s.csv" % time.strftime("%Y%m%d", time.gmtime()))


def ghi(rows: List[dict]) -> None:
    if not rows:
        return
    p = duong_dan_ngay()
    moi = not os.path.exists(p)
    with open(p, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COT)
        if moi:
            w.writeheader()
        w.writerows(rows)


def _thoat(signum, frame):
    logger.warning("Nhan tin hieu dung (%s) - dang ghi not roi thoat", signum)
    _dung.set()


def main() -> int:
    ap = argparse.ArgumentParser(description="Thu thap dac trung so lenh")
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,DOGEUSDT")
    ap.add_argument("--depth", type=int, default=50, choices=[1, 50, 200])
    ap.add_argument("--category", default="linear", choices=["linear", "spot"])
    ap.add_argument("--sample-sec", type=float, default=5.0)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s | %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(os.path.join(
                                      THU_MUC if os.path.isdir(THU_MUC) else ".",
                                      "collector.log"), encoding="utf-8")]
                        if os.path.isdir(THU_MUC) else None)
    os.makedirs(THU_MUC, exist_ok=True)

    syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    sach = {s: SoLenh(s) for s in syms}

    from pybit.unified_trading import WebSocket
    ws = WebSocket(testnet=config.DATA_TESTNET, channel_type=args.category)

    def tao_callback(sym: str):
        def cb(msg):
            try:
                d = msg.get("data")
                if d:
                    sach[sym].cap_nhat(d, msg.get("type", "delta"))
            except Exception as e:
                logger.error("%s loi xu ly message: %s", sym, e)
        return cb

    for s in syms:
        ws.orderbook_stream(depth=args.depth, symbol=s, callback=tao_callback(s))
        time.sleep(0.2)

    logger.info("Dang thu %d ma (%s, depth %d), lay mau moi %.0fs, gop theo phut",
                len(syms), args.category, args.depth, args.sample_sec)
    logger.info("Ghi vao %s", THU_MUC)
    logger.info("Dung bang Ctrl+C. An toan de chay lai - file ghi noi theo ngay.")

    signal.signal(signal.SIGINT, _thoat)
    signal.signal(signal.SIGTERM, _thoat)

    phut_hien_tai = int(time.time() // 60)
    dem = defaultdict(int)
    lan_bao_cao = time.time()

    while not _dung.is_set():
        for s in syms:
            sach[s].lay_mau()

        phut = int(time.time() // 60)
        if phut != phut_hien_tai:
            rows = [r for s in syms if (r := sach[s].gop_phut(phut_hien_tai * 60000))]
            ghi(rows)
            for r in rows:
                dem[r["symbol"]] += 1
            phut_hien_tai = phut

        if time.time() - lan_bao_cao > 900:
            logger.info("Da ghi: %s", ", ".join("%s=%d" % (k, v) for k, v in sorted(dem.items())))
            lan_bao_cao = time.time()

        _dung.wait(args.sample_sec)

    ghi([r for s in syms if (r := sach[s].gop_phut(phut_hien_tai * 60000))])
    logger.info("Da dung. Tong so dong da ghi: %d", sum(dem.values()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
