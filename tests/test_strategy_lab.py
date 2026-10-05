"""
Kiem tra Strategy Lab: DSL luat + hieu chinh nhieu phep thu.

HAI THU DUOC KHOA O DAY, ca hai deu la loai "hong im lang":

1. LLM KHONG DUOC CHAM VAO MAY. Spec la du lieu, khong phai code. Neu mot ngay
   nao do ai do them exec()/eval() vao duong ong nay cho tien, cac test ve
   danh sach trang se van pass - nen chung o day de khoa HANH VI: cot la va
   toan tu la deu bi tu choi, khong bao gio duoc "co chay thu xem sao".

2. HIEU CHINH NHIEU PHEP THU KHONG DUOC AM THAM NOI LONG. Bo dem chi tang.
   Neu no reset moi lan chay thi ta chi viec chay lab 10 lan voi 2 y tuong
   moi lan de vo hieu hoa toan bo hieu chinh - va se lam vay ma khong nhan ra.
"""
import json

import pandas as pd
import pytest

from research import strategy_lab as lab
from src.strategies import rule_spec
from src.strategies.base import BUY, HOLD, SELL


# ==========================================================
# DSL: kiem tra spec
# ==========================================================
class TestKiemTraSpec:
    def test_spec_hop_le_qua_duoc(self):
        s = rule_spec.kiem_tra_spec({"ten": "rsi_thap", "long": [["rsi", "<", 30]]})
        assert s["ten"] == "rsi_thap"

    def test_cot_la_bi_tu_choi(self):
        with pytest.raises(rule_spec.SpecKhongHopLe, match="danh sach trang"):
            rule_spec.kiem_tra_spec({"ten": "xau", "long": [["gia_tuong_lai", "<", 1]]})

    def test_toan_tu_la_bi_tu_choi(self):
        with pytest.raises(rule_spec.SpecKhongHopLe, match="toan tu"):
            rule_spec.kiem_tra_spec({"ten": "xau", "long": [["rsi", "exec", 30]]})

    def test_ve_phai_la_chuoi_bay_bi_tu_choi(self):
        with pytest.raises(rule_spec.SpecKhongHopLe):
            rule_spec.kiem_tra_spec(
                {"ten": "xau", "long": [["rsi", "<", "__import__('os').system('rm')"]]})

    def test_bool_khong_duoc_coi_la_so(self):
        """bool la subclass cua int trong Python - khong chan rieng thi
        [rsi, "<", True] lot qua va am tham so sanh voi 1.
        """
        with pytest.raises(rule_spec.SpecKhongHopLe):
            rule_spec.kiem_tra_spec({"ten": "xau", "long": [["rsi", "<", True]]})

    def test_ten_khong_hop_le_bi_tu_choi(self):
        for ten in ("", "A", "co dau cach", "Ten-Hoa", "x" * 50):
            with pytest.raises(rule_spec.SpecKhongHopLe):
                rule_spec.kiem_tra_spec({"ten": ten, "long": [["rsi", "<", 30]]})

    def test_spec_rong_bi_tu_choi(self):
        with pytest.raises(rule_spec.SpecKhongHopLe, match="it nhat mot dieu kien"):
            rule_spec.kiem_tra_spec({"ten": "rong"})

    def test_qua_nhieu_dieu_kien_bi_tu_choi(self):
        """Moi dieu kien la mot bac tu do. Luat 12 dieu kien luon khop dep voi
        qua khu va khong bao gio khop voi tuong lai.
        """
        dk = [["rsi", "<", 30 + i] for i in range(rule_spec.GIOI_HAN_DIEU_KIEN + 1)]
        with pytest.raises(rule_spec.SpecKhongHopLe, match="bac tu do"):
            rule_spec.kiem_tra_spec({"ten": "qua_nhieu", "long": dk})

    def test_so_sanh_cot_voi_cot_duoc_phep(self):
        s = rule_spec.kiem_tra_spec(
            {"ten": "tren_xu_huong", "long": [["close", ">", "ema_trend"]]})
        assert s["long"][0] == ("close", ">", "ema_trend")


# ==========================================================
# DSL: bien dich va chay
# ==========================================================
def khung(rsi, close=None, ema_trend=None):
    n = len(rsi)
    return pd.DataFrame({
        "rsi": rsi,
        "close": close or [100.0] * n,
        "ema_trend": ema_trend or [100.0] * n,
    })


class TestBienDich:
    def test_sinh_tin_hieu_long(self):
        cls = rule_spec.bien_dich({"ten": "rsi_thap", "long": [["rsi", "<", 30]]})
        st = cls()
        assert st.generate_at(khung([50, 25]), 1).action == BUY

    def test_khong_thoa_thi_hold(self):
        cls = rule_spec.bien_dich({"ten": "rsi_thap", "long": [["rsi", "<", 30]]})
        assert cls().generate_at(khung([50, 45]), 1).action == HOLD

    def test_dieu_kien_ket_hop_bang_va(self):
        cls = rule_spec.bien_dich({"ten": "hai_dk",
                                   "long": [["rsi", "<", 30], ["close", ">", "ema_trend"]]})
        st = cls()
        # RSI dat nhung gia duoi duong xu huong -> khong vao
        assert st.generate_at(khung([50, 25], close=[100, 90],
                                    ema_trend=[100, 100]), 1).action == HOLD
        assert st.generate_at(khung([50, 25], close=[100, 110],
                                    ema_trend=[100, 100]), 1).action == BUY

    def test_short_hoat_dong(self):
        cls = rule_spec.bien_dich({"ten": "rsi_cao", "short": [["rsi", ">", 70]]})
        assert cls().generate_at(khung([50, 80]), 1).action == SELL

    def test_toan_tu_cat_len(self):
        cls = rule_spec.bien_dich({"ten": "cat_xu_huong",
                                   "long": [["close", "cat_len", "ema_trend"]]})
        st = cls()
        df = khung([50, 50], close=[99, 101], ema_trend=[100, 100])
        assert st.generate_at(df, 1).action == BUY
        # da o tren tu truoc thi KHONG phai cat len
        df2 = khung([50, 50], close=[101, 102], ema_trend=[100, 100])
        assert st.generate_at(df2, 1).action == HOLD

    def test_nan_khong_sinh_tin_hieu(self):
        """Vung warmup co NaN. Coi NaN la thoa dieu kien se sinh lenh ao o dau
        moi cua so walk-forward.
        """
        cls = rule_spec.bien_dich({"ten": "rsi_thap", "long": [["rsi", "<", 30]]})
        assert cls().generate_at(khung([float("nan"), float("nan")]), 1).action == HOLD

    def test_dong_dau_tien_khong_sinh_tin_hieu(self):
        cls = rule_spec.bien_dich({"ten": "rsi_thap", "long": [["rsi", "<", 30]]})
        assert cls().generate_at(khung([25]), 0).action == HOLD

    def test_bien_dich_nhieu_bo_qua_spec_hong(self):
        """Mot y tuong sai cua LLM khong duoc chan 19 y tuong con lai."""
        ra = rule_spec.bien_dich_nhieu([
            {"ten": "tot", "long": [["rsi", "<", 30]]},
            {"ten": "hong", "long": [["cot_bia", "<", 30]]},
            {"ten": "tot_hai", "short": [["rsi", ">", 70]]},
        ])
        assert [c.name for c in ra] == ["tot", "tot_hai"]


# ==========================================================
# Hieu chinh nhieu phep thu
# ==========================================================
class TestHieuChinh:
    def test_mot_phep_thu_thi_khong_hieu_chinh(self):
        assert lab.ky_vong_cuc_dai_chuan(1) == 0.0

    def test_cang_thu_nhieu_nguong_cang_cao(self):
        assert (lab.ky_vong_cuc_dai_chuan(5)
                < lab.ky_vong_cuc_dai_chuan(20)
                < lab.ky_vong_cuc_dai_chuan(100))

    def test_gia_tri_xap_xi_dung(self):
        # E[max cua 20 bien chuan] ~ 1.87 theo cong thuc Bailey & Lopez de Prado
        assert lab.ky_vong_cuc_dai_chuan(20) == pytest.approx(1.87, abs=0.1)

    def test_nguong_khong_bao_gio_thap_hon_cong_co_ban(self):
        n = lab.nguong_sharpe(n_thu=1, so_quan_sat=100000, bars_per_year=2190,
                              sharpe_co_ban=1.0)
        assert n == 1.0

    def test_nguong_tang_theo_so_phep_thu(self):
        chung = dict(so_quan_sat=5000, bars_per_year=2190, sharpe_co_ban=1.0)
        assert (lab.nguong_sharpe(n_thu=1, **chung)
                < lab.nguong_sharpe(n_thu=50, **chung))

    def test_it_du_lieu_thi_nguong_cao_hon(self):
        """Cung so phep thu, cang it quan sat thi cuc dai nhieu cang de cao -
        nen nguong phai cao len, khong duoc de nguyen.
        """
        chung = dict(n_thu=30, bars_per_year=2190, sharpe_co_ban=1.0)
        assert (lab.nguong_sharpe(so_quan_sat=20000, **chung)
                < lab.nguong_sharpe(so_quan_sat=2000, **chung))


class TestBoDem:
    def test_bo_dem_chi_tang(self, tmp_path, monkeypatch):
        p = tmp_path / "trials.json"
        monkeypatch.setattr(lab, "DUONG_DAN_BO_DEM", str(p))
        assert lab.doc_bo_dem()["so_lan_thu"] == 0
        lab.ghi_bo_dem(lab.doc_bo_dem(), 5, "lan 1")
        assert lab.doc_bo_dem()["so_lan_thu"] == 5
        lab.ghi_bo_dem(lab.doc_bo_dem(), 3, "lan 2")
        assert lab.doc_bo_dem()["so_lan_thu"] == 8

    def test_luu_lich_su_tung_lan(self, tmp_path, monkeypatch):
        p = tmp_path / "trials.json"
        monkeypatch.setattr(lab, "DUONG_DAN_BO_DEM", str(p))
        lab.ghi_bo_dem(lab.doc_bo_dem(), 4, "chay thu")
        assert lab.doc_bo_dem()["lich_su"][-1]["them"] == 4

    def test_file_hong_thi_bao_loi_chu_khong_reset_ve_0(self, tmp_path, monkeypatch):
        """Reset ve 0 la huong sai NGUY HIEM: no noi long cong mot cach im lang."""
        p = tmp_path / "trials.json"
        p.write_text("{khong phai json", encoding="utf-8")
        monkeypatch.setattr(lab, "DUONG_DAN_BO_DEM", str(p))
        with pytest.raises(RuntimeError, match="hong"):
            lab.doc_bo_dem()
