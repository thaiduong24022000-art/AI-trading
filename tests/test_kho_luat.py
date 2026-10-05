"""
Kiem tra kho chien luoc luat - duong di tu Strategy Lab den ban live.

Cho nay la noi mot y tuong cua LLM co the tro thanh mot lenh bang tien that,
nen cac cong o day duoc khoa bang test chu khong bang thien chi:

  1. Chua qua cong thong ke thi khong duoc vao kho. Neu lot vao duoc, moi cong
     phia sau tro nen vo nghia - chung chi kiem tra "da chay bong du lau chua"
     va tin rang phan thong ke da xong tu truoc.
  2. Khong nhay coc tu ung_vien thang len chu_dong. Bo qua che do bong nghia la
     dem thang mot thu chua ai nhin thay chay that ra dung tien.
  3. Duong XUONG luon thong, khong dieu kien gi. Luc can ha cap nhat la luc moi
     thu dang hong - do khong phai luc de bat nguoi ta thoa man dieu kien.
"""
import json

import pytest

from src.strategies import kho_luat
from src.strategies.kho_luat import BONG, CHU_DONG, DA_LOAI, UNG_VIEN, KhoLuat, KhoLuatLoi
from src.strategies.rule_spec import SpecKhongHopLe


SPEC = {"ten": "rsi_thap_test", "mo_ta": "rsi thap", "long": [["rsi", "<", 30]]}
BANG_CHUNG = {"qua_cong": True, "sharpe_min": 1.4, "tong_lenh": 150,
              "nguong_da_hieu_chinh": 1.2, "so_phep_thu_luy_ke": 8}


@pytest.fixture
def kho(tmp_path):
    return KhoLuat(duong_dan=str(tmp_path / "kho.json"))


class TestThemUngVien:
    def test_them_duoc_khi_co_bang_chung(self, kho):
        muc = kho.them_ung_vien(SPEC, BANG_CHUNG)
        assert muc["trang_thai"] == UNG_VIEN
        assert kho.lay("rsi_thap_test") is not None

    def test_chua_qua_cong_thi_bi_tu_choi(self, kho):
        with pytest.raises(KhoLuatLoi, match="chua qua cong"):
            kho.them_ung_vien(SPEC, {"qua_cong": False, "sharpe_min": 0.2})

    def test_khong_co_bang_chung_thi_bi_tu_choi(self, kho):
        with pytest.raises(KhoLuatLoi, match="chua qua cong"):
            kho.them_ung_vien(SPEC, {})

    def test_spec_hong_bi_tu_choi(self, kho):
        with pytest.raises(SpecKhongHopLe):
            kho.them_ung_vien({"ten": "xau", "long": [["cot_bia", "<", 1]]}, BANG_CHUNG)

    def test_khong_them_trung_ten(self, kho):
        kho.them_ung_vien(SPEC, BANG_CHUNG)
        with pytest.raises(KhoLuatLoi, match="da co trong kho"):
            kho.them_ung_vien(SPEC, BANG_CHUNG)


class TestThangCap:
    def test_ung_vien_len_bong(self, kho):
        kho.them_ung_vien(SPEC, BANG_CHUNG)
        assert kho.thang_cap("rsi_thap_test")["trang_thai"] == BONG

    def test_khong_nhay_coc_len_chu_dong(self, kho):
        """ung_vien thang cap mot lan chi len duoc BONG, khong len thang chu_dong."""
        kho.them_ung_vien(SPEC, BANG_CHUNG)
        muc = kho.thang_cap("rsi_thap_test")
        assert muc["trang_thai"] == BONG
        assert muc["trang_thai"] != CHU_DONG

    def test_chua_du_ngay_bong_thi_bi_chan(self, kho):
        kho.them_ung_vien(SPEC, BANG_CHUNG)
        kho.thang_cap("rsi_thap_test")          # -> bong, vua vao hom nay
        with pytest.raises(KhoLuatLoi, match="ngay"):
            kho.thang_cap("rsi_thap_test")

    def test_du_ngay_bong_thi_len_duoc(self, kho, monkeypatch):
        kho.them_ung_vien(SPEC, BANG_CHUNG)
        kho.thang_cap("rsi_thap_test")
        monkeypatch.setattr(kho, "so_ngay_o_bong",
                            lambda ten: kho_luat.NGAY_BONG_TOI_THIEU + 1)
        assert kho.thang_cap("rsi_thap_test")["trang_thai"] == CHU_DONG

    def test_ep_bo_qua_dieu_kien_so_ngay(self, kho):
        kho.them_ung_vien(SPEC, BANG_CHUNG)
        kho.thang_cap("rsi_thap_test")
        assert kho.thang_cap("rsi_thap_test", ep=True)["trang_thai"] == CHU_DONG

    def test_ep_KHONG_bo_qua_duoc_buoc_bong(self, kho):
        """--ep chi bo qua so NGAY, khong bo qua duoc viec phai di qua bong."""
        kho.them_ung_vien(SPEC, BANG_CHUNG)
        assert kho.thang_cap("rsi_thap_test", ep=True)["trang_thai"] == BONG

    def test_da_o_muc_cao_nhat_thi_bao_loi(self, kho):
        kho.them_ung_vien(SPEC, BANG_CHUNG)
        kho.thang_cap("rsi_thap_test")
        kho.thang_cap("rsi_thap_test", ep=True)
        with pytest.raises(KhoLuatLoi, match="cao nhat"):
            kho.thang_cap("rsi_thap_test")

    def test_khong_co_trong_kho(self, kho):
        with pytest.raises(KhoLuatLoi, match="Khong co"):
            kho.thang_cap("khong_ton_tai")


class TestHaCap:
    def test_ha_cap_khong_can_dieu_kien_gi(self, kho):
        kho.them_ung_vien(SPEC, BANG_CHUNG)
        kho.thang_cap("rsi_thap_test")
        kho.thang_cap("rsi_thap_test", ep=True)
        assert kho.ha_cap("rsi_thap_test")["trang_thai"] == BONG
        assert kho.ha_cap("rsi_thap_test")["trang_thai"] == UNG_VIEN
        assert kho.ha_cap("rsi_thap_test")["trang_thai"] == DA_LOAI

    def test_loai_bo_tu_bat_ky_trang_thai_nao(self, kho):
        kho.them_ung_vien(SPEC, BANG_CHUNG)
        kho.thang_cap("rsi_thap_test")
        assert kho.loai_bo("rsi_thap_test", "khong hieu qua")["trang_thai"] == DA_LOAI


class TestBienDichVaLichSu:
    def test_chi_bien_dich_dung_trang_thai_yeu_cau(self, kho):
        kho.them_ung_vien(SPEC, BANG_CHUNG)
        assert len(kho.bien_dich_theo_trang_thai(UNG_VIEN)) == 1
        assert kho.bien_dich_theo_trang_thai(CHU_DONG) == []
        kho.thang_cap("rsi_thap_test")
        assert len(kho.bien_dich_theo_trang_thai(BONG)) == 1

    def test_spec_hong_trong_kho_khong_lam_sap_ca_lo(self, kho):
        """Ai do sua tay file kho thanh spec sai - bo qua muc do, khong nem."""
        kho.them_ung_vien(SPEC, BANG_CHUNG)
        data = json.load(open(kho.duong_dan, encoding="utf-8"))
        data["muc"]["rsi_thap_test"]["spec"]["long"] = [["cot_khong_ton_tai", "<", 1]]
        json.dump(data, open(kho.duong_dan, "w", encoding="utf-8"))
        assert kho.bien_dich_theo_trang_thai(UNG_VIEN) == []

    def test_moi_lan_doi_trang_thai_deu_ghi_lich_su(self, kho):
        kho.them_ung_vien(SPEC, BANG_CHUNG)
        kho.thang_cap("rsi_thap_test", "cho chay thu")
        kho.ha_cap("rsi_thap_test", "tin hieu qua thua")
        ls = kho.lay("rsi_thap_test")["lich_su"]
        assert [h["den"] for h in ls] == [UNG_VIEN, BONG, UNG_VIEN]
        assert ls[-1]["ly_do"] == "tin hieu qua thua"

    def test_file_hong_thi_bao_loi_chu_khong_coi_la_kho_rong(self, kho):
        """Kho rong nghia la 'chua thu gi' - he thong se vui ve ghi de len
        lich su da mat.
        """
        open(kho.duong_dan, "w", encoding="utf-8").write("{khong phai json")
        with pytest.raises(KhoLuatLoi, match="hong"):
            kho.tat_ca()


class TestNoiVaoEnsemble:
    def test_chien_luoc_chu_dong_dung_duoc_trong_ensemble(self, kho):
        from src.strategies import build_ensemble
        kho.them_ung_vien(SPEC, BANG_CHUNG)
        kho.thang_cap("rsi_thap_test")
        kho.thang_cap("rsi_thap_test", ep=True)
        ens = build_ensemble(["breakout", "rsi_thap_test"], kho=kho)
        assert [s.name for s in ens] == ["breakout", "rsi_thap_test"]

    def test_chien_luoc_che_do_BONG_KHONG_vao_duoc_ensemble(self, kho):
        """Chi viec co mat trong ensemble da lam doi trong so cua cac chien
        luoc that - luc do che do bong khong con la bong nua.
        """
        from src.strategies import build_ensemble
        kho.them_ung_vien(SPEC, BANG_CHUNG)
        kho.thang_cap("rsi_thap_test")      # -> bong
        with pytest.raises(ValueError, match="Khong co chien luoc"):
            build_ensemble(["breakout", "rsi_thap_test"], kho=kho)

    def test_ten_khong_ton_tai_van_bao_loi_ro(self, kho):
        from src.strategies import build_ensemble
        with pytest.raises(ValueError, match="Khong co chien luoc"):
            build_ensemble(["khong_co_dau"], kho=kho)
