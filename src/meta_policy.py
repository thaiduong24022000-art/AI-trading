"""
Lop suy luan cua bo loc meta - chay trong vong giao dich that.

VI TRI TRONG DUONG ONG: lop nay khong bao gio tao ra lenh. No chi tra loi mot
cau hoi ve mot tin hieu DA CO:

    chien luoc luat -> ensemble -> [BO LOC META] -> LLM veto -> risk -> lenh

Do chinh la rang buoc dat cho che do `filter` trong `src/policy.py`, va bo loc
nay la thu duoc thiet ke dung cho vi tri do. No co ba cau tra loi:

    GIU     xac suat thang >= nguong  -> de tin hieu di tiep nguyen ven
    GIAM    duoi nguong nhung khong xa -> giam quy mo
    CHAN    duoi han                   -> bo tin hieu

Va mot cau tra loi thu tu, quan trong khong kem: KHONG Y KIEN. Moi tinh huong
khong du dieu kien - thieu dac trung, sai dau van tay, qua it ma de xep hang -
deu tra ve khong y kien, va luc do tin hieu di tiep NGUYEN VEN. Bo loc hong
phai lam he thong quay ve hanh vi cu, khong duoc lam no dung lai va cung khong
duoc lam no chan bua.

MAC DINH KHI KHONG CHAC LA CHO QUA, khac voi `MLPolicy` mac dinh la HOLD. Ly do:
o day ta dang xen vao mot tin hieu da qua kiem dinh cua chien luoc luat. Chan
no vi mot ly do ky thuat (thieu mot cot dac trung) la thay mot quyet dinh co co
so bang mot quyet dinh khong co co so nao.
"""
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, Optional

import numpy as np
import pandas as pd

import config
from . import model_store
from .strategies.base import BUY, SELL

logger = logging.getLogger(__name__)

GIU = "giu"
GIAM = "giam"
CHAN = "chan"
KHONG_Y_KIEN = "khong_y_kien"


@dataclass
class KetQuaLoc:
    quyet_dinh: str = KHONG_Y_KIEN
    he_so: float = 1.0          # nhan vao do manh tin hieu: 1.0 giu nguyen, 0.0 chan
    p_thang: float = float("nan")
    ky_vong: float = float("nan")
    nguong: float = float("nan")
    phien_ban: str = ""
    ly_do: str = ""

    @property
    def co_y_kien(self) -> bool:
        return self.quyet_dinh != KHONG_Y_KIEN

    def tom_tat(self) -> str:
        if not self.co_y_kien:
            return "bo loc: khong y kien (%s)" % self.ly_do
        return ("bo loc[%s]: %s (p=%.3f, nguong %.3f, EV %+.4f)"
                % (self.phien_ban, self.quyet_dinh.upper(), self.p_thang,
                   self.nguong, self.ky_vong))


class MetaPolicy:
    """Boc champion cua kho bo loc. An toan khi khong co mo hinh nao."""

    def __init__(self, cfg=config, kho: model_store.KhoModel = None):
        from .meta_continual import KhoMeta

        self.cfg = cfg
        self.kho = kho or KhoMeta()
        self.mo_hinh: Optional[model_store.MoHinhPolicy] = None
        self._van_tay_loi: Optional[str] = None
        self._mtime: float = 0.0
        self.nap_lai()

    # ---------- vong doi ----------
    def nap_lai(self) -> bool:
        self.mo_hinh = None
        self._van_tay_loi = None
        try:
            mh = self.kho.nap_champion()
        except Exception as e:
            logger.error("Loi nap champion bo loc: %s", e)
            return False
        if mh is None:
            return False
        if not mh.la_meta:
            self._van_tay_loi = "champion %s khong phai bo loc meta" % mh.phien_ban
            logger.error(self._van_tay_loi)
            return False

        lech = mh.hop_le_voi(self.cfg)
        if lech:
            self._van_tay_loi = lech
            logger.error("Bo loc TU CHOI mo hinh %s: %s", mh.phien_ban, lech)
            return False

        self.mo_hinh = mh
        p = os.path.join(self.kho.thu_muc, "champion.json")
        self._mtime = os.path.getmtime(p) if os.path.exists(p) else 0.0
        logger.info("Bo loc nap champion %s (nguong %.4f, loc tin hieu cua %s)",
                    mh.phien_ban, self.nguong,
                    ",".join(mh.meta.get("chien_luoc_nguon", [])))
        return True

    def kiem_tra_champion_moi(self) -> bool:
        p = os.path.join(self.kho.thu_muc, "champion.json")
        mtime = os.path.getmtime(p) if os.path.exists(p) else 0.0
        if mtime != self._mtime:
            self._mtime = mtime
            return self.nap_lai()
        return self.mo_hinh is not None

    @property
    def san_sang(self) -> bool:
        return self.mo_hinh is not None

    @property
    def nguong(self) -> float:
        return float(self.mo_hinh.meta.get("nguong", 0.5)) if self.mo_hinh else 0.5

    @property
    def chien_luoc_nguon(self) -> list:
        return list(self.mo_hinh.meta.get("chien_luoc_nguon", [])) if self.mo_hinh else []

    # ---------- suy luan ----------
    def _tu_choi(self, hang: pd.Series, cot) -> Optional[str]:
        if self.mo_hinh is None:
            return self._van_tay_loi or "chua co bo loc nao"
        thieu = [c for c in cot if c not in hang.index]
        if thieu:
            return "thieu %d cot dac trung (%s...)" % (len(thieu), thieu[0])
        gt = hang[cot].to_numpy(dtype=float)
        if not np.all(np.isfinite(gt)):
            xau = [c for c, v in zip(cot, gt) if not np.isfinite(v)]
            return "dac trung chua san sang: %s" % ", ".join(xau[:3])
        n_ma = float(hang.get("n_ma", 0) or 0)
        toi_thieu = getattr(self.cfg, "POLICY_MIN_MA", 8)
        if any(c.endswith("_r") for c in cot) and n_ma < toi_thieu:
            return "chi co %d ma tai moc nay, can >= %d" % (n_ma, toi_thieu)
        return None

    def danh_gia(self, hang: pd.Series, huong: str, suc_manh: float,
                 regime: str = "") -> KetQuaLoc:
        """Cham diem MOT tin hieu cua chien luoc luat."""
        from . import meta_label

        kq = KetQuaLoc()
        cot = self.mo_hinh.cot_dac_trung if self.mo_hinh else []

        # Dac trung cua tin hieu duoc gan vao BAN SAO cua dong panel. Sua truc
        # tiep hang goc se lam ban ky uc cua vong lap - cac ma sau doc phai gia
        # tri cua ma truoc.
        h = hang.copy()
        h["la_mua"] = 1.0 if huong == BUY else 0.0
        h["suc_manh_luat"] = float(suc_manh)
        h["regime_trend"] = 1.0 if regime == "trend" else 0.0
        h["regime_range"] = 1.0 if regime == "range" else 0.0
        h["regime_bien_dong"] = 1.0 if regime == "high_vol" else 0.0

        ly_do = self._tu_choi(h, cot)
        if ly_do:
            kq.ly_do = ly_do
            return kq

        kq.phien_ban = self.mo_hinh.phien_ban
        kq.nguong = self.nguong
        try:
            X = h[cot].to_numpy(dtype=float).reshape(1, -1)
            kq.p_thang = float(self.mo_hinh.booster.predict(X)[0])
        except Exception as e:
            logger.error("Bo loc loi khi du doan: %s", e)
            kq.ly_do = "loi suy luan: %s" % e
            return kq

        bien_do = self.mo_hinh.meta.get("bien_do", {})
        if bien_do:
            kq.ky_vong = float(meta_label.ky_vong(np.array([kq.p_thang]), bien_do)[0])

        # Vung GIAM nam ngay duoi nguong: mo hinh khong du tu tin de bao "vao",
        # nhung cung chua noi nguoc lai. Chan han o day se vut di ca nhung tin
        # hieu chi vua sat nguong, ma sai so du doan cua mo hinh lon hon khoang
        # sat do nhieu.
        rong_giam = getattr(self.cfg, "META_VUNG_GIAM", 0.02)
        he_so_giam = getattr(self.cfg, "POLICY_FILTER_GIAM", 0.5)

        if kq.p_thang >= kq.nguong:
            kq.quyet_dinh, kq.he_so = GIU, 1.0
            kq.ly_do = "p %.3f >= nguong %.3f" % (kq.p_thang, kq.nguong)
        elif kq.p_thang >= kq.nguong - rong_giam:
            kq.quyet_dinh, kq.he_so = GIAM, he_so_giam
            kq.ly_do = "p %.3f sat duoi nguong %.3f - giam quy mo" % (kq.p_thang, kq.nguong)
        else:
            kq.quyet_dinh, kq.he_so = CHAN, 0.0
            kq.ly_do = "p %.3f duoi han %.3f" % (kq.p_thang, kq.nguong - rong_giam)
        return kq
