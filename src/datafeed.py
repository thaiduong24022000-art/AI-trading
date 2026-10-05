"""
Nguon du lieu: tai tu Bybit, cache ra CSV, va sinh du lieu tong hop de test offline.

Cache CSV quan trong hon ve ngoai: backtest can chay lai hang tram lan khi
quet tham so. Goi API moi lan vua cham vua de bi rate-limit.
"""
import logging
import os
from typing import Optional

import numpy as np
import pandas as pd

import config

logger = logging.getLogger(__name__)


def cache_path(symbol: str, interval: str) -> str:
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    return os.path.join(config.CACHE_DIR, "%s_%s.csv" % (symbol, interval))


def save_cache(df: pd.DataFrame, symbol: str, interval: str) -> str:
    path = cache_path(symbol, interval)
    df.to_csv(path, index=False)
    logger.info("Da luu %d nen vao %s", len(df), path)
    return path


def load_cache(symbol: str, interval: str) -> Optional[pd.DataFrame]:
    path = cache_path(symbol, interval)
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"])
    return df


def download_history(client, symbol: str, interval: str = None, total_bars: int = 2000,
                     use_cache: bool = True) -> pd.DataFrame:
    """Tai lich su nhieu trang (Bybit gioi han 1000 nen moi lan goi)."""
    interval = interval or config.KLINE_INTERVAL
    if use_cache:
        cached = load_cache(symbol, interval)
        if cached is not None and len(cached) >= total_bars * 0.9:
            logger.info("Dung cache %d nen cho %s", len(cached), symbol)
            return cached

    frames = []
    fetched = 0
    end_ts = None
    while fetched < total_bars:
        limit = min(1000, total_bars - fetched)
        params = dict(category=config.CATEGORY, symbol=symbol,
                      interval=interval, limit=limit)
        if end_ts:
            params["end"] = int(end_ts)
        resp = client.session.get_kline(**params)
        rows = resp.get("result", {}).get("list", [])
        if not rows:
            break
        cols = ["timestamp", "open", "high", "low", "close", "volume", "turnover"]
        df = pd.DataFrame(rows, columns=cols).drop(columns=["turnover"])
        df["timestamp"] = pd.to_numeric(df["timestamp"])
        for c in ("open", "high", "low", "close", "volume"):
            df[c] = df[c].astype(float)
        frames.append(df)
        fetched += len(df)
        end_ts = df["timestamp"].min() - 1
        if len(df) < limit:
            break

    if not frames:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    out = pd.concat(frames).drop_duplicates("timestamp").sort_values("timestamp")
    out = out.reset_index(drop=True)

    # GOP voi cache cu, KHONG ghi de len no.
    # Ly do: mot lan tai 1000 nen gan day khong duoc phep xoa mat 4 nam lich su
    # da tai tu truoc. Lich su chi duoc phep DAY LEN, khong duoc phep mat di -
    # va mat du lieu kieu nay hoan toan im lang, chi lo ra khi backtest bong
    # nhien chay tren mot ky ngan hon ma khong ai de y.
    truoc = load_cache(symbol, interval)
    if truoc is not None and "timestamp" in truoc.columns:
        so_nen_cu = len(truoc)
        out = (pd.concat([truoc, out], ignore_index=True)
                 .drop_duplicates("timestamp", keep="last")
                 .sort_values("timestamp").reset_index(drop=True))
        if len(out) > so_nen_cu:
            logger.info("Gop voi cache cu: %d + moi -> %d nen", so_nen_cu, len(out))

    out["datetime"] = pd.to_datetime(out["timestamp"], unit="ms")
    save_cache(out, symbol, interval)
    return out


def synthetic_ohlcv(n: int = 2000, seed: int = 42, start_price: float = 30000.0,
                    regime_switch: bool = True) -> pd.DataFrame:
    """Sinh du lieu gia tong hop co doi regime, dung cho test offline.

    Du lieu nay KHONG dung de danh gia loi nhuan chien luoc - no chi de kiem tra
    code chay dung. Ket qua backtest tren du lieu ngau nhien khong co y nghia
    du bao, va neu mot chien luoc "co lai" tren nhieu tuy y thi do la dau hieu
    cua overfit chu khong phai cua alpha.
    """
    rng = np.random.default_rng(seed)
    prices = [start_price]
    drift, vol = 0.0002, 0.010
    for i in range(1, n):
        if regime_switch and i % 400 == 0:
            drift = rng.choice([-0.0006, 0.0, 0.0006])
            vol = rng.choice([0.006, 0.012, 0.025])
        prices.append(prices[-1] * float(np.exp(rng.normal(drift, vol))))

    close = np.array(prices)
    noise = np.abs(rng.normal(0, 0.004, n)) * close
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) + noise
    low = np.minimum(open_, close) - noise
    volume = rng.lognormal(mean=5.0, sigma=0.5, size=n)
    ts = pd.date_range("2024-01-01", periods=n, freq="h")

    return pd.DataFrame({
        # astype("int64") tra ve so theo DO PHAN GIAI cua chinh DatetimeIndex:
        # pandas 2 mac dinh nano-giay, pandas 3 mac dinh giay. Ep ve
        # datetime64[ms] truoc de ket qua luon la mili-giay giong du lieu that
        # tu san, o moi phien ban pandas.
        "timestamp": ts.astype("datetime64[ms]").astype("int64"),
        "datetime": ts,
        "open": open_, "high": high, "low": low, "close": close, "volume": volume,
    })
