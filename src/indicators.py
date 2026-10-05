"""
Chi bao ky thuat, viet bang pandas/numpy thuan (khong can ta-lib).

QUY TAC CHONG LOOKAHEAD:
  Moi chi bao chi dung du lieu cua nen hien tai va cac nen TRUOC do.
  Cac ham nhu donchian() tra ve kenh tinh tren nen truoc (da shift(1))
  de tin hieu breakout khong "nhin thay" chinh cay nen dang xet.
"""
import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


def _check(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError("DataFrame thieu cot: %s" % missing)


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """RSI theo phuong phap Wilder (dung EMA voi alpha=1/period)."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    # avg_loss == 0 nghia la khong co nen giam nao -> RSI = 100
    out = out.where(avg_loss != 0.0, 100.0)
    return out.where(avg_gain.notna(), np.nan)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return macd_line, signal_line, macd_line - signal_line


def true_range(df: pd.DataFrame) -> pd.Series:
    _check(df)
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range theo Wilder."""
    return true_range(df).ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ADX theo Wilder. Gia tri cao = thi truong co xu huong ro."""
    _check(df)
    up_move = df["high"].diff()
    down_move = -df["low"].diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)

    atr_ = true_range(df).ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean() / atr_
    minus_di = 100.0 * minus_dm.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean() / atr_

    denom = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / denom
    return dx.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def bollinger(series: pd.Series, period: int = 20, num_std: float = 2.0):
    mid = sma(series, period)
    std = series.rolling(period, min_periods=period).std(ddof=0)
    return mid - num_std * std, mid, mid + num_std * std


def donchian(df: pd.DataFrame, period: int = 20):
    """Kenh Donchian tinh tren cac nen TRUOC nen hien tai (shift(1)).

    Nho vay dieu kien 'close > donchian_high' la breakout that su,
    khong phai tu so sanh voi chinh dinh cua no.
    """
    _check(df)
    upper = df["high"].rolling(period, min_periods=period).max().shift(1)
    lower = df["low"].rolling(period, min_periods=period).min().shift(1)
    return lower, upper


def add_indicators(df: pd.DataFrame, cfg=None) -> pd.DataFrame:
    """Them toan bo chi bao can thiet vao DataFrame va tra ve ban sao."""
    _check(df)
    out = df.copy()
    close = out["close"]

    out["ema_fast"] = ema(close, 20)
    out["ema_slow"] = ema(close, 50)
    out["ema_trend"] = ema(close, 200)
    out["rsi"] = rsi(close, 14)

    macd_line, signal_line, hist = macd(close)
    out["macd"] = macd_line
    out["macd_signal"] = signal_line
    out["macd_hist"] = hist

    out["atr"] = atr(out, 14)
    out["atr_pct"] = out["atr"] / close
    out["adx"] = adx(out, 14)

    bb_low, bb_mid, bb_high = bollinger(close, 20, 2.0)
    out["bb_low"] = bb_low
    out["bb_mid"] = bb_mid
    out["bb_high"] = bb_high

    dc_low, dc_high = donchian(out, 20)
    out["dc_low"] = dc_low
    out["dc_high"] = dc_high

    out["vol_ma"] = sma(out["volume"], 20)
    out["vol_ratio"] = out["volume"] / out["vol_ma"].replace(0.0, np.nan)

    return out


def warmup_bars() -> int:
    """So nen toi thieu can co truoc khi tin hieu duoc coi la hop le."""
    return 220  # ema_trend(200) la chi bao cham nhat
