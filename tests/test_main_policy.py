"""
Kiem tra cach AI policy duoc noi vao vong lap giao dich.

Bo test nay bao ve mot bat bien de vo ma khong ai nhin thay: O CHE DO BONG,
POLICY KHONG DUOC LAM DOI BAT CU DIEU GI.

Cai bay cu the: allocator chuan hoa trong so tren DANH SACH chien luoc. Chi can
them mot chien luoc vao danh sach - du no khong bao gio phat tin hieu - la trong
so cua breakout tut tu 1.00 xuong 0.60. Che do bong luc do khong con la bong nua,
no da am tham thay doi quy mo lenh that. Vi vay chien luoc policy o che do bong
phai KHONG CO MAT trong danh sach, chu khong phai co mat roi tu hua se im lang.
"""
import types

import pytest

from src import policy as policy_mod
from src.allocator import allocate
from src.regime import TREND, RegimeResult
from src.strategies import Breakout
from src.strategies.base import BUY, HOLD, SELL
from tests.conftest import make_cfg

import main as main_mod


def _bot(che_do, co_mo_hinh=True):
    """TradingBot toi thieu, khong dung den Storage hay ket noi san."""
    bot = main_mod.TradingBot.__new__(main_mod.TradingBot)
    bot.strategies = [Breakout()]
    bot.storage = None
    bot.policy_strategy = None

    if che_do != policy_mod.TAT:
        st = types.SimpleNamespace(policy=types.SimpleNamespace(san_sang=co_mo_hinh))
        bot.policy_strategy = st
        if che_do == policy_mod.CHU_DONG:
            st.name = "ml_policy"
            st.preferred_regimes = ()
            bot.strategies = bot.strategies + [st]
    return bot


def _regime():
    return RegimeResult(regime=TREND, confidence=0.8)


# ==========================================================
# Bat bien cua che do bong
# ==========================================================
def test_che_do_bong_khong_lam_doi_trong_so_cua_chien_luoc_luat():
    cfg = make_cfg()
    khong_policy = allocate(_bot(policy_mod.TAT).strategies, _regime(), {}, cfg)
    bong = allocate(_bot(policy_mod.BONG).strategies, _regime(), {}, cfg)
    assert bong.weights == khong_policy.weights
    assert bong.weights["breakout"] == pytest.approx(1.0)


def test_che_do_active_thi_policy_chia_trong_so_voi_chien_luoc_luat():
    """Doi lai o che do active: co mat trong danh sach la co anh huong - va do
    la dieu duoc mong doi, sau khi mo hinh da qua cong thang cap."""
    cfg = make_cfg()
    w = allocate(_bot(policy_mod.CHU_DONG).strategies, _regime(), {}, cfg).weights
    assert "ml_policy" in w
    assert w["breakout"] < 1.0


def test_che_do_filter_cung_khong_nam_trong_ensemble():
    assert len(_bot(policy_mod.LOC).strategies) == 1


# ==========================================================
# Che do filter: chi duoc chan hoac giam
# ==========================================================
class _YKien:
    def __init__(self, action=BUY, co_y_kien=True, ly_do="test"):
        self.action, self.co_y_kien, self.ly_do = action, co_y_kien, ly_do


def _loc(y, action, strength=0.8):
    bot = _bot(policy_mod.LOC)
    return bot._loc_bang_policy(y, action, strength, "breakout:BUY(0.80)")


def test_policy_dong_chieu_thi_giu_nguyen_quy_mo():
    a, s, r = _loc(_YKien(BUY), BUY, 0.8)
    assert (a, s) == (BUY, 0.8)
    assert "dong y" in r


def test_policy_nguoc_chieu_thi_chan_han():
    a, s, r = _loc(_YKien(SELL), BUY, 0.8)
    assert a == HOLD
    assert s == 0.0
    assert "CHAN" in r


def test_policy_khong_du_ky_vong_thi_giam_quy_mo():
    a, s, r = _loc(_YKien(HOLD), BUY, 0.8)
    assert a == BUY
    assert s == pytest.approx(0.8 * make_cfg().POLICY_FILTER_GIAM)


def test_policy_khong_danh_gia_duoc_thi_khong_can_thiep():
    """Thieu du lieu khong phai la bang chung chong lai lenh."""
    a, s, r = _loc(_YKien(HOLD, co_y_kien=False, ly_do="thieu dac trung"), BUY, 0.8)
    assert (a, s) == (BUY, 0.8)
    assert "khong y kien" in r


def test_policy_khong_bao_gio_lam_tin_hieu_manh_len():
    """Rang buoc kien truc: mot lop LOC lam tin hieu manh len thi no da tro thanh
    nguon tin hieu, va nguon tin hieu phai di qua cong thang cap rieng."""
    for y in (_YKien(BUY), _YKien(SELL), _YKien(HOLD),
              _YKien(HOLD, co_y_kien=False)):
        _, s, _ = _loc(y, BUY, 0.8)
        assert s <= 0.8


def test_khi_ensemble_da_HOLD_thi_policy_khong_the_tao_lenh():
    """Che do filter khong duoc phep tu sinh lenh, ke ca khi mo hinh rat tu tin."""
    a, s, _ = _loc(_YKien(BUY), HOLD, 0.0)
    assert a == HOLD


# ==========================================================
# Cau hinh sai
# ==========================================================
def test_che_do_khong_hop_le_thi_tat_policy_thay_vi_no(monkeypatch):
    bot = main_mod.TradingBot.__new__(main_mod.TradingBot)
    bot.strategies = [Breakout()]
    monkeypatch.setattr(main_mod.config, "POLICY_MODE", "bat_dai", raising=False)
    assert bot._tao_policy() is None
    assert len(bot.strategies) == 1


# ==========================================================
# Bo loc meta trong vong giao dich
#
# Bat bien: bo loc chi duoc CHAN hoac GIAM. No khong bao gio tao ra lenh, va
# khong bao gio cham diem mot tin hieu ma no chua tung hoc.
# ==========================================================
class _LocGia:
    """Gia lap MetaPolicy voi mot quyet dinh co dinh."""

    def __init__(self, quyet_dinh, he_so=1.0, nguon=("breakout",), san_sang=True):
        from src import meta_policy as mp
        self.san_sang = san_sang
        self.chien_luoc_nguon = list(nguon)
        self._kq = mp.KetQuaLoc(quyet_dinh=quyet_dinh, he_so=he_so,
                                p_thang=0.6, nguong=0.5, phien_ban="v_test",
                                ly_do="test")

    def danh_gia(self, hang, huong, suc_manh, regime=""):
        return self._kq


def _bot_co_loc(loc):
    import pandas as pd
    bot = main_mod.TradingBot.__new__(main_mod.TradingBot)
    bot.strategies = [Breakout()]
    bot.bo_loc_meta = loc
    return bot


def _tin_hieu(ten="breakout", action=BUY, strength=0.8):
    from src.strategies.base import Signal
    return Signal(action=action, strength=strength, strategy=ten, reason="r")


def _panel_va_df():
    import pandas as pd
    panel = pd.DataFrame([{"symbol": "BTCUSDT", "timestamp": 1_700_000_000_000,
                           "n_ma": 20, "mom_6": 0.01}])
    df = pd.DataFrame({"timestamp": [1_700_000_000_000], "close": [100.0]})
    return panel, df


def test_bo_loc_chan_thi_quyet_dinh_ve_HOLD():
    from src import meta_policy as mp
    panel, df = _panel_va_df()
    bot = _bot_co_loc(_LocGia(mp.CHAN, 0.0))
    a, s, r = bot._loc_bang_meta("BTCUSDT", panel, df, 0, "trend",
                                 [_tin_hieu()], BUY, 0.8, "goc")
    assert a == HOLD and s == 0.0
    assert "BO LOC CHAN" in r


def test_bo_loc_giam_thi_giu_huong_nhung_nho_quy_mo():
    from src import meta_policy as mp
    panel, df = _panel_va_df()
    bot = _bot_co_loc(_LocGia(mp.GIAM, 0.5))
    a, s, _ = bot._loc_bang_meta("BTCUSDT", panel, df, 0, "trend",
                                 [_tin_hieu()], BUY, 0.8, "goc")
    assert a == BUY and s == pytest.approx(0.4)


def test_bo_loc_dong_y_thi_khong_doi_gi():
    from src import meta_policy as mp
    panel, df = _panel_va_df()
    bot = _bot_co_loc(_LocGia(mp.GIU, 1.0))
    a, s, _ = bot._loc_bang_meta("BTCUSDT", panel, df, 0, "trend",
                                 [_tin_hieu()], BUY, 0.8, "goc")
    assert (a, s) == (BUY, 0.8)


def test_bo_loc_khong_cham_tin_hieu_cua_chien_luoc_no_chua_hoc():
    """Bo loc duoc huan luyen tren tin hieu cua mot tap chien luoc cu the.

    Cham diem tin hieu cua mot chien luoc khac la doan mo - no chua bao gio
    thay phan bo do luc huan luyen.
    """
    from src import meta_policy as mp
    panel, df = _panel_va_df()
    bot = _bot_co_loc(_LocGia(mp.CHAN, 0.0, nguon=("breakout",)))
    a, s, _ = bot._loc_bang_meta("BTCUSDT", panel, df, 0, "trend",
                                 [_tin_hieu("trend_following")], BUY, 0.8, "goc")
    assert (a, s) == (BUY, 0.8), "tin hieu ngoai tap huan luyen phai di tiep nguyen ven"


def test_khong_co_bo_loc_thi_tin_hieu_di_tiep_nguyen_ven():
    panel, df = _panel_va_df()
    for loc in (None, _LocGia("chan", 0.0, san_sang=False)):
        bot = _bot_co_loc(loc)
        a, s, _ = bot._loc_bang_meta("BTCUSDT", panel, df, 0, "trend",
                                     [_tin_hieu()], BUY, 0.8, "goc")
        assert (a, s) == (BUY, 0.8)


def test_bo_loc_no_thi_tin_hieu_van_di_tiep():
    """Bo loc hong phai lam he thong quay ve hanh vi cu, khong duoc chan bua."""
    class LocNo:
        san_sang = True
        chien_luoc_nguon = ["breakout"]

        def danh_gia(self, *a, **k):
            raise RuntimeError("hong")

    panel, df = _panel_va_df()
    bot = _bot_co_loc(LocNo())
    a, s, _ = bot._loc_bang_meta("BTCUSDT", panel, df, 0, "trend",
                                 [_tin_hieu()], BUY, 0.8, "goc")
    assert (a, s) == (BUY, 0.8)


def test_ensemble_da_HOLD_thi_bo_loc_khong_the_tao_lenh():
    from src import meta_policy as mp
    panel, df = _panel_va_df()
    bot = _bot_co_loc(_LocGia(mp.GIU, 1.0))
    a, _, _ = bot._loc_bang_meta("BTCUSDT", panel, df, 0, "trend",
                                 [_tin_hieu()], HOLD, 0.0, "goc")
    assert a == HOLD
