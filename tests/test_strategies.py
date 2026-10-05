"""
Kiem tra hop dong ma moi chien luoc phai giu.

Bat bien manh nhat o day: tin hieu tai nen i phai GIONG HET nhau du DataFrame
co chua cac nen sau i hay khong. Day la dang manh hon cua test chi bao - no
kiem ca prepare() lan generate_at() cung mot luc, va no la dieu duy nhat bao
dam ket qua backtest chuyen giao duoc sang chay that.
"""
import pytest

from src import indicators
from src.strategies import ALL_STRATEGIES
from src.strategies.base import BUY, HOLD, SELL


@pytest.mark.parametrize("cls", ALL_STRATEGIES, ids=lambda c: c.name)
@pytest.mark.parametrize("i", [300, 500, 699])
def test_tin_hieu_khong_doi_khi_biet_tuong_lai(raw_df, cls, i):
    full = cls().prepare(indicators.add_indicators(raw_df))
    sig_full = cls().generate_at(full, i)

    partial = cls().prepare(indicators.add_indicators(raw_df.iloc[:i + 1]))
    sig_part = cls().generate_at(partial, i)

    assert sig_full.action == sig_part.action, (
        "%s doi quyet dinh tai nen %d khi co du lieu tuong lai" % (cls.name, i))
    assert sig_full.strength == pytest.approx(sig_part.strength, rel=1e-9)


@pytest.mark.parametrize("cls", ALL_STRATEGIES, ids=lambda c: c.name)
def test_khong_ra_tin_hieu_truoc_khi_du_warmup(raw_df, cls):
    df = cls().prepare(indicators.add_indicators(raw_df))
    strat = cls()
    for i in (0, 50, indicators.warmup_bars() - 1):
        assert strat.generate_at(df, i).action == HOLD, (
            "%s ra tin hieu khi chi bao chua on dinh (nen %d)" % (cls.name, i))


@pytest.mark.parametrize("cls", ALL_STRATEGIES, ids=lambda c: c.name)
def test_tin_hieu_luon_hop_le(raw_df, cls):
    df = cls().prepare(indicators.add_indicators(raw_df))
    strat = cls()
    for i in range(indicators.warmup_bars(), len(df)):
        sig = strat.generate_at(df, i)
        assert sig.action in (BUY, SELL, HOLD)
        assert 0.0 <= sig.strength <= 1.0, "strength ngoai khoang 0..1: %s" % sig.strength
        assert sig.strategy == cls.name
        assert sig.reason, "moi tin hieu phai co ly do - day la nguyen lieu cho nhat ky AI"
        if sig.action == HOLD:
            assert not sig.is_actionable


@pytest.mark.parametrize("cls", ALL_STRATEGIES, ids=lambda c: c.name)
def test_prepare_khong_lam_hong_du_lieu_goc(raw_df, cls):
    df = indicators.add_indicators(raw_df)
    before = df["close"].copy()
    cls().prepare(df)
    pd_testing_equal = (df["close"] == before) | (df["close"].isna() & before.isna())
    assert pd_testing_equal.all(), "prepare() da sua du lieu goc"


@pytest.mark.parametrize("cls", ALL_STRATEGIES, ids=lambda c: c.name)
def test_nhieu_chien_luoc_prepare_chung_mot_frame(raw_df, cls):
    """Cac chien luoc dung chung mot DataFrame thi cot cua chung khong duoc dam nhau."""
    df = indicators.add_indicators(raw_df)
    for other in ALL_STRATEGIES:
        df = other().prepare(df)

    rieng = cls().prepare(indicators.add_indicators(raw_df))
    i = 500
    sig_chung = cls().generate_at(df, i)
    sig_rieng = cls().generate_at(rieng, i)
    assert sig_chung.action == sig_rieng.action
    assert sig_chung.strength == pytest.approx(sig_rieng.strength, rel=1e-9)


def test_moi_chien_luoc_khai_bao_regime_uu_tien():
    """Allocator dua vao preferred_regimes de doi trong so - thieu la hong thiet ke."""
    for cls in ALL_STRATEGIES:
        assert cls.preferred_regimes, "%s chua khai bao preferred_regimes" % cls.name
        assert cls.name, "chien luoc phai co ten de allocator va DB tham chieu"
