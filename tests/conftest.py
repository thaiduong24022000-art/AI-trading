"""
Fixture dung chung cho test.

Nguyen tac: test KHONG duoc phu thuoc vao gia tri trong .env cua may dang chay.
Moi test can tham so rieng thi dung make_cfg() de tao ban sao co the sua,
thay vi doi config that.
"""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as real_config  # noqa: E402
from src import datafeed, indicators  # noqa: E402


def make_cfg(**overrides):
    """Ban sao cua config co the sua tu do, khong dung den config that."""
    cfg = types.SimpleNamespace(
        **{k: getattr(real_config, k) for k in dir(real_config) if k.isupper()})
    cfg.__dict__.update(overrides)
    return cfg


@pytest.fixture
def cfg():
    return make_cfg()


@pytest.fixture(scope="session")
def raw_df():
    """Du lieu tong hop co doi regime - du dai de vuot warmup 220 nen."""
    return datafeed.synthetic_ohlcv(n=700, seed=7)


@pytest.fixture(scope="session")
def df_ind(raw_df):
    return indicators.add_indicators(raw_df)
