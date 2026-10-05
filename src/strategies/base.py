"""
Giao dien chung cho moi chien luoc.

THIET KE HIEU NANG (quan trong):
  Chien luoc tinh chi bao TRUOC mot lan qua prepare(), roi generate_at(df, i)
  chi doc dong thu i. Neu de moi cay nen tinh lai chi bao tu dau thi backtest
  la O(n^2) va walk-forward tro nen khong the chay duoc.

  Cach nay VAN AN TOAN truoc lookahead vi moi toan tu dung deu la NHAN QUA:
  ewm/rolling/shift(1) tai dong i chi phu thuoc cac dong <= i. Gia tri doc duoc
  tai dong i hoan toan giong nhu khi tinh rieng tren df[:i+1].
  KHONG duoc dung cac toan tu nhin ve tuong lai trong prepare():
  shift(-1), rolling(...).shift(-k), fillna(method='bfill'), v.v.

  Chien luoc chi TRA LOI "co tin hieu gi khong", KHONG quyet dinh khoi luong
  va khong biet gi ve so du - sizing la viec cua RiskManager.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Tuple

import pandas as pd

BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


@dataclass
class Signal:
    action: str = HOLD
    strength: float = 0.0       # 0..1, do tu tin cua chinh chien luoc
    reason: str = ""
    strategy: str = ""
    metrics: Dict[str, float] = field(default_factory=dict)

    @property
    def is_actionable(self) -> bool:
        return self.action in (BUY, SELL)


class Strategy(ABC):
    name: str = "base"
    preferred_regimes: Tuple[str, ...] = ()
    default_params: Dict[str, float] = {}

    def __init__(self, **params):
        self.params = dict(self.default_params)
        self.params.update(params)

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        """Tinh truoc cac cot rieng cua chien luoc (chi dung toan tu nhan qua)."""
        return df

    @abstractmethod
    def generate_at(self, df: pd.DataFrame, i: int) -> Signal:
        """Tin hieu tai dong i cua df DA duoc prepare()."""

    def generate(self, df: pd.DataFrame) -> Signal:
        """Duong dung cho live: prepare roi lay tin hieu o nen cuoi cung."""
        prepared = self.prepare(df)
        return self.generate_at(prepared, len(prepared) - 1)

    def _base_signal(self) -> Signal:
        return Signal(action=HOLD, strength=0.0, strategy=self.name)

    def _col(self, suffix: str) -> str:
        """Ten cot rieng cho chien luoc nay - tranh dam nhau khi nhieu chien
        luoc cung prepare tren mot DataFrame."""
        return "_%s_%s" % (self.name, suffix)

    def __repr__(self) -> str:
        return "%s(%s)" % (self.__class__.__name__, self.params)
