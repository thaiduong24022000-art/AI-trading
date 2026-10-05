"""
DSL luat -> chien luoc. Nen mong cua Strategy Lab (Nang cap 5).

VI SAO KHONG CHO LLM SINH CODE PYTHON:
Kien truc v2 mo ta LLM "de xuat gia thuyet moi duoi dang code". Chay thang code
do la chay ma nguon tuy y tren may co .env chua API key san. Mot gia thuyet
sai thi mat mot buoi backtest; mot dong code doc thi mat tai khoan.

Vi vay LLM o day sinh DU LIEU chu khong sinh code: mot ban mo ta luat dang
JSON, duoc kiem tra doi chieu voi danh sach trang cot va toan tu, roi moi
duoc bien dich thanh doi tuong Strategy. Khong co exec(), khong co eval().
LLM van tu do sang tao trong khong gian luat, nhung khong cham duoc vao may.

VI SAO CHAN SO DIEU KIEN:
Moi dieu kien them vao la mot bac tu do. Mot luat 12 dieu kien luon "khop dep"
voi qua khu va khong bao gio khop voi tuong lai - do la dinh nghia cua overfit.
Tran GIOI_HAN_DIEU_KIEN ton tai de LLM khong the tu di vao cai bay do.

AN TOAN TRUOC LOOKAHEAD:
Luat chi doc dong i (va dong i-1 cho toan tu cat nhau). Moi cot deu do
indicators.add_indicators() sinh ra bang toan tu nhan qua, nen mot luat theo
dong khong the nhin thay tuong lai - tinh chat nay la mien phi, nhung chi con
dung chung nao danh sach trang chi chua cac cot nhan qua.
"""
import re
from typing import Dict, List, Sequence, Tuple, Type

import pandas as pd

from .base import BUY, HOLD, SELL, Signal, Strategy

# Chi cac cot do indicators.add_indicators() sinh ra, cong cot phai sinh tu
# features.py. Them cot moi vao day PHAI kiem lai rang no duoc tinh bang toan
# tu nhan qua - mot cot nhin ve tuong lai lot vao day se lam moi ket qua cua
# ca Strategy Lab tro nen vo nghia ma khong co dau hieu gi.
COT_HOP_LE = (
    "open", "high", "low", "close", "volume",
    "ema_fast", "ema_slow", "ema_trend",
    "rsi", "adx", "atr", "atr_pct",
    "bb_high", "bb_mid", "bb_low",
    "dc_high", "dc_low",
    "macd", "macd_signal", "macd_hist",
    "vol_ma", "vol_ratio",
    "funding", "open_interest",
    # Dan xuat tu funding/OI - xem research/strategy_lab.nap_gia. Muc tuyet doi
    # cua OI khong so sanh duoc giua cac ma, nen mot luat ve OI gan nhu luon
    # phai dung oi_chg_24 chu khong phai open_interest.
    "oi_chg_24", "funding_z",
)

TOAN_TU_SO_SANH = ("<", "<=", ">", ">=")
TOAN_TU_CAT = ("cat_len", "cat_xuong")
TOAN_TU_HOP_LE = TOAN_TU_SO_SANH + TOAN_TU_CAT

GIOI_HAN_DIEU_KIEN = 4        # tran bac tu do moi chieu
_TEN_HOP_LE = re.compile(r"^[a-z][a-z0-9_]{2,39}$")


class SpecKhongHopLe(ValueError):
    """Ban mo ta luat khong qua duoc kiem tra. Luon kem ly do cu the."""


def _kiem_dieu_kien(dk, cho: str) -> Tuple[str, str, object]:
    if not isinstance(dk, (list, tuple)) or len(dk) != 3:
        raise SpecKhongHopLe(
            "%s: moi dieu kien phai la [cot, toan_tu, gia_tri], nhan duoc: %r" % (cho, dk))
    trai, toan_tu, phai = dk

    if trai not in COT_HOP_LE:
        raise SpecKhongHopLe("%s: cot '%s' khong nam trong danh sach trang (%s)"
                             % (cho, trai, ", ".join(COT_HOP_LE)))
    if toan_tu not in TOAN_TU_HOP_LE:
        raise SpecKhongHopLe("%s: toan tu '%s' khong hop le (chi nhan: %s)"
                             % (cho, toan_tu, ", ".join(TOAN_TU_HOP_LE)))

    if isinstance(phai, str):
        if phai not in COT_HOP_LE:
            raise SpecKhongHopLe("%s: ve phai '%s' khong phai cot hop le" % (cho, phai))
    elif isinstance(phai, bool) or not isinstance(phai, (int, float)):
        # bool la subclass cua int trong Python - chan rieng, neu khong
        # [rsi, "<", True] se lot qua va so sanh voi 1.
        raise SpecKhongHopLe("%s: ve phai phai la so hoac ten cot, nhan duoc: %r"
                             % (cho, phai))
    if toan_tu in TOAN_TU_CAT and not isinstance(phai, str):
        # Cat nhau voi mot hang so cung hop ly ve mat toan hoc, nhung gan nhu
        # luon la dau hieu LLM dang dinh viet mot phep so sanh thuong.
        pass
    return trai, toan_tu, phai


def kiem_tra_spec(spec: Dict) -> Dict:
    """Kiem tra va chuan hoa mot ban mo ta luat. Nem SpecKhongHopLe neu sai.

    Tra ve ban da chuan hoa (co du khoa, dieu kien la tuple) de phan con lai
    khong phai phong thu lai lan nua.
    """
    if not isinstance(spec, dict):
        raise SpecKhongHopLe("spec phai la mot dict")

    ten = spec.get("ten")
    if not isinstance(ten, str) or not _TEN_HOP_LE.match(ten):
        raise SpecKhongHopLe(
            "ten '%s' khong hop le: chi chu thuong/so/gach duoi, bat dau bang "
            "chu, dai 3-40 ky tu" % ten)

    dk_long = spec.get("long") or []
    dk_short = spec.get("short") or []
    if not dk_long and not dk_short:
        raise SpecKhongHopLe("spec phai co it nhat mot dieu kien long hoac short")
    for ds, cho in ((dk_long, "long"), (dk_short, "short")):
        if len(ds) > GIOI_HAN_DIEU_KIEN:
            raise SpecKhongHopLe(
                "%s: %d dieu kien, toi da %d - moi dieu kien la mot bac tu do, "
                "va luat cang nhieu bac tu do cang chac chan overfit"
                % (cho, len(ds), GIOI_HAN_DIEU_KIEN))

    return {
        "ten": ten,
        "mo_ta": str(spec.get("mo_ta", ""))[:300],
        "long": [_kiem_dieu_kien(d, "long") for d in dk_long],
        "short": [_kiem_dieu_kien(d, "short") for d in dk_short],
        "gia_thuyet": str(spec.get("gia_thuyet", ""))[:500],
    }


def _gia_tri(df: pd.DataFrame, i: int, x):
    return float(df[x].iloc[i]) if isinstance(x, str) else float(x)


def _dung(df: pd.DataFrame, i: int, dk) -> bool:
    trai, toan_tu, phai = dk
    a = _gia_tri(df, i, trai)
    b = _gia_tri(df, i, phai)
    if a != a or b != b:          # NaN - vung warmup, coi nhu chua co tin hieu
        return False

    if toan_tu == "<":
        return a < b
    if toan_tu == "<=":
        return a <= b
    if toan_tu == ">":
        return a > b
    if toan_tu == ">=":
        return a >= b

    # Toan tu cat nhau can dong truoc do - van la nhan qua.
    if i < 1:
        return False
    a_truoc = _gia_tri(df, i - 1, trai)
    b_truoc = _gia_tri(df, i - 1, phai)
    if a_truoc != a_truoc or b_truoc != b_truoc:
        return False
    if toan_tu == "cat_len":
        return a_truoc <= b_truoc and a > b
    return a_truoc >= b_truoc and a < b


def bien_dich(spec: Dict) -> Type[Strategy]:
    """Bien dich ban mo ta luat thanh mot lop Strategy.

    Tra ve LOP (khong phai the hien) vi walk_forward() nhan strategy_cls.
    """
    s = kiem_tra_spec(spec)

    def generate_at(self, df: pd.DataFrame, i: int) -> Signal:
        sig = self._base_signal()
        if i < 1:
            return sig
        if s["long"] and all(_dung(df, i, d) for d in s["long"]):
            sig.action = BUY
        elif s["short"] and all(_dung(df, i, d) for d in s["short"]):
            sig.action = SELL
        else:
            return sig
        # Do manh co dinh: luat khong co thang do tu tin rieng, va bia ra mot
        # thang do se lam allocator tuong no biet nhieu hon thuc te.
        sig.strength = 0.6
        sig.reason = s["mo_ta"] or s["ten"]
        return sig

    return type(
        "RuleStrategy_%s" % s["ten"],
        (Strategy,),
        {
            "name": s["ten"],
            "default_params": {},
            "generate_at": generate_at,
            "spec": s,
            "__doc__": "Chien luoc sinh tu luat: %s" % (s["mo_ta"] or s["ten"]),
        },
    )


def bien_dich_nhieu(specs: Sequence[Dict]) -> List[Type[Strategy]]:
    """Bien dich mot loat spec. Spec hong bi bo qua kem ly do, khong lam
    hong ca lo - mot y tuong sai cua LLM khong duoc chan 19 y tuong con lai.
    """
    ra, loi = [], []
    for sp in specs:
        try:
            ra.append(bien_dich(sp))
        except SpecKhongHopLe as e:
            loi.append("%s: %s" % (sp.get("ten", "?") if isinstance(sp, dict) else "?", e))
    if loi:
        import logging
        logging.getLogger(__name__).warning(
            "Bo qua %d spec khong hop le:\n  %s", len(loi), "\n  ".join(loi))
    return ra
