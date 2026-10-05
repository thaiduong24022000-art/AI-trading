"""
Tai funding rate va open interest - du lieu ma OHLCV KHONG nhin thay.

VI SAO CAN: 12 dac trung tu OHLCV cho IC ~ 0. Gia va khoi luong la thong tin
moi bot retail deu co va da bi arbitrage het. Funding va OI do mot thu khac han:
VI THE - ai dang dat cuoc bao nhieu, huong nao, don bay ra sao.

  funding rate  : phe nao dang TRA TIEN cho phe nao de giu vi the.
                  Funding duong sau = phe long dong duc va dang tra phi -
                  mot trang thai ton kem, kho keo dai.
  open interest : bao nhieu tien don bay dang tren ban. OI tang khi gia giam
                  nghia la phe short dang xay vi the, khong phai phe long thoat.

CHONG LOOKAHEAD:
Funding cong bo moi 8 gio, OI moi 4 gio, con nen cua ta bat dau tai timestamp[i]
va dong tai timestamp[i]+4h. Ta ghep bang merge_asof lui (backward) tren
timestamp BAT DAU nen - tuc chi dung gia tri da cong bo TRUOC khi nen mo. Day
la lua chon BAO THU: no bo phi mot chut thong tin hop le, nhung khong the ro ri.

    python -m research.download_derivatives --symbols BTCUSDT,ETHUSDT --interval 240
"""
import argparse
import os
import sys
import time
from typing import Dict, List, Optional

import pandas as pd

import config

# Mot so ma spot khong co perp cung ten - dung bien the nhan gia (cung tai san
# co so, chi khac don vi bao gia, nen funding/OI van dung).
ANH_XA_PERP: Dict[str, str] = {
    "PEPEUSDT": "1000PEPEUSDT",
    "BONKUSDT": "1000BONKUSDT",
    "SHIBUSDT": "1000SHIBUSDT",
    "FLOKIUSDT": "1000FLOKIUSDT",
}
KHONG_CO_PERP = {"ZIGUSDT"}


def duong_dan(symbol: str, interval: str) -> str:
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    return os.path.join(config.CACHE_DIR, "%s_deriv_%s.csv" % (symbol, interval))


def tai_oi(session, perp: str, interval: str, max_trang: int = 70) -> pd.DataFrame:
    ban_ghi, cursor = [], ""
    for _ in range(max_trang):
        kw = dict(category="linear", symbol=perp,
                  intervalTime={"240": "4h", "60": "1h", "D": "1d"}.get(interval, "4h"),
                  limit=200)
        if cursor:
            kw["cursor"] = cursor
        res = session.get_open_interest(**kw).get("result", {})
        rows = res.get("list", [])
        if not rows:
            break
        ban_ghi.extend(rows)
        cursor = res.get("nextPageCursor", "")
        if not cursor:
            break
        time.sleep(0.08)
    if not ban_ghi:
        return pd.DataFrame(columns=["timestamp", "open_interest"])
    df = pd.DataFrame({
        "timestamp": [int(x["timestamp"]) for x in ban_ghi],
        "open_interest": [float(x["openInterest"]) for x in ban_ghi],
    })
    return df.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)


def tai_funding(session, perp: str, max_trang: int = 40) -> pd.DataFrame:
    ban_ghi, end = [], None
    for _ in range(max_trang):
        kw = dict(category="linear", symbol=perp, limit=200)
        if end is not None:
            kw["endTime"] = int(end)
        rows = session.get_funding_rate_history(**kw).get("result", {}).get("list", [])
        if not rows:
            break
        ban_ghi.extend(rows)
        end = min(int(x["fundingRateTimestamp"]) for x in rows) - 1
        time.sleep(0.08)
    if not ban_ghi:
        return pd.DataFrame(columns=["timestamp", "funding"])
    df = pd.DataFrame({
        "timestamp": [int(x["fundingRateTimestamp"]) for x in ban_ghi],
        "funding": [float(x["fundingRate"]) for x in ban_ghi],
    })
    return df.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)


def ghep_vao_nen(gia: pd.DataFrame, oi: pd.DataFrame, funding: pd.DataFrame) -> pd.DataFrame:
    """Ghep lui: moi nen chi nhan gia tri da cong bo TRUOC khi no mo."""
    out = gia[["timestamp"]].copy().sort_values("timestamp")
    for phu in (oi, funding):
        if len(phu):
            out = pd.merge_asof(out, phu.sort_values("timestamp"),
                                on="timestamp", direction="backward")
    for c in ("open_interest", "funding"):
        if c not in out.columns:
            out[c] = float("nan")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--interval", default="240")
    args = ap.parse_args()

    if config.EXCHANGE != "bybit":
        # Chua port sang OKX co chu dich: OKX co funding-rate-history nhung do
        # sau lich su open-interest cong khai qua API chua duoc kiem chung la
        # tuong duong Bybit. Data nay nuoi thang vao ic_study.py - tha bao loi
        # ro con hon am tham ghi so lieu mong hoac sai vao ket qua nghien cuu.
        print("EXCHANGE=%s: script nay moi ho tro Bybit. Doi EXCHANGE=bybit "
              "trong .env de tai derivatives, hoac tu kiem chung do sau OI "
              "cong khai cua OKX truoc khi mo rong script nay." % config.EXCHANGE)
        return 1

    from src import datafeed
    from src.bybit_client import BybitClient
    session = BybitClient(cfg=config, testnet=config.DATA_TESTNET).session

    syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    ok, bo = 0, []
    for i, sym in enumerate(syms, 1):
        if sym in KHONG_CO_PERP:
            print("%3d. %-12s bo qua (khong co perp)" % (i, sym))
            bo.append(sym)
            continue
        perp = ANH_XA_PERP.get(sym, sym)
        gia = datafeed.load_cache(sym, args.interval)
        if gia is None:
            print("%3d. %-12s bo qua (chua co cache gia)" % (i, sym))
            bo.append(sym)
            continue
        try:
            oi = tai_oi(session, perp, args.interval)
            fd = tai_funding(session, perp)
        except Exception as e:
            print("%3d. %-12s LOI: %s" % (i, sym, str(e)[:60]))
            bo.append(sym)
            continue

        ghep = ghep_vao_nen(gia, oi, fd)
        phu_song = float(ghep["open_interest"].notna().mean())
        ghep.to_csv(duong_dan(sym, args.interval), index=False)
        ok += 1
        print("%3d. %-12s perp=%-14s OI %5d ban ghi, funding %4d | phu song %.0f%% so nen"
              % (i, sym, perp, len(oi), len(fd), phu_song * 100))

    print("\n%d ma co du lieu phai sinh, %d bo qua." % (ok, len(bo)))
    if bo:
        print("Bo qua: %s" % ",".join(bo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
