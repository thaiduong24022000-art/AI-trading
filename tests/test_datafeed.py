"""
Kiem tra nguon du lieu.

Trong tam la mot bat bien ve AN TOAN DU LIEU: lich su chi duoc phep day len,
khong duoc phep mat di. Mat du lieu o day hoan toan im lang - khong loi, khong
canh bao - va chi lo ra khi mot backtest bong nhien chay tren ky ngan hon ma
khong ai de y, roi ket luan rut ra tu do la sai.
"""
import numpy as np
import pandas as pd
import pytest

from src import datafeed


class FakeSession:
    """Gia lap san: chi tra ve N nen GAN DAY NHAT."""

    def __init__(self, so_nen: int, moc_dau_ms: int):
        self.so_nen = so_nen
        self.moc_dau_ms = moc_dau_ms

    def get_kline(self, **params):
        limit = int(params.get("limit", 1000))
        end = params.get("end")
        moc_cuoi = self.moc_dau_ms + (self.so_nen - 1) * 3_600_000
        if end is not None:
            moc_cuoi = min(moc_cuoi, int(end))
        rows = []
        for i in range(limit):
            ts = moc_cuoi - i * 3_600_000
            if ts < self.moc_dau_ms:
                break
            rows.append([str(ts), "100", "101", "99", "100", "10", "1000"])
        return {"result": {"list": rows}}


class FakeClient:
    def __init__(self, session):
        self.session = session


@pytest.fixture
def cache_tam(tmp_path, monkeypatch):
    monkeypatch.setattr(datafeed.config, "CACHE_DIR", str(tmp_path))
    return tmp_path


def test_tai_them_khong_duoc_xoa_lich_su_da_co(cache_tam):
    """Test hoi quy cho mot loi lam mat 4 nam du lieu.

    Nut 'Tai ve cache' trong web UI mac dinh 8000 nen. Truoc day download_history
    GHI DE cache, nen bam nut mac dinh mot lan la xoa sach lich su dai hon da tai
    tu truoc - im lang, khong canh bao.
    """
    moc = 1_600_000_000_000
    client = FakeClient(FakeSession(so_nen=5000, moc_dau_ms=moc))

    dai = datafeed.download_history(client, "BTCUSDT", "60", total_bars=5000, use_cache=False)
    assert len(dai) == 5000

    # Lan tai thu hai chi lay 100 nen gan day - KHONG duoc lam mat 4900 nen kia
    sau = datafeed.download_history(client, "BTCUSDT", "60", total_bars=100, use_cache=False)

    assert len(sau) == 5000, (
        "tai 100 nen ma cache tut xuong %d - da xoa mat lich su" % len(sau))
    assert sau["timestamp"].min() == dai["timestamp"].min()


def test_nen_moi_duoc_them_vao_cache(cache_tam):
    moc = 1_600_000_000_000
    cu = FakeClient(FakeSession(so_nen=1000, moc_dau_ms=moc))
    datafeed.download_history(cu, "BTCUSDT", "60", total_bars=1000, use_cache=False)

    # San co them 200 nen moi o phia sau
    moi = FakeClient(FakeSession(so_nen=1200, moc_dau_ms=moc))
    sau = datafeed.download_history(moi, "BTCUSDT", "60", total_bars=300, use_cache=False)

    assert len(sau) == 1200
    assert sau["timestamp"].is_monotonic_increasing
    assert not sau["timestamp"].duplicated().any()


def test_cache_giu_dung_thu_tu_va_khong_trung_lap(cache_tam):
    client = FakeClient(FakeSession(so_nen=800, moc_dau_ms=1_600_000_000_000))
    df = datafeed.download_history(client, "BTCUSDT", "60", total_bars=800, use_cache=False)

    assert df["timestamp"].is_monotonic_increasing
    assert not df["timestamp"].duplicated().any()
    assert list(df.columns[:6]) == ["timestamp", "open", "high", "low", "close", "volume"]


def test_dung_cache_khi_da_du_nen(cache_tam):
    """Khong goi API neu cache da du - backtest quet tham so chay hang tram lan."""
    client = FakeClient(FakeSession(so_nen=1000, moc_dau_ms=1_600_000_000_000))
    datafeed.download_history(client, "BTCUSDT", "60", total_bars=1000, use_cache=False)

    class SessionNo:
        def get_kline(self, **params):
            raise AssertionError("khong duoc goi API khi cache da du")

    datafeed.download_history(FakeClient(SessionNo()), "BTCUSDT", "60",
                              total_bars=1000, use_cache=True)


def test_du_lieu_tong_hop_co_timestamp_mili_giay_hop_le():
    """pandas 3 doi do phan giai cua date_range sang GIAY.

    Neu timestamp bi sinh sai don vi, moc ngay trong backtest se sai theo, va
    logic reset circuit breaker theo ngay im lang ngung hoat dong.
    """
    df = datafeed.synthetic_ohlcv(n=100, seed=1)
    ts = df["timestamp"].to_numpy()

    assert ts.dtype.kind in "iu"
    assert ts[0] > 1_000_000_000_000, "timestamp phai la mili-giay tu epoch"
    assert np.all(np.diff(ts) == 3_600_000), "khung 1h phai cach nhau dung 1 gio"
    assert pd.to_datetime(ts[0], unit="ms").year == 2024
