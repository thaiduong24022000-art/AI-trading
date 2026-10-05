"""
Lop suy luan cua AI policy - bien hai xac suat thanh LONG / SHORT / HOLD.

CACH RA QUYET DINH (khong co nguong tu chon tay):
  Hai mo hinh LightGBM tra loi hai cau hoi RIENG BIET:
      p_long  = P(vao lenh MUA o day thi ket qua rong > 0)
      p_short = P(vao lenh BAN o day thi ket qua rong > 0)
  Hai cau nay khong bu tru nhau: voi stop 2xATR va TP 3xATR, phan lon thoi diem
  ca hai deu la lenh xau. Do chinh la ly do phai co HOLD nhu mot lua chon thu ba
  chu khong phai la "vung giua" cua mot truc long-short.

  Ky vong loi nhuan:  EV = p * lai_trung_binh + (1 - p) * lo_trung_binh
  Hai so lai/lo trung binh KHONG duoc dat tay - chung do tren khoi kiem dinh va
  luu trong meta cua mo hinh. Nho vay nguong quyet dinh la EV > 0 (cong mot bien
  an toan), mot dai luong co nghia kinh te, thay vi mot con so p tuy chon ma moi
  lan mo hinh doi lai phai chinh lai.

TRIET LY: MAC DINH LA HOLD.
Moi tinh huong khong chac chan deu tra ve HOLD, khong bao gio nem ngoai le len
vong lap giao dich. Danh sach truong hop tu choi nam trong `_ly_do_tu_choi()` -
doc no truoc khi sua bat cu gi o day. Mot bug o lop nay khong lam bot dung, no
lam bot vao lenh dua tren rac; do la kieu hong nguy hiem nhat.

VI TRI TRONG KIEN TRUC: policy la mot NGUON TIN HIEU, ngang hang voi cac chien
luoc luat. No khong tu dat lenh, khong tu tinh khoi luong, khong duoc phep bo
qua RiskManager hay circuit breaker. Duong di khong doi:
    policy -> ensemble -> allocator -> LLM veto -> risk engine -> executor
"""
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import config
from . import model_store
from .strategies.base import BUY, HOLD, SELL

logger = logging.getLogger(__name__)

# Cac che do trien khai, xep theo muc do duoc phep anh huong den lenh that.
TAT = "off"          # khong nap mo hinh
BONG = "shadow"      # co du doan, co ghi log, KHONG anh huong quyet dinh
LOC = "filter"       # chi duoc CHAN hoac GIAM quy mo tin hieu cua chien luoc luat
CHU_DONG = "active"  # duoc phat tin hieu nhu mot chien luoc binh thuong
CAC_CHE_DO = (TAT, BONG, LOC, CHU_DONG)


@dataclass
class KetQuaPolicy:
    action: str = HOLD
    strength: float = 0.0
    p_long: float = float("nan")
    p_short: float = float("nan")
    ev_long: float = float("nan")
    ev_short: float = float("nan")
    phien_ban: str = ""
    ly_do: str = ""
    co_y_kien: bool = False      # False = policy khong danh gia duoc, khong phai "khuyen HOLD"
    dac_trung: Dict[str, float] = field(default_factory=dict)

    def tom_tat(self) -> str:
        if not self.co_y_kien:
            return "policy: khong y kien (%s)" % self.ly_do
        return ("policy[%s]: %s manh %.2f | p_long=%.3f EV=%.4f | p_short=%.3f EV=%.4f"
                % (self.phien_ban, self.action, self.strength,
                   self.p_long, self.ev_long, self.p_short, self.ev_short))


class MLPolicy:
    """Boc mo hinh champion. An toan khi khong co mo hinh nao."""

    def __init__(self, cfg=config, kho: model_store.KhoModel = None):
        self.cfg = cfg
        self.kho = kho or model_store.KhoModel()
        self.mo_hinh: Optional[model_store.MoHinhPolicy] = None
        self._van_tay_loi: Optional[str] = None
        self._mtime_champion: float = 0.0
        self.nap_lai()

    # ---------- vong doi mo hinh ----------
    def nap_lai(self) -> bool:
        """Nap champion hien tai. Tra ve True neu dang co mo hinh dung duoc."""
        self.mo_hinh = None
        self._van_tay_loi = None
        if getattr(self.cfg, "POLICY_MODE", TAT) == TAT:
            return False
        try:
            mh = self.kho.nap_champion()
        except Exception as e:                       # nap mo hinh khong duoc lam sap bot
            logger.error("Loi nap champion: %s", e)
            return False
        if mh is None:
            logger.info("Policy: chua co champion - bot chay thuan chien luoc luat")
            return False

        lech = mh.hop_le_voi(self.cfg)
        if lech:
            # Khong tu dong bo qua: mo hinh nay hoc mot bai toan khac voi bai
            # toan dang chay. Dung no la du doan sai mot cach co he thong.
            self._van_tay_loi = lech
            logger.error("Policy TU CHOI mo hinh %s: %s", mh.phien_ban, lech)
            return False

        self.mo_hinh = mh
        p = os.path.join(self.kho.thu_muc, "champion.json")
        self._mtime_champion = os.path.getmtime(p) if os.path.exists(p) else 0.0
        logger.info("Policy nap champion %s (%d dac trung, huan luyen %s)",
                    mh.phien_ban, len(mh.cot_dac_trung),
                    mh.meta.get("huan_luyen_luc", "?"))
        return True

    def kiem_tra_champion_moi(self) -> bool:
        """Goi moi vong: neu champion vua doi (thang cap hoac ha cap) thi nap lai.

        Nho vay vong hoc chay o tien trinh khac co the thay mo hinh ma khong can
        khoi dong lai bot - va viec ha cap khan cap co hieu luc ngay vong sau.
        """
        p = os.path.join(self.kho.thu_muc, "champion.json")
        mtime = os.path.getmtime(p) if os.path.exists(p) else 0.0
        if mtime != self._mtime_champion:
            logger.warning("Phat hien champion thay doi - nap lai")
            self._mtime_champion = mtime
            return self.nap_lai()
        return self.mo_hinh is not None

    @property
    def san_sang(self) -> bool:
        return self.mo_hinh is not None

    @property
    def che_do(self) -> str:
        return getattr(self.cfg, "POLICY_MODE", TAT)

    # ---------- suy luan ----------
    def _ly_do_tu_choi(self, hang: pd.Series, cot: List[str]) -> Optional[str]:
        """Moi ly do khien policy KHONG duoc phep co y kien. None = du dieu kien."""
        if self.mo_hinh is None:
            return self._van_tay_loi or "chua co champion"

        thieu = [c for c in cot if c not in hang.index]
        if thieu:
            return "thieu %d cot dac trung (%s...)" % (len(thieu), thieu[0])

        gt = hang[cot].to_numpy(dtype=float)
        if not np.all(np.isfinite(gt)):
            xau = [c for c, v in zip(cot, gt) if not np.isfinite(v)]
            return "dac trung chua san sang: %s" % ", ".join(xau[:3])

        # Xep hang cat ngang tren qua it ma la vo nghia: voi 3 ma thi "top 33%"
        # khong mang thong tin gi, nhung mo hinh van an cac cot _r nhu that.
        n_ma = float(hang.get("n_ma", 0) or 0)
        toi_thieu = getattr(self.cfg, "POLICY_MIN_MA", 8)
        if any(c.endswith("_r") for c in cot) and n_ma < toi_thieu:
            return "chi co %d ma tai moc nay, can >= %d de xep hang co nghia" % (n_ma, toi_thieu)
        return None

    def du_doan(self, hang: pd.Series) -> KetQuaPolicy:
        """Y kien cua policy cho MOT dong panel (mot ma tai mot moc thoi gian)."""
        kq = KetQuaPolicy()
        cot = self.mo_hinh.cot_dac_trung if self.mo_hinh else []

        tu_choi = self._ly_do_tu_choi(hang, cot)
        if tu_choi:
            kq.ly_do = tu_choi
            return kq

        kq.phien_ban = self.mo_hinh.phien_ban
        try:
            X = hang[cot].to_numpy(dtype=float).reshape(1, -1)
            p_long = float(self.mo_hinh.booster_long.predict(X)[0])
            p_short = float(self.mo_hinh.booster_short.predict(X)[0])
        except Exception as e:                       # loi suy luan -> im lang, khong y kien
            logger.error("Policy loi khi du doan: %s", e)
            kq.ly_do = "loi suy luan: %s" % e
            return kq

        lai, lo = self._bien_do_lai_lo()
        kq.p_long, kq.p_short = p_long, p_short
        kq.ev_long = p_long * lai["long"] + (1.0 - p_long) * lo["long"]
        kq.ev_short = p_short * lai["short"] + (1.0 - p_short) * lo["short"]
        kq.co_y_kien = True
        kq.dac_trung = {c: float(hang[c]) for c in cot}

        nguong = getattr(self.cfg, "POLICY_EV_MIN", 0.001)
        day_du = max(getattr(self.cfg, "POLICY_EV_FULL", 0.010), nguong * 2)

        # Chi mot ben duoc thang. Neu ca hai cung vuot nguong thi mo hinh dang
        # tu mau thuan - do la tin hieu KEM chac chan hon, khong phai manh hon.
        if kq.ev_long > nguong and kq.ev_short > nguong:
            kq.ly_do = ("mo hinh cho ca hai chieu deu duong (EV %.4f / %.4f) - tu mau thuan"
                        % (kq.ev_long, kq.ev_short))
            return kq

        if kq.ev_long > nguong:
            kq.action, ev = BUY, kq.ev_long
        elif kq.ev_short > nguong:
            kq.action, ev = SELL, kq.ev_short
        else:
            kq.ly_do = ("EV ca hai chieu duoi nguong (long %.4f, short %.4f, can > %.4f)"
                        % (kq.ev_long, kq.ev_short, nguong))
            return kq

        kq.strength = float(np.clip((ev - nguong) / max(day_du - nguong, 1e-9), 0.0, 1.0))
        kq.ly_do = "EV %s = %.4f (p=%.3f)" % (
            kq.action, ev, kq.p_long if kq.action == BUY else kq.p_short)
        return kq

    def _bien_do_lai_lo(self):
        """Lai/lo trung binh MOI LENH, do tren khoi kiem dinh luc huan luyen.

        Do tren khoi kiem dinh chu khong phai khoi train: tren train mo hinh da
        thay ket qua nen bien do thuong lac quan hon thuc te.
        """
        m = self.mo_hinh.meta.get("bien_do", {}) if self.mo_hinh else {}
        mac_dinh_lai = 0.02
        mac_dinh_lo = -0.015
        lai = {"long": float(m.get("lai_long", mac_dinh_lai)),
               "short": float(m.get("lai_short", mac_dinh_lai))}
        lo = {"long": float(m.get("lo_long", mac_dinh_lo)),
              "short": float(m.get("lo_short", mac_dinh_lo))}
        return lai, lo


def chuan_bi_panel_live(frames: Dict[str, pd.DataFrame], cfg=config,
                        derivs: Dict[str, pd.DataFrame] = None) -> pd.DataFrame:
    """Panel dac trung cho vong chay that - KHONG gan nhan.

    Live khong co tuong lai de gan nhan, va do la mot bat bien nen giu bang code
    chu khong bang y thuc: `gan_nhan=False` dam bao khong ton tai duong nao ma
    nhan lot vao duoc panel dang chay that.
    """
    from . import features
    return features.xay_panel(frames, cfg, gan_nhan=False, derivs=derivs)


def lay_hang(panel: pd.DataFrame, symbol: str, timestamp: int = None) -> Optional[pd.Series]:
    """Dong cua mot ma tai mot moc. timestamp=None -> moc MOI NHAT cua ma do."""
    con = panel[panel["symbol"] == symbol]
    if con.empty:
        return None
    if timestamp is None:
        return con.iloc[-1]
    khop = con[con["timestamp"] == int(timestamp)]
    return khop.iloc[-1] if not khop.empty else None
