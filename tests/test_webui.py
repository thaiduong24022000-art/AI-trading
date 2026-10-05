"""
Kiem tra phan backend cua bang dieu khien.

TRONG TAM LA HAI THU CO THE GAY THIET HAI THAT:

  1. `env_store` sua tep .env - noi chua khoa API. Mot loi o day co the lam mat
     khoa, ghi mot gia tri xau khien bot doc ra mac dinh mot cach im lang, hoac
     de khoa bi mat ro ri ra HTTP.

  2. Danh sach trang script - UI chay tien trinh tren may. Mot loi o tang tren
     khong duoc bien thanh "chay lenh tuy y".

Cac test o day co y ban truong hop xau vao: khoa bi mat, gia tri sai kieu, ky tu
xuong dong, script ngoai danh sach.
"""
import os

import pytest

from webui import env_store, jobs


@pytest.fixture
def env(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_text(
        "# Bybit\n"
        "BYBIT_API_KEY=khoa_that_khong_duoc_lo\n"
        "BYBIT_API_SECRET=bi_mat_khong_duoc_lo\n"
        "BYBIT_TESTNET=true\n"
        "\n"
        "# Che do\n"
        "DRY_RUN=true\n"
        "SYMBOLS=BTCUSDT,ETHUSDT\n"
        "KHOA_LA_HOAC=giu_nguyen\n",
        encoding="utf-8")
    monkeypatch.setattr(env_store, "ENV_PATH", str(p))
    return p


# ==========================================================
# Khoa bi mat khong bao gio roi khoi may
# ==========================================================
def test_doc_gia_tri_khong_bao_gio_tra_ve_khoa_bi_mat(env):
    gt = env_store.doc_gia_tri()
    assert "BYBIT_API_SECRET" not in gt
    assert "BYBIT_API_KEY" not in gt
    assert "bi_mat_khong_duoc_lo" not in str(gt)


def test_chi_bao_co_dat_hay_chua_chu_khong_bao_gia_tri(env):
    tt = env_store.trang_thai_bi_mat()
    assert tt == {"BYBIT_API_KEY": True, "BYBIT_API_SECRET": True,
                  "ANTHROPIC_API_KEY": False, "OKX_API_KEY": False,
                  "OKX_API_SECRET": False, "OKX_API_PASSPHRASE": False,
                  "TELEGRAM_BOT_TOKEN": False, "TELEGRAM_CHAT_ID": False}
    assert "khoa_that" not in str(tt)


def test_mo_ta_khoa_khong_lo_bi_mat(env):
    assert "bi_mat_khong_duoc_lo" not in str(env_store.mo_ta_khoa())


def test_khong_the_ghi_de_khoa_bi_mat(env):
    kq = env_store.ghi({"BYBIT_API_SECRET": "khoa_gia_cua_ke_tan_cong"})
    assert kq["ok"] is False
    assert "BYBIT_API_SECRET" in kq["loi"]
    assert "bi_mat_khong_duoc_lo" in env.read_text(encoding="utf-8")


# ==========================================================
# Kiem tra gia tri
# ==========================================================
@pytest.mark.parametrize("khoa,gia_tri", [
    ("POLICY_MODE", "shadow"),
    ("DRY_RUN", "false"),
    ("SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT"),
    ("RISK_PER_TRADE", "0.01"),
    ("KLINE_INTERVAL", "240"),
    ("CATEGORY", "linear"),
])
def test_gia_tri_hop_le_thi_qua(env, khoa, gia_tri):
    assert env_store.kiem_tra(khoa, gia_tri) is None


@pytest.mark.parametrize("khoa,gia_tri", [
    ("POLICY_MODE", "bat_dai"),
    ("DRY_RUN", "co"),
    ("SYMBOLS", "btc usdt"),
    ("SYMBOLS", ""),
    ("RISK_PER_TRADE", "0.9"),          # 90% von moi lenh
    ("RISK_PER_TRADE", "khong phai so"),
    ("KLINE_INTERVAL", "7"),            # khung Bybit khong co
    ("CATEGORY", "futures"),
    ("MAX_DAILY_DRAWDOWN", "0.9"),
])
def test_gia_tri_sai_thi_bi_tu_choi_kem_ly_do(env, khoa, gia_tri):
    ly_do = env_store.kiem_tra(khoa, gia_tri)
    assert ly_do, "%s=%s phai bi tu choi" % (khoa, gia_tri)


def test_gia_tri_xuong_dong_bi_chan(env):
    """Xuong dong se pha vo dinh dang .env - dong sau tro thanh mot khoa la."""
    assert env_store.kiem_tra("SYMBOLS", "BTCUSDT\nDRY_RUN=false")


def test_khoa_ngoai_danh_sach_bi_tu_choi(env):
    assert env_store.kiem_tra("PATH", "/tmp")
    assert env_store.kiem_tra("DB_PATH", "/tmp/x.db")


# ==========================================================
# Ghi khong duoc lam mat gi
# ==========================================================
def test_ghi_giu_nguyen_comment_va_khoa_la(env):
    env_store.ghi({"DRY_RUN": "false"})
    noi_dung = env.read_text(encoding="utf-8")
    assert "# Bybit" in noi_dung
    assert "# Che do" in noi_dung
    assert "KHOA_LA_HOAC=giu_nguyen" in noi_dung
    assert "BYBIT_API_KEY=khoa_that_khong_duoc_lo" in noi_dung
    assert "DRY_RUN=false" in noi_dung


def test_ghi_khoa_chua_co_thi_them_vao_cuoi(env):
    env_store.ghi({"POLICY_MODE": "shadow"})
    assert "POLICY_MODE=shadow" in env.read_text(encoding="utf-8")
    assert env_store.doc_gia_tri()["POLICY_MODE"] == "shadow"


def test_mot_khoa_sai_thi_khong_khoa_nao_duoc_ghi(env):
    """Khong duoc de lai .env o trang thai sua mot nua."""
    kq = env_store.ghi({"DRY_RUN": "false", "POLICY_MODE": "khong_ton_tai"})
    assert kq["ok"] is False
    assert "DRY_RUN=true" in env.read_text(encoding="utf-8")


def test_ghi_tao_ban_sao_du_phong(env):
    env_store.ghi({"DRY_RUN": "false"})
    assert os.path.exists(str(env) + ".bak")
    assert "DRY_RUN=true" in open(str(env) + ".bak", encoding="utf-8").read()


def test_ghi_bao_lai_dung_nhung_gi_da_doi(env):
    kq = env_store.ghi({"DRY_RUN": "false", "BYBIT_TESTNET": "true"})
    assert kq["ok"] is True
    assert list(kq["da_doi"]) == ["DRY_RUN"]      # BYBIT_TESTNET von da la true
    assert kq["da_doi"]["DRY_RUN"] == {"cu": "true", "moi": "false"}
    assert kq["can_khoi_dong_lai"] is True


def test_bao_khi_doi_khoa_lam_lech_dau_van_tay_mo_hinh(env):
    """Doi ATR_STOP_MULT la doi BAI TOAN ma mo hinh da hoc - UI phai canh bao
    truoc, khong de nguoi dung phat hien bang cach thay policy bong dung im lang."""
    kq = env_store.ghi({"ATR_STOP_MULT": "1.5"})
    assert kq["doi_bai_toan"] == ["ATR_STOP_MULT"]


def test_doi_khoa_binh_thuong_thi_khong_bao_doi_bai_toan(env):
    assert env_store.ghi({"DRY_RUN": "false"})["doi_bai_toan"] == []


# ==========================================================
# Danh sach trang script
# ==========================================================
def test_script_ngoai_danh_sach_bi_tu_choi():
    for xau in ("main.py", "../thu_gi_do.py", "rm -rf /", "-m os"):
        with pytest.raises(ValueError):
            jobs._kiem_tra_script(xau)


def test_script_trong_danh_sach_thi_qua():
    jobs._kiem_tra_script("run_backtest.py")
    jobs._kiem_tra_script("run_policy.py")
    jobs._kiem_tra_script("-m research.download_universe")


def test_khong_the_start_job_voi_script_la():
    with pytest.raises(ValueError):
        jobs.JobManager().start("gi_do", "curl.exe", [], "nhan")


# ==========================================================
# Khoa bi mat: GHI duoc, DOC thi khong
#
# Day la mat hang rao moi mo ra, nen no la mat duoc ban nhieu nhat o duoi.
# Quy tac chi co mot cau: gia tri di VAO duoc, khong di RA duoc - khong qua
# ket qua tra ve, khong qua thong bao loi.
# ==========================================================
def test_ghi_bi_mat_dat_duoc_khoa_moi(env):
    kq = env_store.ghi_bi_mat({"OKX_API_KEY": "okx-key-moi-toanh"})
    assert kq["ok"] is True
    assert kq["da_dat"] == ["OKX_API_KEY"]
    assert "OKX_API_KEY=okx-key-moi-toanh" in env.read_text(encoding="utf-8")


def test_ghi_bi_mat_khong_bao_gio_nhac_lai_gia_tri(env):
    kq = env_store.ghi_bi_mat({"OKX_API_SECRET": "gia-tri-khong-duoc-vong-lai"})
    assert "gia-tri-khong-duoc-vong-lai" not in str(kq)


def test_ghi_bi_mat_ghi_de_khoa_cu_va_khong_lo_ca_hai(env):
    kq = env_store.ghi_bi_mat({"BYBIT_API_SECRET": "bi_mat_moi"})
    assert kq["ok"] is True
    assert "bi_mat_khong_duoc_lo" not in str(kq)      # gia tri cu
    assert "bi_mat_moi" not in str(kq)                # gia tri moi
    assert "BYBIT_API_SECRET=bi_mat_moi" in env.read_text(encoding="utf-8")


def test_chuoi_rong_la_xoa_khoa(env):
    """Cach go mot khoa da dan ra ngoai ma khong phai mo trinh soan thao."""
    kq = env_store.ghi_bi_mat({"BYBIT_API_KEY": ""})
    assert kq["ok"] is True
    assert kq["da_xoa"] == ["BYBIT_API_KEY"]
    assert "BYBIT_API_KEY=\n" in env.read_text(encoding="utf-8")
    assert env_store.trang_thai_bi_mat()["BYBIT_API_KEY"] is False


def test_ghi_bi_mat_giu_nguyen_comment_va_khoa_khac(env):
    env_store.ghi_bi_mat({"OKX_API_KEY": "abc123"})
    noi_dung = env.read_text(encoding="utf-8")
    assert "# Bybit" in noi_dung
    assert "KHOA_LA_HOAC=giu_nguyen" in noi_dung
    assert "DRY_RUN=true" in noi_dung


@pytest.mark.parametrize("gia_tri", [
    "co khoang trang",
    "xuong\ndong",
    "tab\tgiua",
    '"co-dau-nhay"',
    "'nhay-don'",
    "x" * 501,
])
def test_khoa_dan_hong_bi_tu_choi(env, gia_tri):
    """Dan nham ca dong hoac ca doan van la loi thuong gap nhat khi copy khoa.
    Bat o day de nguoi dung biet ngay, thay vi doi san bao 'invalid signature'
    giua mot phien chay."""
    assert env_store.kiem_tra_bi_mat("OKX_API_KEY", gia_tri)


def test_ly_do_tu_choi_khong_duoc_nhac_lai_khoa(env):
    """Thong bao loi di vao log trinh duyet - nhac lai khoa o do la dung cai
    ro ri ma thiet ke nay dung de chan."""
    ly_do = env_store.kiem_tra_bi_mat("OKX_API_KEY", "khoa that nhung co khoang trang")
    assert ly_do and "khoa that" not in ly_do


def test_ghi_bi_mat_tu_choi_khoa_khong_bi_mat(env):
    """Hai duong ghi tach bach: khoa thuong khong duoc di vao duong khong-log."""
    kq = env_store.ghi_bi_mat({"DRY_RUN": "false"})
    assert kq["ok"] is False
    assert "DRY_RUN=true" in env.read_text(encoding="utf-8")


def test_ghi_thuong_van_khong_dung_duoc_vao_khoa_bi_mat(env):
    """Chieu con lai: `ghi` van phai tu choi khoa bi mat nhu truoc."""
    kq = env_store.ghi({"OKX_API_SECRET": "thu_di_duong_vong"})
    assert kq["ok"] is False
    assert "OKX_API_SECRET" not in env.read_text(encoding="utf-8")


def test_mot_khoa_bi_mat_sai_thi_khong_khoa_nao_duoc_ghi(env):
    kq = env_store.ghi_bi_mat({"OKX_API_KEY": "hop-le",
                               "OKX_API_SECRET": "co khoang trang"})
    assert kq["ok"] is False
    assert "OKX_API_KEY" not in env.read_text(encoding="utf-8")


def test_doc_bi_mat_noi_bo_tra_gia_tri_that(env):
    """Duong DUY NHAT doc duoc gia tri - va no khong duoc noi voi HTTP."""
    bm = env_store.doc_bi_mat_cho_tien_trinh_nay()
    assert bm["BYBIT_API_SECRET"] == "bi_mat_khong_duoc_lo"
    assert bm["OKX_API_KEY"] == ""


# ==========================================================
# Route: dat khoa va thu ket noi san
# ==========================================================
@pytest.fixture
def web(env, monkeypatch):
    from webui import app as app_mod
    app_mod.app.config["TESTING"] = True
    return app_mod


def test_route_dat_khoa_khong_vong_gia_tri_ve(web, env):
    r = web.app.test_client().post("/api/config/bi-mat",
                                   json={"thay_doi": {"OKX_API_KEY": "khoa-vua-dan"}})
    assert r.status_code == 200
    assert "khoa-vua-dan" not in r.get_data(as_text=True)
    assert "OKX_API_KEY=khoa-vua-dan" in env.read_text(encoding="utf-8")


def test_route_dat_khoa_tu_choi_khoa_thuong(web, env):
    r = web.app.test_client().post("/api/config/bi-mat",
                                   json={"thay_doi": {"SYMBOLS": "BTCUSDT"}})
    assert r.status_code == 400


def test_khong_route_nao_tra_ve_gia_tri_khoa(web, env):
    """Quet ca hai route cau hinh: khoa that nam trong .env cua fixture, va
    khong duoc xuat hien o bat ky phan hoi nao."""
    c = web.app.test_client()
    for duong in ("/api/config", "/api/status"):
        assert "bi_mat_khong_duoc_lo" not in c.get(duong).get_data(as_text=True)


class _ClientGia:
    """Dong vai san: khong cham mang."""
    def __init__(self, gia=None, von=None, loi_gia=None, loi_von=None):
        self._gia, self._von = gia, von
        self._loi_gia, self._loi_von = loi_gia, loi_von

    def get_last_price(self, ma):
        if self._loi_gia:
            raise self._loi_gia
        return self._gia

    def kiem_tra_ket_noi(self):
        if self._loi_von:
            raise self._loi_von
        if self._von is None:
            return {"ok": False, "chi_tiet": "khoa dung nhung tai khoan khong tra ve du lieu so du"}
        return {"ok": True, "chi_tiet": "so du %.2f USDT" % self._von}


def test_kiem_tra_san_bao_ca_hai_buoc_khi_dat(web, env, monkeypatch):
    env.write_text("EXCHANGE=okx\nOKX_API_KEY=k\nOKX_API_SECRET=s\n"
                   "OKX_API_PASSPHRASE=p\nOKX_DEMO=true\n", encoding="utf-8")
    monkeypatch.setattr(web, "build_client",
                        lambda cfg: _ClientGia(gia=64000.0, von=1234.5))
    d = web.app.test_client().post("/api/san/kiem-tra", json={}).get_json()
    assert d["san"] == "okx"
    assert d["cong_khai"]["ok"] is True
    assert d["rieng_tu"]["ok"] is True
    assert "1234.50" in d["rieng_tu"]["chi_tiet"]


def test_kiem_tra_san_tach_loi_mang_khoi_loi_khoa(web, env, monkeypatch):
    """Cong khai OK ma rieng tu hong = van de o KHOA, khong phai o mang. Hai
    huong sua khac han nhau nen UI phai phan biet duoc."""
    env.write_text("EXCHANGE=okx\nOKX_API_KEY=k\nOKX_API_SECRET=s\n"
                   "OKX_API_PASSPHRASE=p\n", encoding="utf-8")
    monkeypatch.setattr(web, "build_client",
                        lambda cfg: _ClientGia(gia=64000.0,
                                               loi_von=RuntimeError("60006 invalid sign")))
    d = web.app.test_client().post("/api/san/kiem-tra", json={}).get_json()
    assert d["cong_khai"]["ok"] is True
    assert d["rieng_tu"]["ok"] is False
    assert "invalid sign" in d["rieng_tu"]["chi_tiet"]


def test_kiem_tra_san_bao_ro_khoa_nao_con_thieu(web, env, monkeypatch):
    """OKX can passphrase ma Bybit khong - thieu no thi phai goi ten no ra."""
    env.write_text("EXCHANGE=okx\nOKX_API_KEY=k\nOKX_API_SECRET=s\n", encoding="utf-8")
    monkeypatch.setattr(web, "build_client", lambda cfg: _ClientGia(gia=64000.0))
    d = web.app.test_client().post("/api/san/kiem-tra", json={}).get_json()
    assert d["rieng_tu"]["ok"] is False
    assert "OKX_API_PASSPHRASE" in d["rieng_tu"]["chi_tiet"]


def test_kiem_tra_san_doc_khoa_VUA_GHI_chu_khong_phai_ban_da_nap(web, env, monkeypatch):
    """config.py goi load_dotenv() mot lan luc import. Neu route doc ban da nap
    thi nguoi dung vua dan khoa xong bam thu se bi bao 'chua co khoa' - dung
    vao luc ho vua dat khoa. Day la ly do `_CauHinhVuaDoc` ton tai."""
    env.write_text("EXCHANGE=okx\n", encoding="utf-8")
    c = web.app.test_client()
    c.post("/api/config/bi-mat", json={"thay_doi": {
        "OKX_API_KEY": "k", "OKX_API_SECRET": "s", "OKX_API_PASSPHRASE": "p"}})
    monkeypatch.setattr(web, "build_client", lambda cfg: _ClientGia(gia=1.0, von=0.0))
    d = c.post("/api/san/kiem-tra", json={}).get_json()
    assert d["rieng_tu"]["ok"] is True, d["rieng_tu"]["chi_tiet"]


def test_loi_ngan_xoa_khoa_lot_vao_thong_bao_loi(web, env):
    """Thu vien HTTP thinh thoang nhet ca header vao thong bao loi."""
    e = RuntimeError("401 unauthorized: apikey=bi_mat_khong_duoc_lo")
    s = web._loi_ngan(e)
    assert "bi_mat_khong_duoc_lo" not in s
    assert "***" in s


# ==========================================================
# Chon san
# ==========================================================
class _ClientCoViThe(_ClientGia):
    def __init__(self, vi_the=(), lenh=()):
        super().__init__(gia=1.0, von=1.0)
        self._vi_the, self._lenh = list(vi_the), list(lenh)

    def get_open_positions(self):
        return self._vi_the

    def get_open_orders(self):
        return self._lenh


def test_api_san_bao_ca_hai_san_chu_khong_rieng_san_dang_chon(web, env):
    """Cau hoi that cua nguoi dung la 'doi sang OKX duoc chua', nen tra loi
    phai biet khoa OKX da co hay chua NGAY CA KHI dang chay Bybit."""
    env.write_text("EXCHANGE=bybit\nOKX_API_KEY=k\nOKX_API_SECRET=s\n"
                   "OKX_API_PASSPHRASE=p\n", encoding="utf-8")
    d = web.app.test_client().get("/api/san").get_json()
    assert d["dang_chon"] == "bybit"
    assert d["san"]["okx"]["san_sang"] is True
    assert d["san"]["bybit"]["san_sang"] is False


def test_api_san_khong_lo_gia_tri_khoa(web, env):
    assert "bi_mat_khong_duoc_lo" not in web.app.test_client().get("/api/san").get_data(as_text=True)


def test_doi_san_ghi_vao_env(web, env):
    env.write_text("EXCHANGE=bybit\n", encoding="utf-8")
    d = web.app.test_client().post("/api/san/chon", json={"san": "okx"}).get_json()
    assert d["ok"] is True and d["da_doi"] is True
    assert "EXCHANGE=okx" in env.read_text(encoding="utf-8")


def test_doi_sang_chinh_no_thi_khong_ghi_gi(web, env):
    env.write_text("EXCHANGE=bybit\n", encoding="utf-8")
    d = web.app.test_client().post("/api/san/chon", json={"san": "bybit"}).get_json()
    assert d["da_doi"] is False


def test_san_la_bi_tu_choi(web, env):
    r = web.app.test_client().post("/api/san/chon", json={"san": "binance"})
    assert r.status_code == 400


def test_khong_co_khoa_thi_doi_san_thang(web, env):
    """Khong co khoa thi khong the co vi the nao de bo roi - dung hoi han."""
    env.write_text("EXCHANGE=bybit\n", encoding="utf-8")
    r = web.app.test_client().post("/api/san/chon", json={"san": "okx"})
    assert r.status_code == 200


def test_con_vi_the_tren_san_cu_thi_chan_lai(web, env, monkeypatch):
    """Diem quan trong nhat cua ca bang chon san.

    reconcile() chi doc vi the tu san dang cau hinh, khong doi chieu voi mot so
    sach rieng. Doi san khi con vi the tren san cu thi vong sau bot thay 'khong
    co vi the nao' va chay tiep - con vi the kia nam lai khong ai quan stop.
    Bot khong bao loi, vi theo goc nhin moi cua no thi khong co gi sai.
    """
    env.write_text("EXCHANGE=bybit\nBYBIT_API_KEY=k\nBYBIT_API_SECRET=s\n", encoding="utf-8")
    monkeypatch.setattr(web, "build_client",
                        lambda cfg: _ClientCoViThe(vi_the=[{"symbol": "BTCUSDT"}]))
    r = web.app.test_client().post("/api/san/chon", json={"san": "okx"})
    assert r.status_code == 409
    assert r.get_json()["can_xac_nhan"] is True
    assert "EXCHANGE=bybit" in env.read_text(encoding="utf-8")     # chua doi gi


def test_xac_nhan_roi_thi_van_doi_duoc(web, env, monkeypatch):
    """Canh bao chu khong phai cam: nguoi dung co the da dong tay tren san."""
    env.write_text("EXCHANGE=bybit\nBYBIT_API_KEY=k\nBYBIT_API_SECRET=s\n", encoding="utf-8")
    monkeypatch.setattr(web, "build_client",
                        lambda cfg: _ClientCoViThe(vi_the=[{"symbol": "BTCUSDT"}]))
    r = web.app.test_client().post("/api/san/chon", json={"san": "okx", "xac_nhan": True})
    assert r.status_code == 200
    assert "EXCHANGE=okx" in env.read_text(encoding="utf-8")


def test_lenh_cho_cung_duoc_tinh_la_vuong_mac(web, env, monkeypatch):
    env.write_text("EXCHANGE=bybit\nBYBIT_API_KEY=k\nBYBIT_API_SECRET=s\n", encoding="utf-8")
    monkeypatch.setattr(web, "build_client", lambda cfg: _ClientCoViThe(lenh=[{"id": 1}]))
    r = web.app.test_client().post("/api/san/chon", json={"san": "okx"})
    assert r.status_code == 409
    assert "lenh cho" in " ".join(r.get_json()["vuong_mac"])


def test_khong_doc_duoc_san_thi_khong_chan(web, env, monkeypatch):
    """Chan bang mot loi mang chi khien nguoi dung bam 'xac nhan' theo phan xa,
    lam hong dung cai canh bao nay dung de bao ve."""
    env.write_text("EXCHANGE=bybit\nBYBIT_API_KEY=k\nBYBIT_API_SECRET=s\n", encoding="utf-8")
    def no(cfg):
        raise ConnectionError("mat mang")
    monkeypatch.setattr(web, "build_client", no)
    assert web.app.test_client().post("/api/san/chon", json={"san": "okx"}).status_code == 200


# ==========================================================
# Cau hinh doc lai tu .env, dung kieu
# ==========================================================
def test_status_theo_kip_env_vua_sua(web, env):
    """config.py goi load_dotenv() mot lan luc import. Neu /api/status doc ban
    da nap thi nguoi dung luu xong van thay gia tri cu - do la mot bao cao SAI,
    khong phai mot do tre: ho khong co cach nao biet cai nao dang dung."""
    c = web.app.test_client()
    c.post("/api/san/chon", json={"san": "okx"})
    assert c.get("/api/status").get_json()["cau_hinh"]["exchange"] == "okx"


@pytest.mark.parametrize("gia_tri,mau,mong_doi", [
    ("true", False, True),
    ("no", True, False),
    ("BTCUSDT,ETHUSDT", [], ["BTCUSDT", "ETHUSDT"]),
    ("BTCUSDT, ETHUSDT ", [], ["BTCUSDT", "ETHUSDT"]),
    ("0.01", 0.5, 0.01),
    ("240", 60, 240),
    ("shadow", "off", "shadow"),
])
def test_ep_kieu_theo_dung_kieu_trong_config(web, gia_tri, mau, mong_doi):
    """Kieu hong o day khong bao loi ma di tiep: len() tren mot chuoi van chay,
    chi la tra ve so KY TU thay vi so ma."""
    assert web._ep_kieu(gia_tri, mau) == mong_doi


def test_ep_kieu_bool_truoc_int(web):
    """isinstance(True, int) la True trong Python - kiem sai thu tu thi
    BYBIT_TESTNET=true thanh int('true') va no ham."""
    assert web._ep_kieu("true", False) is True


def test_so_hong_trong_env_khong_lam_no_bang_dieu_khien(web):
    assert web._ep_kieu("khong-phai-so", 0.5) == 0.5


def test_exchange_luon_duoc_chuan_hoa(web, env):
    """config.py chuan hoa khoa nay luc nap; .env sua tay co the con 'OKX '."""
    env.write_text("EXCHANGE=  OKX \n", encoding="utf-8")
    assert web._CauHinhVuaDoc().EXCHANGE == "okx"


# ==========================================================
# Bo loc meta trong bang dieu khien
# ==========================================================
def test_run_meta_nam_trong_danh_sach_trang():
    jobs._kiem_tra_script("run_meta.py")


def test_route_meta_ton_tai():
    from webui.app import app
    co = {r.rule for r in app.url_map.iter_rules()}
    for r in ("/api/meta", "/api/meta/the/<phien_ban>",
              "/api/meta/thang-cap", "/api/meta/ha-cap"):
        assert r in co, "thieu route %s" % r


def test_meta_va_policy_dung_kho_khac_nhau():
    """Hai loai mo hinh tra loi hai cau hoi khac han. Gop chung mot thu muc thi
    mot lan thang cap ben nay se am tham go champion cua ben kia."""
    from src.meta_continual import KhoMeta
    from webui.app import MODEL_DIR
    assert KhoMeta().thu_muc != MODEL_DIR


def test_seeds_chi_nhan_so(monkeypatch):
    """Tham so nay di thang vao dong lenh."""
    from webui import app as webui_app
    for vao, ra in [("0,1,2", "0,1,2"), ("1;rm -rf /", "0"), ("", "0"),
                    ("0,1,2,3,4,5,6", "0,1,2,3,4")]:
        monkeypatch.setattr(webui_app, "_json", lambda v=vao: {"seeds": v})
        assert webui_app._seeds() == ra


def test_chien_luoc_meta_chi_nhan_ten_da_biet(monkeypatch):
    from webui import app as webui_app
    monkeypatch.setattr(webui_app, "_json",
                        lambda: {"chien_luoc": "breakout,khong_ton_tai,../etc"})
    assert webui_app._chien_luoc_meta() == "breakout"


# ==========================================================
# Bo nho dem so nen (_cache_files) - toi uu hoa 2026-09-11
#
# /api/status duoc bang goi moi 6 giay. Truoc ban va, ham nay doc lai TOAN BO
# noi dung moi tep CSV trong cache moi lan goi - 85ms tren 39 MB / 72 tep, gan
# het thoi gian cua ca endpoint, chi de hien mot con so hau nhu khong doi giua
# hai lan tai du lieu.
# ==========================================================
def test_dem_nen_dung_bo_nho_cho_lan_goi_thu_hai(tmp_path, monkeypatch):
    from webui import app as webui_app

    tep = tmp_path / "BTCUSDT_240.csv"
    tep.write_text("timestamp,close\n1,1\n2,2\n3,3\n", encoding="utf-8")
    monkeypatch.setattr(webui_app, "_DEM_NEN", {})

    assert webui_app._so_nen(str(tep)) == 3

    # Sua tep BANG TAY - khong qua ham nay - roi kiem tra bo nho co bi qua mat
    # hay khong bang cach doc lai gia tri no tra ve, khong doc noi dung tep.
    with tep.open("a", encoding="utf-8") as f:
        f.write("4,4\n")
    # Chua cham mtime/size trong bo nho -> van tra ve gia tri CU (dung thiet ke:
    # bo nho chi lam moi khi (mtime, size) doi, va ghi them trong cung mot lan
    # goi open() nhu tren luon doi ca hai nen truong hop nay thuc ra kiem tra
    # dung con duong "da doi thi doc lai".
    assert webui_app._so_nen(str(tep)) == 4


def test_dem_nen_tep_khong_doi_thi_khong_doc_lai_dia(tmp_path, monkeypatch):
    from webui import app as webui_app

    tep = tmp_path / "ETHUSDT_240.csv"
    tep.write_text("timestamp,close\n1,1\n2,2\n", encoding="utf-8")
    monkeypatch.setattr(webui_app, "_DEM_NEN", {})
    webui_app._so_nen(str(tep))

    da_mo = []
    that = open

    def theo_doi(p, *a, **k):
        da_mo.append(p)
        return that(p, *a, **k)

    monkeypatch.setattr("builtins.open", theo_doi)
    assert webui_app._so_nen(str(tep)) == 2
    assert str(tep) not in da_mo, "tep khong doi ma van bi mo lai"


def test_dem_nen_tra_ve_dung_gia_tri_thuc(tmp_path, monkeypatch):
    """Toi uu hoa khong duoc lam sai ket qua - day la dieu kien tien quyet."""
    from webui import app as webui_app

    tep = tmp_path / "SOLUSDT_240.csv"
    tep.write_text("timestamp,close\n" + "1,1\n" * 37, encoding="utf-8")
    monkeypatch.setattr(webui_app, "_DEM_NEN", {})
    assert webui_app._so_nen(str(tep)) == 37


def test_cache_files_bo_tep_da_bi_xoa_khoi_bo_nho(tmp_path, monkeypatch):
    """Tep xoa khoi dia thi phai bien khoi bo nho, khong duoc phinh mai."""
    from webui import app as webui_app

    tep = tmp_path / "BNBUSDT_240.csv"
    tep.write_text("timestamp,close\n1,1\n", encoding="utf-8")
    monkeypatch.setattr(webui_app, "_DEM_NEN", {})
    monkeypatch.setattr(webui_app.config, "CACHE_DIR", str(tmp_path))

    webui_app._cache_files()
    assert str(tep) in webui_app._DEM_NEN

    tep.unlink()
    webui_app._cache_files()
    assert str(tep) not in webui_app._DEM_NEN


def test_cache_files_tep_khong_doc_duoc_thi_tra_ve_0_khong_sap():
    from webui import app as webui_app
    assert webui_app._so_nen("/duong/dan/khong/ton/tai.csv") == 0
