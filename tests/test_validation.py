"""
Kiem tra lop chia du lieu chong ro ri.

Bo test nay quan trong hon phan con lai cua vong hoc. Mot mo hinh ro ri khong
bao gio bao loi - no chi cho ra so lieu dep roi thua tien that. Cach duy nhat
biet duoc bo chan ro ri con hoat dong la CO Y ban ro ri vao va bat no phai keu.

Vi vay o day co ca hai chieu:
  - test khang dinh: chia dung thi khong bao loi
  - test phu dinh: chia sai (tat purge, xoa embargo) thi PHAI bao loi
Mot bo test khong the that bai thi khong chung minh duoc dieu gi.
"""
import numpy as np
import pandas as pd
import pytest

from src import validation as v


def _panel(so_moc=100, so_ma=3, bars_held=5):
    """Panel gia lap: moi moc thoi gian co `so_ma` dong."""
    dong = []
    for i in range(so_moc):
        for m in range(so_ma):
            dong.append({"timestamp": 1_000_000 + i * 60_000,
                         "symbol": "MA%d" % m,
                         "bars_held": bars_held,
                         "x": float(i)})
    return v.them_vi_tri(pd.DataFrame(dong))


# ==========================================================
# Chia cua so
# ==========================================================
def test_cua_so_co_dung_khoang_embargo():
    khoi = list(v.chia_walkforward(1000, train_bars=500, test_bars=100, embargo=30))
    assert khoi[0].train_hi == 500
    assert khoi[0].test_lo == 530          # 500 + embargo
    assert khoi[0].test_hi == 630
    # Cua so ke tiep truot di dung mot do dai test
    assert khoi[1].train_hi == 600


def test_mo_rong_thi_train_luon_bat_dau_tu_0():
    truot = list(v.chia_walkforward(1000, 400, 100, 20, mo_rong=False))
    rong = list(v.chia_walkforward(1000, 400, 100, 20, mo_rong=True))
    assert truot[2].train_lo > 0
    assert all(k.train_lo == 0 for k in rong)


def test_khong_du_du_lieu_thi_khong_sinh_cua_so_nao():
    assert list(v.chia_walkforward(100, 500, 100, 30)) == []


def test_tham_so_vo_ly_thi_bao_loi():
    with pytest.raises(ValueError):
        list(v.chia_walkforward(1000, 0, 100, 30))


def test_ba_khoi_xep_dung_thu_tu_va_co_hai_khoang_embargo():
    b = v.cat_ba_khoi(2000, calib_bars=300, val_bars=400, embargo=50)
    assert b is not None
    assert b.val_hi == 2000
    assert b.val_lo == 1600
    assert b.calib_hi == 1550        # embargo giua calib va val
    assert b.calib_lo == 1250
    assert b.train_hi == 1200        # embargo giua train va calib
    assert b.train_lo == 0


def test_ba_khoi_tu_choi_khi_lich_su_qua_ngan():
    assert v.cat_ba_khoi(600, 300, 400, 50) is None


def test_khoi_val_khong_huan_luyen_them_tren_calib():
    """Mo hinh duoc trien khai phai la DUNG mo hinh da duoc do.

    Neu vung train cua khoi val keo den het calib thi so lieu bao cao thuoc ve
    mot mo hinh khac voi mo hinh dem chay - kieu sai lech khong ai phat hien ra.
    """
    b = v.cat_ba_khoi(2000, 300, 400, 50)
    assert b.khoi_val().train_hi == b.train_hi
    assert b.khoi_val().train_hi < b.calib_lo


# ==========================================================
# Purge
# ==========================================================
def test_purge_bo_mau_co_nhan_cham_vao_vung_test():
    p = _panel(so_moc=100, so_ma=2, bars_held=5)
    khoi = v.KhoiChia(0, 0, 50, 55, 80)
    tr = v.lay_train(p, khoi)

    # Mau o moc 50-x voi bars_held=5 cham moc 55 = dau vung test -> phai bi loai
    assert tr["_i"].max() == 49        # trong vung train
    assert (tr["_i"] + tr["bars_held"]).max() < khoi.test_lo


def test_tap_train_da_purge_thi_kiem_tra_sach():
    p = _panel(so_moc=100, so_ma=2, bars_held=20)
    khoi = v.KhoiChia(0, 0, 50, 55, 80)
    tr = v.lay_train(p, khoi)
    te = v.lay_test(p, khoi)
    assert v.kiem_tra_khong_ro_ri(tr, te, khoi) == []


def test_ban_ro_ri_vao_thi_bo_kiem_tra_phai_keu():
    """Dua thang mot tap train CHUA purge vao - bo kiem tra phai bat duoc.

    Day la kieu ro ri xay ra that: khong ai co tinh tat purge, ma la ai do dung
    mot duong khac de cat du lieu (mot notebook, mot script nghien cuu) roi doi
    duong do vao vong huan luyen.
    """
    p = _panel(so_moc=100, so_ma=2, bars_held=20)
    khoi = v.KhoiChia(0, 0, 50, 55, 80)

    tr_ban = p[(p["_i"] >= 0) & (p["_i"] < 50)]        # cat tho, khong purge
    te = v.lay_test(p, khoi)
    loi = v.kiem_tra_khong_ro_ri(tr_ban, te, khoi)
    assert any("purge" in l for l in loi), loi


def test_thieu_cot_bars_held_thi_coi_la_khong_kiem_tra_duoc():
    """Khong co bars_held nghia la khong biet nhan keo dai bao xa - phai bao,
    khong duoc im lang coi nhu sach."""
    p = _panel(so_moc=100, so_ma=2, bars_held=20).drop(columns=["bars_held"])
    khoi = v.KhoiChia(0, 0, 50, 55, 80)
    loi = v.kiem_tra_khong_ro_ri(v.lay_train(p, khoi), v.lay_test(p, khoi), khoi)
    assert any("bars_held" in l for l in loi), loi


def test_vi_tri_dem_theo_nen_khong_theo_dong_panel():
    """Loi kinh dien: embargo=60 tren panel 21 ma chi bang 3 nen.

    them_vi_tri phai gan cung mot chi so cho moi dong tai cung mot moc.
    """
    p = _panel(so_moc=10, so_ma=21)
    assert len(p) == 210
    assert p["_i"].max() == 9
    assert (p.groupby("timestamp")["_i"].nunique() == 1).all()


# ==========================================================
# Trong so duy nhat
# ==========================================================
def test_mau_nam_mot_minh_co_do_duy_nhat_bang_1():
    w = v.trong_so_duy_nhat([0, 50], [0, 0], so_moc=100)
    assert w == pytest.approx([1.0, 1.0])


def test_ba_mau_trung_hoan_toan_thi_moi_cai_con_mot_phan_ba():
    w = v.trong_so_duy_nhat([10, 10, 10], [4, 4, 4], so_moc=100)
    assert w == pytest.approx([1 / 3, 1 / 3, 1 / 3])


def test_chong_lan_cang_nhieu_trong_so_cang_nho():
    it_chong = v.trong_so_duy_nhat(list(range(0, 100, 20)), [2] * 5, so_moc=100)
    nhieu_chong = v.trong_so_duy_nhat(list(range(0, 100)), [50] * 100, so_moc=150)
    assert it_chong.mean() > 0.9
    assert nhieu_chong.mean() < 0.1


def test_trong_so_tinh_rieng_tung_ma():
    """Hai ma tai cung moc la hai quan sat khac nhau, khong phai mot bi dem hai lan."""
    p = _panel(so_moc=50, so_ma=5, bars_held=0)
    w = v.trong_so_duy_nhat_panel(p, so_moc=50)
    # bars_held=0 va moi ma chi co mot mau moi moc -> tat ca deu duy nhat
    assert w == pytest.approx(np.ones(len(p)))


# ==========================================================
# IC va t-stat
# ==========================================================
def test_ic_do_cat_ngang_tung_moc_va_bo_moc_qua_it_ma():
    n_moc, n_ma = 20, 10
    ts = np.repeat(np.arange(n_moc), n_ma)
    rng = np.random.default_rng(0)
    thuc = rng.normal(size=n_moc * n_ma)
    chuoi = v.ic_theo_moc(thuc, thuc, ts, min_ma=8)        # du doan = thuc
    assert len(chuoi) == n_moc
    assert chuoi == pytest.approx(np.ones(n_moc))

    # Moc chi co 3 ma thi bo qua
    ts_it = np.repeat(np.arange(n_moc), 3)
    assert len(v.ic_theo_moc(thuc[:n_moc * 3], thuc[:n_moc * 3], ts_it, min_ma=8)) == 0


def test_t_stat_cua_nhieu_trang_gan_khong():
    rng = np.random.default_rng(1)
    assert abs(v.t_stat(rng.normal(size=500))) < 3.0


def test_t_stat_khong_du_mau_thi_tra_nan():
    assert np.isnan(v.t_stat(np.array([0.1, 0.2])))


# ==========================================================
# Hieu chinh tu tuong quan chuoi
# ==========================================================
def test_chuoi_doc_lap_thi_hai_cach_tinh_t_gan_bang_nhau():
    rng = np.random.default_rng(3)
    x = rng.normal(0.05, 1.0, size=1000)
    assert v.t_stat_newey_west(x, lag=20) == pytest.approx(v.t_stat(x), rel=0.35)


def test_chuoi_chong_lan_thi_t_tho_bi_thoi_phong_manh():
    """Mo phong dung cai bay cua nhan triple-barrier: mot chuoi IC trong do moi
    gia tri la trung binh truot cua 60 quan sat doc lap. So quan sat THUC nho
    hon 60 lan, va t-stat tho phai phong dai dieu do."""
    rng = np.random.default_rng(4)
    goc = rng.normal(0.05, 1.0, size=2000)
    chong_lan = np.convolve(goc, np.ones(60) / 60, mode="valid")

    t_tho = v.t_stat(chong_lan)
    t_nw = v.t_stat_newey_west(chong_lan, lag=60)
    assert t_tho > 3 * t_nw, "t tho (%.2f) phai bi thoi phong so voi NW (%.2f)" % (t_tho, t_nw)


def test_khong_co_hieu_ung_that_thi_ca_hai_cach_deu_khong_ket_luan():
    rng = np.random.default_rng(5)
    chong_lan = np.convolve(rng.normal(0.0, 1.0, size=3000), np.ones(60) / 60, mode="valid")
    assert abs(v.t_stat_newey_west(chong_lan, lag=60)) < 2.0


def test_lag_lon_hon_do_dai_chuoi_thi_khong_no():
    assert np.isfinite(v.t_stat_newey_west(np.array([0.1, 0.2, 0.3, 0.4]), lag=999))
