"""
Kiem tra cac route moi cua bang dieu khien: Strategy Lab + kho luat.

BA THU DUOC KHOA O DAY:

  1. CONG THANG CAP KHONG DUOC NOI LONG KHI DI QUA HTTP. Kho luat da co cong
     rieng (tests/test_kho_luat.py), nhung mot route web co the vo tinh bo qua
     chung. Buoc len `chu_dong` qua UI phai doi dung cau xac nhan, y het nut
     bat bot bang tien that.

  2. SPEC HONG PHAI BI BAT LUC SOAN. Neu de spec hong xuong toi lab, no van bi
     tu choi - nhung luc do da TON MOT PHEP THU vinh vien vao bo dem. Kiem tra
     som la de tiet kiem thu do.

  3. KHONG BAO GIO GHI RA JSON KHONG HOP LE. profit_factor = inf khi mot cua
     so khong co lenh thua nao, va json.dump cua Python ghi no thanh
     `Infinity` - thu ma JSON.parse cua trinh duyet tu choi. Loi nay an rat
     lau vi Python doc lai duoc file cua chinh no; no chi lo ra khi mot cong
     cu khac cham vao. Da tung xay ra that trong du an nay.
"""
import json
import math

import pytest

from research import strategy_lab
from src.strategies import kho_luat as kl


# ==========================================================
# Khong bao gio ghi JSON khong hop le
# ==========================================================
class TestLamSach:
    def test_inf_thanh_none(self):
        assert strategy_lab.lam_sach(float("inf")) is None
        assert strategy_lab.lam_sach(float("-inf")) is None

    def test_nan_thanh_none(self):
        assert strategy_lab.lam_sach(float("nan")) is None

    def test_so_binh_thuong_giu_nguyen(self):
        assert strategy_lab.lam_sach(1.25) == 1.25
        assert strategy_lab.lam_sach(0) == 0

    def test_di_sau_vao_dict_va_list(self):
        ra = strategy_lab.lam_sach(
            {"a": [1.0, float("inf")], "b": {"c": float("nan"), "d": "x"}})
        assert ra == {"a": [1.0, None], "b": {"c": None, "d": "x"}}

    def test_ket_qua_dump_duoc_voi_allow_nan_false(self):
        """Day moi la bat bien that: ket qua phai la JSON HOP LE."""
        ban_ghi = {"theo_ma": {"BTC": {"pf": float("inf"), "sharpe": 1.2}}}
        json.dumps(strategy_lab.lam_sach(ban_ghi), allow_nan=False)

    def test_kho_luat_khong_ghi_duoc_inf(self, tmp_path):
        """Bang chung den tu lab co the chua inf - kho phai lam sach truoc khi ghi."""
        kho = kl.KhoLuat(duong_dan=str(tmp_path / "kho.json"))
        kho.them_ung_vien(
            {"ten": "co_inf", "long": [["rsi", "<", 30]]},
            {"qua_cong": True, "sharpe_min": 1.4, "tong_lenh": 100,
             "theo_ma": {"BTCUSDT": {"pf": float("inf")}}})
        raw = (tmp_path / "kho.json").read_text(encoding="utf-8")
        assert "Infinity" not in raw and "NaN" not in raw
        json.loads(raw)          # doc lai bang bo doc nghiem ngat


# ==========================================================
# Route: soan gia thuyet
# ==========================================================
@pytest.fixture
def app(tmp_path, monkeypatch):
    from webui import app as app_mod
    monkeypatch.setattr(app_mod, "BASE_DIR", str(tmp_path))
    (tmp_path / "research").mkdir()
    (tmp_path / "data" / "reports").mkdir(parents=True)
    monkeypatch.setattr(strategy_lab, "DUONG_DAN_BO_DEM",
                        str(tmp_path / "data" / "trials.json"))
    app_mod.app.config["TESTING"] = True
    return app_mod.app.test_client()


class TestSoanGiaThuyet:
    def test_luu_spec_hop_le(self, app):
        r = app.post("/api/gia-thuyet", json={"noi_dung": json.dumps(
            [{"ten": "rsi_thap", "long": [["rsi", "<", 30]]}])})
        assert r.status_code == 200
        assert r.get_json()["so_gia_thuyet"] == 1

    def test_spec_cot_la_bi_tu_choi_ngay_luc_soan(self, app):
        r = app.post("/api/gia-thuyet", json={"noi_dung": json.dumps(
            [{"ten": "xau", "long": [["cot_bia", "<", 1]]}])})
        assert r.status_code == 400
        assert "0" in r.get_json()["chi_tiet"]

    def test_json_sai_cu_phap_bi_tu_choi(self, app):
        r = app.post("/api/gia-thuyet", json={"noi_dung": "[{hong"})
        assert r.status_code == 400

    def test_khong_phai_mang_bi_tu_choi(self, app):
        r = app.post("/api/gia-thuyet", json={"noi_dung": '{"ten": "x"}'})
        assert r.status_code == 400

    def test_qua_nhieu_gia_thuyet_bi_tu_choi(self, app):
        nhieu = [{"ten": "ten_%d" % i, "long": [["rsi", "<", 30]]} for i in range(60)]
        r = app.post("/api/gia-thuyet", json={"noi_dung": json.dumps(nhieu)})
        assert r.status_code == 400

    def test_mot_spec_hong_thi_KHONG_ghi_gi_ca(self, app):
        """Ghi mot nua danh sach roi bao loi la trang thai te nhat."""
        app.post("/api/gia-thuyet", json={"noi_dung": json.dumps(
            [{"ten": "tot", "long": [["rsi", "<", 30]]}])})
        app.post("/api/gia-thuyet", json={"noi_dung": json.dumps(
            [{"ten": "tot_hai", "long": [["rsi", "<", 30]]},
             {"ten": "hong", "long": [["cot_bia", "<", 1]]}])})
        assert app.get("/api/gia-thuyet").get_json()["so_gia_thuyet"] == 1


# ==========================================================
# Route: thang cap / ha cap kho luat
# ==========================================================
@pytest.fixture
def kho(tmp_path, monkeypatch):
    k = kl.KhoLuat(duong_dan=str(tmp_path / "kho.json"))
    monkeypatch.setattr(kl, "DUONG_DAN_MAC_DINH", k.duong_dan)
    k.them_ung_vien({"ten": "thu_nghiem", "long": [["rsi", "<", 30]]},
                    {"qua_cong": True, "sharpe_min": 1.4, "tong_lenh": 120})
    return k


class TestRouteKhoLuat:
    def test_len_bong_khong_doi_xac_nhan(self, app, kho):
        r = app.post("/api/kho-luat/thang-cap", json={"ten": "thu_nghiem"})
        assert r.status_code == 200
        assert r.get_json()["trang_thai"] == kl.BONG

    def test_len_chu_dong_DOI_cau_xac_nhan(self, app, kho):
        app.post("/api/kho-luat/thang-cap", json={"ten": "thu_nghiem"})
        r = app.post("/api/kho-luat/thang-cap", json={"ten": "thu_nghiem", "ep": True})
        assert r.status_code == 428
        assert r.get_json()["can_xac_nhan"] is True
        assert kho.lay("thu_nghiem")["trang_thai"] == kl.BONG   # chua doi

    def test_cau_xac_nhan_sai_van_bi_chan(self, app, kho):
        app.post("/api/kho-luat/thang-cap", json={"ten": "thu_nghiem"})
        r = app.post("/api/kho-luat/thang-cap",
                     json={"ten": "thu_nghiem", "ep": True, "xac_nhan": "dong y"})
        assert r.status_code == 428

    def test_cau_xac_nhan_dung_thi_len_duoc(self, app, kho):
        from webui.app import CAU_XAC_NHAN
        app.post("/api/kho-luat/thang-cap", json={"ten": "thu_nghiem"})
        r = app.post("/api/kho-luat/thang-cap",
                     json={"ten": "thu_nghiem", "ep": True, "xac_nhan": CAU_XAC_NHAN})
        assert r.status_code == 200
        assert r.get_json()["trang_thai"] == kl.CHU_DONG

    def test_chua_du_ngay_bong_van_bi_chan_du_co_xac_nhan(self, app, kho):
        """Cau xac nhan khong thay the duoc dieu kien so ngay - do la hai cong
        khac nhau. Chi co --ep moi bo qua duoc so ngay.
        """
        from webui.app import CAU_XAC_NHAN
        app.post("/api/kho-luat/thang-cap", json={"ten": "thu_nghiem"})
        r = app.post("/api/kho-luat/thang-cap",
                     json={"ten": "thu_nghiem", "xac_nhan": CAU_XAC_NHAN})
        assert r.status_code == 409
        assert "ngay" in r.get_json()["loi"]

    def test_ha_cap_khong_doi_gi(self, app, kho):
        app.post("/api/kho-luat/thang-cap", json={"ten": "thu_nghiem"})
        r = app.post("/api/kho-luat/ha-cap", json={"ten": "thu_nghiem"})
        assert r.status_code == 200
        assert r.get_json()["trang_thai"] == kl.UNG_VIEN

    def test_ten_khong_ton_tai_tra_404(self, app, kho):
        assert app.post("/api/kho-luat/thang-cap",
                        json={"ten": "khong_co"}).status_code == 404

    def test_hanh_dong_la_bi_tu_choi(self, app, kho):
        assert app.post("/api/kho-luat/xoa-sach",
                        json={"ten": "thu_nghiem"}).status_code == 400


# ==========================================================
# Kenh dieu khien UI -> bot
# ==========================================================
class TestKenhDieuKhien:
    """Kenh nay lam bot HANH DONG, nen no phai het suc hep va phai co han.

    Hai lop danh sach trang co y trung lap: webui.app.LENH_CHO_PHEP va
    main.TradingBot.LENH_CHO_PHEP. Lop thu hai moi la cai quyet dinh - web co
    the bi sua, con bot thi tu bao ve minh.
    """

    def test_lenh_la_bi_tu_choi_o_web(self, app):
        assert app.post("/api/lenh/dong_het_vi_the").status_code == 400

    def test_bot_khong_chay_thi_tu_choi_xep_lenh(self, app):
        """Xep mot lenh khong ai doc chi tao cam giac da lam gi do."""
        r = app.post("/api/lenh/reset_breaker")
        assert r.status_code == 409
        assert "khong chay" in r.get_json()["loi"]

    def test_hai_danh_sach_trang_khop_nhau(self):
        """Web cho phep gi thi bot cung phai chap nhan - lech nhau nghia la co
        nut bam ra loi im lang, hoac co lenh bot chay ma web khong biet.
        """
        import main
        from webui.app import LENH_CHO_PHEP
        assert set(LENH_CHO_PHEP) == set(main.TradingBot.LENH_CHO_PHEP)


class TestLenhTrongStorage:
    @pytest.fixture
    def st(self, tmp_path):
        from src.storage import Storage
        return Storage(db_path=str(tmp_path / "t.db"))

    def test_lenh_moi_thi_doc_duoc(self, st):
        st.them_lenh("reset_breaker")
        assert [r["lenh"] for r in st.lenh_cho_xu_ly()] == ["reset_breaker"]

    def test_da_xu_ly_thi_khong_doc_lai(self, st):
        i = st.them_lenh("reset_breaker")
        st.danh_dau_lenh(i, "xong", "ok")
        assert st.lenh_cho_xu_ly() == []

    def test_lenh_qua_han_KHONG_duoc_chay(self, st):
        """Bot tat ba ngay roi bat lai khong nen thi hanh mot lenh cu: boi canh
        da khac, va mot 'reset breaker' tu qua khu se am tham xoa mot canh bao
        dang con dung.
        """
        st.them_lenh("reset_breaker")
        assert st.lenh_cho_xu_ly(han_giay=-1) == []

    def test_lenh_qua_han_duoc_danh_dau_chu_khong_bi_xoa(self, st):
        i = st.them_lenh("reset_breaker")
        st.lenh_cho_xu_ly(han_giay=-1)
        with st.conn() as c:
            row = c.execute("SELECT trang_thai FROM lenh_dieu_khien WHERE id=?",
                            (i,)).fetchone()
        assert row["trang_thai"] == "het_han"

    def test_nhip_tim_ghi_de_mot_dong_duy_nhat(self, st):
        st.ghi_trang_thai_bot(False, "", 1, 0.01, 10000.0)
        st.ghi_trang_thai_bot(True, "drawdown", 2, 0.02, 9500.0)
        with st.conn() as c:
            rows = c.execute("SELECT * FROM trang_thai_bot").fetchall()
        assert len(rows) == 1
        assert rows[0]["breaker_ngat"] == 1
        assert rows[0]["breaker_ly_do"] == "drawdown"
