"""
Cham diem che do BONG - bien "da cho du lau" thanh "co bang chung".

VAN DE MA FILE NAY SUA:
Kho luat cho mot chien luoc len `chu_dong` khi no da o che do bong >= 14 ngay.
Nhung 14 ngay la THOI GIAN PHUC VU, khong phai ket qua. Kien truc v2 noi ro
"neu shadow mode VAN TOT thi moi them vao ensemble" - va truoc file nay khong
co gi do duoc chu "van tot" do. Mot che do bong khong duoc cham diem chi la
mot khoang cho, va no tao ra cam giac an toan ma khong tao ra bang chung.

CACH CHAM - giong het cach continual.py cham AI policy, co y de hai ben so
sanh duoc voi nhau:

  Ket qua tinh tu DU LIEU THI TRUONG bang triple-barrier, KHONG tu lenh cua
  bot. Chien luoc o che do bong khong dat lenh nao ca, nen day la cach duy
  nhat. Quan trong hon: barrier dung dung ATR_STOP_MULT/ATR_TP_MULT ma bot
  that dang dung, nen con so tra loi dung cau hoi "neu vao lenh luc do, voi
  chinh cai stop va chot lai cua bot, thi lai bao nhieu sau phi".

  Cham CA nhung tin hieu HOLD (chung duoc ghi va duoc dien ket qua), nhung
  ky vong moi lenh chi tinh tren BUY/SELL. Ghi ca HOLD de ho so khong bi
  thien lech chon mau; tinh ky vong tren rieng lenh that vi do moi la cau hoi.

DIEU CO Y KHONG LAM: khong tu dong thang cap khi diem dep. Diem chi mo cong;
buoc qua cong van la quyet dinh cua nguoi.
"""
import logging
import time
from typing import Dict, List

import config
from . import datafeed, indicators, labeling

logger = logging.getLogger(__name__)

# Toi thieu bao nhieu tin hieu DA CHAM truoc khi diem duoc coi la co nghia.
# Duoi muc nay, ky vong chi la nhieu: mot chuoi 5 lenh dep khong noi len gi.
SO_TIN_HIEU_TOI_THIEU = 20


def dien_ket_qua(storage, symbols: List[str] = None, interval: str = None,
                 cfg=config, max_horizon: int = 60) -> int:
    """Dien ket qua thuc cho cac tin hieu bong da du gia. Tra ve so ban ghi.

    "Du gia" nghia la da qua max_horizon nen ke tu luc co tin hieu - truoc do
    barrier chua nga ngu va cham diem se la doan.
    """
    interval = interval or cfg.KLINE_INTERVAL
    ms_moi_nen = int(interval) * 60_000 if str(interval).isdigit() else 86_400_000
    han = int(time.time() * 1000) - max_horizon * ms_moi_nen

    cho = storage.shadow_chua_co_ket_qua(han)
    if not cho:
        return 0

    theo_ma: Dict[str, List] = {}
    for r in cho:
        theo_ma.setdefault(r["symbol"], []).append(r)

    xong = 0
    for sym, rows in theo_ma.items():
        if symbols and sym not in symbols:
            continue
        df = datafeed.load_cache(sym, interval)
        if df is None or len(df) < 250:
            logger.warning("Chua co du cache gia cho %s - bo qua cham diem", sym)
            continue
        df = indicators.add_indicators(df)
        nhan = labeling.gan_nhan_hai_chieu(df, cfg, max_horizon)
        theo_ts = {int(t): i for i, t in enumerate(df["timestamp"].to_numpy())}

        for r in rows:
            i = theo_ts.get(int(r["bar_ts"]))
            if i is None or i >= len(nhan):
                continue
            if not bool(nhan["resolved"].iloc[i]):
                # Barrier chua nga ngu trong max_horizon nen - de lai cho vong
                # sau thay vi ghi mot con so nua voi.
                continue
            if r["action"] == "BUY":
                ret = float(nhan["ret_long"].iloc[i])
            elif r["action"] == "SELL":
                ret = float(nhan["ret_short"].iloc[i])
            else:
                # HOLD: ghi ket qua cua chieu mua lam moc tham chieu. Khong
                # tinh vao ky vong moi lenh, nhung giu lai de biet chien luoc
                # da bo qua nhung gi.
                ret = float(nhan["ret_long"].iloc[i])
            storage.cap_nhat_ket_qua_shadow(r["id"], ret)
            xong += 1

    if xong:
        logger.info("Da cham diem %d tin hieu che do bong", xong)
    return xong


def danh_gia(storage, ten: str, so_toi_thieu: int = None) -> Dict:
    """Cham mot chien luoc bong. Tra ve dict co `du_bang_chung` va `ly_do`.

    `du_bang_chung` la thu ma kho_luat.thang_cap doc de quyet dinh co cho len
    `chu_dong` khong. No doi HAI dieu, va ca hai deu can:

      1. Du SO TIN HIEU da cham. Ky vong tren 5 lenh khong phai bang chung.
      2. Ky vong moi lenh KHONG AM. Khong doi phai dep - chi doi la dung dau.
         Dat nguong cao hon o day se lap lai chinh cai bay ma Strategy Lab da
         tranh: chon cai dep nhat trong nhieu thu, tren mot mau nho.
    """
    so_toi_thieu = so_toi_thieu or SO_TIN_HIEU_TOI_THIEU
    d = storage.diem_shadow(ten)
    n = d["so_tin_hieu_da_cham"]
    ky_vong = d["ky_vong_moi_lenh"]

    if n < so_toi_thieu:
        d["du_bang_chung"] = False
        d["ly_do"] = ("moi co %d tin hieu da cham, can >= %d (%d tin hieu con "
                      "cho du gia)" % (n, so_toi_thieu, d["so_tin_hieu_cho_cham"]))
    elif ky_vong is None or ky_vong < 0:
        d["du_bang_chung"] = False
        d["ly_do"] = ("ky vong moi lenh %.4f%% - am sau phi. Chay bong lau hon "
                      "khong sua duoc mot bien do am."
                      % ((ky_vong or 0) * 100))
    else:
        d["du_bang_chung"] = True
        d["ly_do"] = ("%d tin hieu, ky vong %+.4f%% moi lenh sau phi"
                      % (n, ky_vong * 100))
    return d
