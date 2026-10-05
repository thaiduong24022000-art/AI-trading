"""
Chia du lieu chong ro ri - nen mong cua vong hoc lien tuc.

MOI THU KHAC TRONG VONG HOC DEU VO NGHIA NEU FILE NAY SAI.
Mot mo hinh ro ri khong bao gio bao loi. No chi cho ra so lieu dep, vuot moi
cong thong ke, roi thua tien that. Vi vay cac ham o day duoc viet de CO THE
THAT BAI mot cach on ao, va co bo test rieng ban chung ro ri vao de bat.

BA CO CHE:

1. PURGE - nhan triple-barrier mat nhieu nen moi nga ngu. Mot mau o cuoi vung
   train co the co nhan keo dai sang vung test: no "biet" mot phan tuong lai
   cua test. Phai loai bo moi mau co `vi_tri + bars_held >= test_lo`.

2. EMBARGO - sau khi purge van con tuong quan chuoi: nen ngay truoc test va nen
   dau test chia nhau gan het thong tin. Bo them mot khoang trong giua hai vung.

3. TRONG SO DUY NHAT - hai mau canh nhau voi max_horizon=60 trung nhau 98%
   khoang thoi gian. Chung gan nhu la CUNG mot quan sat duoc dem 60 lan. Dieu
   nay khong lam sai gia tri trung binh nhung thoi phong moi thuoc do do tin
   cay (t-stat, AUC std) rat manh. Trong so duy nhat cua Lopez de Prado ha
   trong so nhung mau bi trung lap, tra lai kich thuoc mau THUC.

MOT DIEU FILE NAY KHONG GIAI QUYET DUOC: tuong quan CAT NGANG. 21 dong coin
gan nhu cung mot tai san - 21 mau tai cung mot moc thoi gian khong phai 21
quan sat doc lap. Cach duy nhat dung la do IC tai TUNG moc thoi gian roi lay
t-stat tren chuoi IC (moi moc = 1 quan sat), khong bao gio lay t-stat tren
tung dong panel. Xem `ic_theo_moc()`.
"""
from dataclasses import dataclass
from typing import Iterator, List, Optional, Sequence

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class KhoiChia:
    """Mot cua so walk-forward, tinh theo CHI SO MOC THOI GIAN (khong phai dong panel)."""
    chi_so: int
    train_lo: int
    train_hi: int
    test_lo: int
    test_hi: int

    def __str__(self) -> str:
        return ("cua so %d: train[%d:%d] embargo[%d:%d] test[%d:%d]"
                % (self.chi_so, self.train_lo, self.train_hi,
                   self.train_hi, self.test_lo, self.test_lo, self.test_hi))


def chia_walkforward(so_moc: int, train_bars: int, test_bars: int, embargo: int,
                     mo_rong: bool = False) -> Iterator[KhoiChia]:
    """Sinh cac cua so truot.

    mo_rong=True: vung train lon dan tu moc 0 (dung cho hoc lien tuc - mo hinh
    duoc thay toan bo lich su den thoi diem do).
    mo_rong=False: cua so truot co dinh do dai (dung khi nghi rang thi truong
    doi che do va lich su qua xa gay nhieu hon la giup).
    """
    if min(train_bars, test_bars) <= 0 or embargo < 0:
        raise ValueError("train_bars/test_bars phai > 0 va embargo >= 0")

    k = 0
    start = 0
    while start + train_bars + embargo + test_bars <= so_moc:
        train_hi = start + train_bars
        test_lo = train_hi + embargo
        yield KhoiChia(chi_so=k,
                       train_lo=0 if mo_rong else start,
                       train_hi=train_hi,
                       test_lo=test_lo,
                       test_hi=test_lo + test_bars)
        start += test_bars
        k += 1


def cat_khoi_cuoi(so_moc: int, val_bars: int, embargo: int,
                  train_toi_thieu: int = 500) -> Optional[KhoiChia]:
    """Cat mot lan: toan bo lich su lam train, khoi MOI NHAT lam kiem dinh.

    Day la phep cat cua vong hoc lien tuc. Khoi kiem dinh phai la khoi GAN NHAT
    chu khong phai mot khoi ngau nhien giua lich su: cau hoi can tra loi la
    "mo hinh nay co con dung voi thi truong HIEN TAI khong", va thi truong gan
    nhat la mau duy nhat tra loi duoc cau do.
    """
    val_lo = so_moc - val_bars
    train_hi = val_lo - embargo
    if train_hi < train_toi_thieu:
        return None
    return KhoiChia(chi_so=0, train_lo=0, train_hi=train_hi,
                    test_lo=val_lo, test_hi=so_moc)


@dataclass(frozen=True)
class BaKhoi:
    """Train | embargo | HIEU CHUAN | embargo | KIEM DINH.

    VI SAO CAN KHOI HIEU CHUAN RIENG: policy can hai thu do tu du lieu - so vong
    lap toi uu cua LightGBM (early stopping) va bien do lai/lo de tinh EV. Neu
    lay ca hai tu khoi kiem dinh thi khoi do khong con la kiem dinh nua: ta da
    chinh mo hinh theo chinh cai thuoc do se dung de cham diem no, va con so cuoi
    cung se dep hon thuc te mot cach co he thong.

    Khoi hieu chuan nam GIUA train va kiem dinh, khong phai sau: no phai la qua
    khu doi voi khoi kiem dinh, giong nhu moi thu khac.
    """
    train_lo: int
    train_hi: int
    calib_lo: int
    calib_hi: int
    val_lo: int
    val_hi: int

    def __post_init__(self):
        """Ba khoi phai xep dung thu tu tren truc thoi gian.

        Kiem ngay luc dung chu khong phai luc dung: mot phep cat sai thu tu van
        chay duoc va van ra so lieu - purge o buoc sau co the tinh co che mat
        hau qua, nen khong co gi bao rang phep cat da sai. Cach duy nhat de dieu
        do khong troi qua im lang la khong cho tao ra doi tuong sai ngay tu dau.
        """
        moc = [("train_lo", self.train_lo), ("train_hi", self.train_hi),
               ("calib_lo", self.calib_lo), ("calib_hi", self.calib_hi),
               ("val_lo", self.val_lo), ("val_hi", self.val_hi)]
        for (ten_a, a), (ten_b, b) in zip(moc, moc[1:]):
            if a > b:
                raise ValueError("ba khoi sai thu tu thoi gian: %s=%d > %s=%d (%s)"
                                 % (ten_a, a, ten_b, b,
                                    " <= ".join("%s=%d" % m for m in moc)))
        if self.train_hi <= self.train_lo or self.calib_hi <= self.calib_lo \
                or self.val_hi <= self.val_lo:
            raise ValueError("co khoi rong: %s"
                             % " ".join("%s=%d" % m for m in moc))

    def khoi_calib(self) -> KhoiChia:
        """Train (da purge theo moc bat dau calib) + vung test la khoi calib."""
        return KhoiChia(0, self.train_lo, self.train_hi, self.calib_lo, self.calib_hi)

    def khoi_val(self) -> KhoiChia:
        """Cung vung train do + vung test la khoi kiem dinh.

        Vung train KHONG mo rong den het calib: mo hinh duoc trien khai phai la
        DUNG mo hinh da duoc do. Neu huan luyen lai tren train+calib de tan dung
        them du lieu thi so lieu tren the mo hinh khong con mo ta vat the that
        duoc dem chay - va do la kieu sai lech khong ai phat hien ra cho den khi
        no thua tien.
        """
        return KhoiChia(1, self.train_lo, self.train_hi, self.val_lo, self.val_hi)

    def __str__(self) -> str:
        return ("train[%d:%d] calib[%d:%d] val[%d:%d]"
                % (self.train_lo, self.train_hi, self.calib_lo, self.calib_hi,
                   self.val_lo, self.val_hi))


def cat_ba_khoi(so_moc: int, calib_bars: int, val_bars: int, embargo: int,
                train_toi_thieu: int = 500) -> Optional[BaKhoi]:
    """Cat lich su thanh train | calib | val, val la khoi MOI NHAT."""
    val_lo = so_moc - val_bars
    calib_hi = val_lo - embargo
    calib_lo = calib_hi - calib_bars
    train_hi = calib_lo - embargo
    if train_hi < train_toi_thieu or calib_lo <= 0:
        return None
    return BaKhoi(train_lo=0, train_hi=train_hi, calib_lo=calib_lo,
                  calib_hi=calib_hi, val_lo=val_lo, val_hi=so_moc)


def them_vi_tri(panel: pd.DataFrame, cot: str = "_i") -> pd.DataFrame:
    """Gan cho moi dong chi so MOC THOI GIAN cua no (0, 1, 2, ...).

    Purge va embargo dem theo NEN, khong theo dong panel: voi 21 ma thi mot moc
    thoi gian la 21 dong. Nham hai cai nay la loi kinh dien - embargo=60 dong
    tren panel 21 ma chi bang 3 nen, gan nhu khong embargo gi ca.
    """
    moc = np.sort(panel["timestamp"].unique())
    vi_tri = {t: k for k, t in enumerate(moc)}
    out = panel.copy()
    out[cot] = out["timestamp"].map(vi_tri).astype("int64")
    return out


def lay_train(panel: pd.DataFrame, khoi: KhoiChia, cot_vi_tri: str = "_i",
              cot_span: str = "bars_held") -> pd.DataFrame:
    """Vung train DA PURGE.

    Dieu kien giu lai: vi_tri + bars_held < test_lo, tuc nhan cua mau da nga ngu
    HOAN TOAN truoc khi vung test bat dau.
    """
    i = panel[cot_vi_tri]
    trong_vung = (i >= khoi.train_lo) & (i < khoi.train_hi)
    if cot_span in panel.columns:
        da_nga_ngu = (i + panel[cot_span].fillna(0).astype("int64")) < khoi.test_lo
        return panel[trong_vung & da_nga_ngu]
    return panel[trong_vung]


def lay_test(panel: pd.DataFrame, khoi: KhoiChia, cot_vi_tri: str = "_i") -> pd.DataFrame:
    i = panel[cot_vi_tri]
    return panel[(i >= khoi.test_lo) & (i < khoi.test_hi)]


def trong_so_duy_nhat(vi_tri: Sequence[int], bars_held: Sequence[int],
                      so_moc: int = None) -> np.ndarray:
    """Do duy nhat trung binh cua tung mau (Lopez de Prado).

    Voi moi nen t, do CHONG LAN = so mau co khoang nhan phu len t.
    Do duy nhat cua mau i = trung binh cua 1/chong_lan tren khoang nhan cua no.
    Mau nam mot minh -> 1.0. Mau nam giua 60 mau trung nhau -> ~1/60.

    Dung lam sample_weight khi huan luyen: mo hinh khong con bi 60 ban sao cua
    cung mot su kien keo lech. Day cung la kich thuoc mau THUC de bao cao -
    tong trong so, khong phai so dong.
    """
    p = np.asarray(vi_tri, dtype=np.int64)
    h = np.asarray(bars_held, dtype=np.int64)
    if len(p) == 0:
        return np.zeros(0)
    h = np.clip(h, 0, None)
    if so_moc is None:
        so_moc = int(max(p.max(), (p + h).max())) + 1
    ket = np.minimum(p + h, so_moc - 1)

    # Do chong lan bang mang sai phan: O(n) thay vi O(n * horizon)
    delta = np.zeros(so_moc + 1, dtype=np.int64)
    np.add.at(delta, p, 1)
    np.add.at(delta, ket + 1, -1)
    chong_lan = np.cumsum(delta[:so_moc])
    chong_lan = np.maximum(chong_lan, 1)

    # Tong tich luy cua 1/chong_lan de lay trung binh tren moi khoang trong O(1)
    nghich = 1.0 / chong_lan
    tich_luy = np.concatenate([[0.0], np.cumsum(nghich)])
    do_dai = (ket - p + 1).astype(float)
    return (tich_luy[ket + 1] - tich_luy[p]) / do_dai


def trong_so_duy_nhat_panel(df: pd.DataFrame, so_moc: int, cot_vi_tri: str = "_i",
                            cot_span: str = "bars_held",
                            cot_ma: str = "symbol") -> np.ndarray:
    """Trong so duy nhat tinh RIENG TUNG MA.

    Chong lan la khai niem trong MOT chuoi thoi gian. Hai ma khac nhau tai cung
    mot moc la hai quan sat khac nhau (do la be rong cat ngang - thu ta muon co),
    khong phai mot quan sat bi dem hai lan. Gop chung lai de dem chong lan se
    ha trong so cua chinh cai dang can.
    """
    w = np.ones(len(df), dtype=float)
    if cot_span not in df.columns or len(df) == 0:
        return w
    vi = df[cot_vi_tri].to_numpy()
    span = df[cot_span].to_numpy()
    for _, idx in df.groupby(cot_ma, sort=False).indices.items():
        idx = np.asarray(idx)
        w[idx] = trong_so_duy_nhat(vi[idx], span[idx], so_moc)
    return w


def chuan_hoa_trong_so(w: np.ndarray) -> np.ndarray:
    """Dua trung binh trong so ve 1.0, giu nguyen TY LE giua cac mau.

    VI SAO CAN: trong so duy nhat co gia tri quanh 1/60. Neu dua thang vao
    LightGBM thi tong hessian nho di khoang 60 lan, ma `lambda_l2` va
    `min_sum_hessian_in_leaf` lai la nguong TUYET DOI tren dai luong do - ket
    qua la mo hinh bi phat nang gap 60 lan so voi y dinh, va no dung hoc sau vai
    vong boosting. Trieu chung nay rat de doc nham thanh "du lieu khong co tin
    hieu", va do la ket luan sai nguy hiem nhat trong ca du an.

    Chuan hoa tach hai viec ra: TY LE giua cac mau van sua duoc thien lech do
    nhan chong lan, con DO LON tuyet doi khong con am tham doi cuong do dieu
    chuan. Kich thuoc mau hieu dung de bao cao van lay tu tong trong so THO.
    """
    w = np.asarray(w, dtype=float)
    tb = w.mean() if len(w) else 0.0
    return w / tb if tb > 0 else np.ones_like(w)


def ic_theo_moc(du_doan: np.ndarray, thuc: np.ndarray, ts: np.ndarray,
                min_ma: int = 8) -> np.ndarray:
    """Spearman CAT NGANG tai tung moc thoi gian -> tra ve chuoi IC.

    Tra ve CHUOI chu khong phai gia tri trung binh, vi t-stat phai tinh tren
    chuoi nay: moi moc thoi gian la mot quan sat. Lay t-stat tren tung dong
    panel se coi 21 ma tai cung mot moc la 21 quan sat doc lap - chung khong
    doc lap, va t-stat se bi thoi phong khoang can bac hai cua 21 lan.
    """
    from scipy import stats

    out: List[float] = []
    s = pd.Series(np.arange(len(ts)))
    nhom = s.groupby(ts).groups
    # Sap theo thoi gian: chuoi IC phai dung thu tu thi moi tinh duoc tu tuong
    # quan cua no, va do la thu `t_stat_newey_west` can den.
    for khoa in sorted(nhom):
        i = np.asarray(nhom[khoa])
        if len(i) < min_ma:
            continue
        a, b = du_doan[i], thuc[i]
        if np.std(a) == 0 or np.std(b) == 0:
            continue
        r = stats.spearmanr(a, b).statistic
        if np.isfinite(r):
            out.append(float(r))
    return np.asarray(out)


def t_stat(v: np.ndarray) -> float:
    """t-stat THO - gia dinh cac quan sat doc lap.

    Chi dung khi da biet chac chuoi khong tu tuong quan. Voi chuoi IC theo thoi
    gian sinh ra tu nhan triple-barrier thi gia dinh do SAI - dung
    `t_stat_newey_west` thay vao do.
    """
    v = np.asarray(v, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) < 3:
        return float("nan")
    sd = v.std(ddof=1)
    if sd == 0:
        return float("nan")
    return float(v.mean() / (sd / np.sqrt(len(v))))


def t_stat_newey_west(v: np.ndarray, lag: int) -> float:
    """t-stat da hieu chinh tu tuong quan chuoi (Newey-West).

    VI SAO BAT BUOC PHAI CO: chuoi IC duoc tinh tai TUNG nen, nhung nhan
    triple-barrier keo dai toi max_horizon nen. Hai moc canh nhau dung chung
    gan het khoang thoi gian tuong lai - chung khong phai hai quan sat doc lap.
    Cong thuc t thong thuong gia dinh doc lap, nen tren chuoi nay no thoi phong
    t-stat khoang can bac hai cua do dai chong lan: t=7 co the thuc chat la
    t=0.9, tuc khong co gi.

    Day chinh la cai bay da lam hong ket qua nghien cuu truoc do cua du an:
    decile spread trong nhu co tin hieu (t = 2.15-3.02) nhung sup xuong am khi
    lay mau roi nhau. Bo trong so lag tuyen tinh (Bartlett) sua dieu do ma van
    dung duoc toan bo du lieu, thay vi vut di 59/60 so quan sat.
    """
    v = np.asarray(v, dtype=float)
    v = v[np.isfinite(v)]
    n = len(v)
    lag = max(0, min(int(lag), n - 2))
    if n < 3:
        return float("nan")

    lech = v - v.mean()
    gamma0 = float(np.dot(lech, lech) / n)
    if gamma0 <= 0:
        return float("nan")

    tong = gamma0
    for k in range(1, lag + 1):
        gamma_k = float(np.dot(lech[k:], lech[:-k]) / n)
        tong += 2.0 * (1.0 - k / (lag + 1.0)) * gamma_k

    # Tu tuong quan am manh co the day tong xuong <= 0; luc do khong ket luan duoc.
    if tong <= 0:
        return float("nan")
    return float(v.mean() / np.sqrt(tong / n))


def kiem_tra_khong_ro_ri(tr: pd.DataFrame, te: pd.DataFrame, khoi: KhoiChia,
                         cot_vi_tri: str = "_i", cot_span: str = "bars_held") -> List[str]:
    """Soi HAI TAP DU LIEU THAT sap duoc dua vao mo hinh. Rong = sach.

    Nhan vao tr/te da dung chu khong tu dung lai chung tu panel. Day khong phai
    chi tiet phong cach: mot ham tu tao lay dau vao cua minh bang chinh cai logic
    no dinh kiem tra thi khong bao gio that bai duoc - no chi khang dinh rang
    purge da purge. Nhan tap that vao thi no bat duoc ca truong hop nguoi goi
    dung mot duong khac de dung tap train, va do moi la kieu ro ri xay ra trong
    thuc te.

    Goi truoc MOI lan huan luyen. Re hon nhieu so voi viec phat hien ro ri sau
    khi da dua mo hinh len chay that.
    """
    loi: List[str] = []
    if len(tr) == 0 or len(te) == 0:
        loi.append("vung train hoac test rong")
        return loi

    if tr[cot_vi_tri].max() >= khoi.test_lo:
        loi.append("mau train nam trong vung test")
    if cot_span in tr.columns:
        cham = int((tr[cot_vi_tri] + tr[cot_span].fillna(0)).max())
        if cham >= khoi.test_lo:
            loi.append("nhan train keo dai sang test (purge that bai): "
                       "cham moc %d, test bat dau %d" % (cham, khoi.test_lo))
    else:
        loi.append("tap train khong co cot '%s' - khong kiem tra purge duoc" % cot_span)
    if khoi.test_lo - int(tr[cot_vi_tri].max()) - 1 < 0:
        loi.append("train va test chong nhau")
    if te[cot_vi_tri].min() < khoi.test_lo or te[cot_vi_tri].max() >= khoi.test_hi:
        loi.append("vung test ra ngoai bien")
    return loi
