"""
Kho chien luoc luat: tu ung vien -> bong -> chu dong.

VI SAO CAN FILE NAY: Strategy Lab sinh ra gia thuyet va kiem dinh chung, nhung
neu khong co duong di tu "qua cong" den "chay that" thi ca cai lab la mot ngo
cut - no viet bao cao roi thoi. File nay la duong di do, va quan trong hon,
no la cac CANH CUA tren duong di do.

BON TRANG THAI (dung tu vung voi AI policy o src/policy.py cho khoi phai nho
hai bo khai niem):

    ung_vien   da qua cong thong ke, CHUA chay o dau ca
    bong       chay song song, chi ghi so, KHONG anh huong lenh nao
    chu_dong   la mot thanh vien binh thuong cua ensemble
    da_loai    da bi go, giu lai de con biet minh da thu gi

HAI NGUYEN TAC, ca hai deu la bat doi xung CO Y:

1. LEN THI CHAM, XUONG THI NHANH.
   Len mot bac phai co bang chung: len `bong` doi bang chung qua cong; len
   `chu_dong` doi da chay bong du so ngay toi thieu. Xuong bac thi khong doi
   gi ca, luc nao cung duoc. Duong lui phai luon thong - luc can no nhat la
   luc moi thu dang hong.

2. KHONG BAO GIO TU DONG LEN BAC.
   Bo may co the tu HA cap (xem continual.py lam vay voi mo hinh), nhung viec
   nang mot chien luoc len muc duoc dung tien la quyet dinh cua NGUOI. Mot he
   thong tu nang cap chinh no la mot he thong khong ai chiu trach nhiem.

KHONG CHO NHAY COC: ung_vien khong len thang chu_dong duoc. Kien truc v2 noi
ro "vao shadow mode 2-4 tuan, neu van tot moi them vao ensemble voi trong so
nho". Bo qua buoc bong nghia la dem thang mot thu chua ai nhin thay chay that
ra dung tien.
"""
import json
import logging
import os
import time
from typing import Dict, List, Optional

import config

from .rule_spec import SpecKhongHopLe, bien_dich, kiem_tra_spec

logger = logging.getLogger(__name__)

UNG_VIEN = "ung_vien"
BONG = "bong"
CHU_DONG = "chu_dong"
DA_LOAI = "da_loai"
CAC_TRANG_THAI = (UNG_VIEN, BONG, CHU_DONG, DA_LOAI)

# Toi thieu bao nhieu ngay o che do bong truoc khi duoc phep len chu_dong.
# Kien truc v2 noi 2-4 tuan; lay can duoi.
NGAY_BONG_TOI_THIEU = 14

DUONG_DAN_MAC_DINH = os.path.join(config.BASE_DIR, "data", "kho_luat.json")


def _lam_sach(x):
    """inf/nan -> None. Xem chu thich trong _ghi()."""
    if isinstance(x, dict):
        return {k: _lam_sach(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_lam_sach(v) for v in x]
    if isinstance(x, float) and (x != x or x in (float("inf"), float("-inf"))):
        return None
    return x


class KhoLuatLoi(RuntimeError):
    """Thao tac bi tu choi. Luon kem ly do cu the."""


class KhoLuat:
    def __init__(self, duong_dan: str = None):
        self.duong_dan = duong_dan or DUONG_DAN_MAC_DINH

    # ---------- doc/ghi ----------
    def _doc(self) -> Dict:
        if not os.path.exists(self.duong_dan):
            return {"muc": {}}
        try:
            with open(self.duong_dan, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            # KHONG tra ve kho rong: kho rong nghia la "chua thu gi", va he
            # thong se vui ve cho ghi de len lich su da mat.
            raise KhoLuatLoi("Kho luat hong (%s): %s. Sua hoac xoa co y thuc."
                             % (self.duong_dan, e))

    def _ghi(self, data: Dict) -> None:
        os.makedirs(os.path.dirname(self.duong_dan), exist_ok=True)
        with open(self.duong_dan, "w", encoding="utf-8") as f:
            # allow_nan=False: bang chung den tu lab co the chua inf (profit
            # factor khi khong co lenh thua). Python ghi no thanh `Infinity`,
            # khong phai JSON hop le - va kho nay se duoc doc boi trinh duyet.
            # Tha nem loi luc ghi con hon de lai mot file khong ai khac doc duoc.
            json.dump(_lam_sach(data), f, ensure_ascii=False, indent=2,
                      default=float, allow_nan=False)

    # ---------- truy van ----------
    def tat_ca(self) -> Dict[str, Dict]:
        return self._doc().get("muc", {})

    def lay(self, ten: str) -> Optional[Dict]:
        return self.tat_ca().get(ten)

    def theo_trang_thai(self, trang_thai: str) -> List[Dict]:
        return [m for m in self.tat_ca().values() if m.get("trang_thai") == trang_thai]

    def ten_chu_dong(self) -> List[str]:
        return [m["ten"] for m in self.theo_trang_thai(CHU_DONG)]

    def ten_bong(self) -> List[str]:
        return [m["ten"] for m in self.theo_trang_thai(BONG)]

    # ---------- thay doi ----------
    def them_ung_vien(self, spec: Dict, bang_chung: Dict, ghi_chu: str = "") -> Dict:
        """Ghi mot gia thuyet DA QUA CONG vao kho o trang thai ung_vien.

        bang_chung phai co qua_cong=True. Cho phep ghi mot y tuong chua qua
        cong vao day se lam ca chuoi phia sau vo nghia: cac cong sau chi kiem
        tra "da o bong du lau chua", chung tin rang cong thong ke da xong.
        """
        spec = kiem_tra_spec(spec)
        if not bang_chung or not bang_chung.get("qua_cong"):
            raise KhoLuatLoi(
                "'%s' chua qua cong thong ke - khong duoc vao kho. Chay "
                "research/strategy_lab.py truoc." % spec["ten"])

        data = self._doc()
        ten = spec["ten"]
        if ten in data["muc"]:
            raise KhoLuatLoi("'%s' da co trong kho (trang thai: %s)"
                             % (ten, data["muc"][ten].get("trang_thai")))

        muc = {
            "ten": ten, "spec": spec, "trang_thai": UNG_VIEN,
            "bang_chung": bang_chung,
            "tao_luc": time.time(),
            "vao_bong_luc": None,
            "lich_su": [{"luc": time.strftime("%Y-%m-%d %H:%M:%S"),
                         "tu": None, "den": UNG_VIEN,
                         "ly_do": ghi_chu or "qua cong thong ke"}],
        }
        data["muc"][ten] = muc
        self._ghi(data)
        logger.info("Da them ung vien '%s' vao kho luat", ten)
        return muc

    def _doi_trang_thai(self, ten: str, den: str, ly_do: str) -> Dict:
        data = self._doc()
        muc = data["muc"].get(ten)
        if muc is None:
            raise KhoLuatLoi("Khong co '%s' trong kho" % ten)
        tu = muc.get("trang_thai")
        muc["trang_thai"] = den
        if den == BONG and not muc.get("vao_bong_luc"):
            muc["vao_bong_luc"] = time.time()
        muc.setdefault("lich_su", []).append({
            "luc": time.strftime("%Y-%m-%d %H:%M:%S"),
            "tu": tu, "den": den, "ly_do": ly_do,
        })
        self._ghi(data)
        logger.info("Chien luoc luat '%s': %s -> %s (%s)", ten, tu, den, ly_do)
        return muc

    def so_ngay_o_bong(self, ten: str) -> float:
        muc = self.lay(ten)
        if not muc or not muc.get("vao_bong_luc"):
            return 0.0
        return (time.time() - float(muc["vao_bong_luc"])) / 86400.0

    def thang_cap(self, ten: str, ly_do: str = "", ep: bool = False,
                  storage=None) -> Dict:
        """Len mot bac. ung_vien -> bong -> chu_dong. Khong nhay coc.

        Len `chu_dong` doi HAI thu, khong phai mot:
          - da chay bong >= NGAY_BONG_TOI_THIEU ngay (thoi gian phuc vu), va
          - diem che do bong du bang chung (ket qua that) - can `storage`.
        Chi dem ngay thi 14 ngay im lang cung qua cong y het 14 ngay tot.

        ep=True bo qua CA HAI dieu kien tren (khi nguoi co ly do rieng, vi du
        da chay bong o may khac). No KHONG bo qua duoc yeu cau phai di qua
        trang thai bong.
        """
        muc = self.lay(ten)
        if muc is None:
            raise KhoLuatLoi("Khong co '%s' trong kho" % ten)
        tt = muc.get("trang_thai")

        if tt == UNG_VIEN:
            return self._doi_trang_thai(ten, BONG, ly_do or "nguoi cho vao che do bong")

        if tt == BONG:
            ngay = self.so_ngay_o_bong(ten)
            if not ep:
                if ngay < NGAY_BONG_TOI_THIEU:
                    raise KhoLuatLoi(
                        "'%s' moi o che do bong %.1f ngay, can >= %d. Kien truc v2 doi "
                        "2-4 tuan chay song song truoc khi dung tien. Dung --ep neu "
                        "ban co ly do rieng va chiu trach nhiem."
                        % (ten, ngay, NGAY_BONG_TOI_THIEU))
                diem = self.diem_bong(ten, storage)
                if diem is not None and not diem.get("du_bang_chung"):
                    raise KhoLuatLoi(
                        "'%s' da chay bong %.1f ngay nhung CHUA du bang chung: %s"
                        % (ten, ngay, diem.get("ly_do")))
            return self._doi_trang_thai(
                ten, CHU_DONG,
                ly_do or ("nguoi thang cap sau %.1f ngay chay bong" % ngay))

        if tt == CHU_DONG:
            raise KhoLuatLoi("'%s' da o muc cao nhat (chu_dong)" % ten)
        raise KhoLuatLoi("'%s' dang o trang thai '%s', khong thang cap duoc" % (ten, tt))

    def diem_bong(self, ten: str, storage=None) -> Optional[Dict]:
        """Diem che do bong cua mot muc. None neu khong cham duoc.

        Tra ve None (thay vi nem loi) khi khong co storage hoac module cham
        diem hong: mot lop DO khong duoc tu bien thanh mot lop CHAN. Nguoi
        dung se thay dieu kien so ngay nhu cu, va thieu lop bang chung se lo
        ra trong log chu khong lam ket cung ca kho.
        """
        if storage is None:
            return None
        try:
            from ..cham_diem_bong import danh_gia
            return danh_gia(storage, ten)
        except Exception as e:
            logger.exception("Khong cham duoc diem che do bong cho '%s': %s", ten, e)
            return None

    def ha_cap(self, ten: str, ly_do: str = "") -> Dict:
        """Xuong mot bac. Luon duoc phep - duong lui phai luon thong."""
        muc = self.lay(ten)
        if muc is None:
            raise KhoLuatLoi("Khong co '%s' trong kho" % ten)
        xuong = {CHU_DONG: BONG, BONG: UNG_VIEN, UNG_VIEN: DA_LOAI, DA_LOAI: DA_LOAI}
        den = xuong[muc.get("trang_thai", UNG_VIEN)]
        return self._doi_trang_thai(ten, den, ly_do or "nguoi ha cap")

    def loai_bo(self, ten: str, ly_do: str = "") -> Dict:
        return self._doi_trang_thai(ten, DA_LOAI, ly_do or "nguoi loai bo")

    # ---------- bien dich ----------
    def bien_dich_theo_trang_thai(self, trang_thai: str) -> List:
        """Tra ve list LOP Strategy cho cac muc o trang thai da cho."""
        ra = []
        for muc in self.theo_trang_thai(trang_thai):
            try:
                ra.append(bien_dich(muc["spec"]))
            except SpecKhongHopLe as e:
                # Spec trong kho hong nghia la ai do sua tay sai - bo qua muc
                # do chu khong lam sap ca bot.
                logger.error("Spec cua '%s' trong kho khong bien dich duoc: %s",
                             muc.get("ten"), e)
        return ra
