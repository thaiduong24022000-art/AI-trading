"""
Kho mo hinh co phien ban - lop bao ve "khong tu pha model dang chay".

VAN DE: mot vong hoc lien tuc tu no la mot co che tu huy. No huan luyen de len
mo hinh moi, va neu mo hinh moi tu dong thay the mo hinh cu thi chi can MOT
cua so du lieu bat thuong (thang 3/2020, mot dot thanh ly hang loat) la con bot
mang len chay mot mo hinh hoc tu nhieu - im lang, khong ai bao loi.

BON RANG BUOC O DAY:

1. BAT BIEN. Mot phien ban da ghi thi khong bao gio bi sua. Huan luyen lai luon
   sinh thu muc moi. Nho vay lich su luon quay lai duoc, va so lieu bao cao cua
   mot phien ban khong bao gio "troi" khoi mo hinh da sinh ra no.

2. THANG CAP LA HANH DONG RIENG. Huan luyen KHONG dong nghia voi trien khai.
   `luu()` chi tao phien ban; phai goi `thang_cap()` thi no moi thanh champion.
   Vong hoc chi duoc goi `thang_cap()` sau khi qua cong thong ke.

3. DAU VAN TAY. Mo hinh hoc bai toan duoc dinh nghia boi ATR_STOP_MULT,
   ATR_TP_MULT, phi va slippage - doi mot trong nhung so do la doi bai toan.
   Neu ai do sua ATR_STOP_MULT tu 2.0 xuong 1.5, mo hinh cu van nap duoc va van
   du doan binh thuong, nhung no dang tra loi mot cau hoi KHAC. Dau van tay
   khien truong hop do bao loi thay vi troi qua im lang.

4. QUAY LUI MOT BUOC. `ha_cap()` tra champion ve phien ban truoc do (hoac ve
   khong co mo hinh nao = chay thuan luat). Duong thoat phai ton tai truoc khi
   can den no.
"""
import glob
import hashlib
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)

THU_MUC_MAC_DINH = getattr(config, "POLICY_MODEL_DIR",
                           os.path.join(config.BASE_DIR, "models"))

# Nhung tham so dinh nghia BAI TOAN ma mo hinh duoc huan luyen de giai.
# Doi bat ky cai nao = mo hinh cu khong con dung nua.
THAM_SO_BAI_TOAN = ("ATR_STOP_MULT", "ATR_TP_MULT", "FEE_TAKER", "SLIPPAGE",
                    "KLINE_INTERVAL")

# Hai loai mo hinh, hai hinh dang khac nhau tren dia:
#   hai_chieu  long.txt + short.txt - AI policy hoi "nen nay nen mua hay ban"
#   meta       meta.txt             - bo loc hoi "tin hieu luat nay co dang nghe"
# Loai duoc ghi trong meta.json va suy ra tu tep co mat khi nap, nen mot phien
# ban cu (truoc khi co truong nay) van nap dung.
HAI_CHIEU = "hai_chieu"
META = "meta"


def dau_van_tay(cot_dac_trung: List[str], cfg=config, max_horizon: int = 60) -> str:
    """Chuoi bam dinh danh BAI TOAN + DAU VAO cua mo hinh.

    Gom: danh sach dac trung (co thu tu - LightGBM an theo vi tri cot) va cac
    tham so barrier/chi phi. Khong gom sieu tham so huan luyen: hai mo hinh
    khac learning_rate van giai cung mot bai toan va van so sanh duoc voi nhau.
    """
    phan = {"cot": list(cot_dac_trung), "max_horizon": int(max_horizon)}
    for ten in THAM_SO_BAI_TOAN:
        phan[ten] = getattr(cfg, ten, None)
    chuoi = json.dumps(phan, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(chuoi.encode("utf-8")).hexdigest()[:16]


@dataclass
class MoHinhPolicy:
    """Mot phien ban mo hinh da nap.

    Mo hinh `meta` chi co MOT booster (nam o `booster_long`, `booster_short`
    la None). Dung chung mot lop thay vi tach doi co chu dich: thang cap, ha
    cap, dau van tay, nhat ky su kien - toan bo vong doi giong het nhau, va
    tach ra se thanh hai ban sao cua cung mot logic roi troi khoi nhau.
    """
    phien_ban: str
    booster_long: object
    booster_short: object = None
    meta: Dict = field(default_factory=dict)

    @property
    def loai(self) -> str:
        return self.meta.get("loai", HAI_CHIEU)

    @property
    def la_meta(self) -> bool:
        return self.loai == META

    @property
    def booster(self) -> object:
        """Booster duy nhat cua mo hinh meta."""
        return self.booster_long

    @property
    def cot_dac_trung(self) -> List[str]:
        return list(self.meta.get("cot_dac_trung", []))

    @property
    def van_tay(self) -> str:
        return self.meta.get("dau_van_tay", "")

    def hop_le_voi(self, cfg=config) -> Optional[str]:
        """None = dung bai toan hien tai. Nguoc lai tra ve mo ta cho lech."""
        ht = dau_van_tay(self.cot_dac_trung, cfg, self.meta.get("max_horizon", 60))
        if ht == self.van_tay:
            return None
        lech = [t for t in THAM_SO_BAI_TOAN
                if self.meta.get("tham_so_bai_toan", {}).get(t) != getattr(cfg, t, None)]
        return ("dau van tay lech (%s != %s)%s" %
                (self.van_tay, ht, "; tham so doi: " + ", ".join(lech) if lech else ""))


class KhoModel:
    def __init__(self, thu_muc: str = None):
        self.thu_muc = thu_muc or THU_MUC_MAC_DINH
        os.makedirs(self.thu_muc, exist_ok=True)

    # ---------- duong dan ----------
    def _duong_dan(self, phien_ban: str) -> str:
        return os.path.join(self.thu_muc, phien_ban)

    @property
    def _tep_champion(self) -> str:
        return os.path.join(self.thu_muc, "champion.json")

    @property
    def _tep_su_kien(self) -> str:
        return os.path.join(self.thu_muc, "lich_su.jsonl")

    # ---------- ghi ----------
    def phien_ban_moi(self, van_tay: str) -> str:
        return "v%s_%s" % (time.strftime("%Y%m%d_%H%M%S"), van_tay[:8])

    def luu(self, booster_long, booster_short, meta: Dict, the: str = "") -> str:
        """Ghi mot phien ban MOI. Khong bao gio de len phien ban cu.

        Luu y: ham nay KHONG thang cap. Mo hinh vua ghi chua duoc dung o dau ca
        cho den khi `thang_cap()` duoc goi - va viec do phai di qua cong thong ke.
        """
        pb = meta.get("phien_ban") or self.phien_ban_moi(meta.get("dau_van_tay", "nofp"))
        d = self._duong_dan(pb)
        if os.path.exists(d):
            raise FileExistsError("phien ban %s da ton tai - mo hinh la bat bien" % pb)
        return self._ghi_phien_ban(
            pb, d, {"long.txt": booster_long, "short.txt": booster_short},
            dict(meta, loai=meta.get("loai", HAI_CHIEU)), the)

    def luu_meta(self, booster, meta: Dict, the: str = "") -> str:
        """Ghi mot phien ban bo loc meta-label (mot booster duy nhat).

        Dung chung moi rang buoc voi `luu()`: bat bien, khong tu thang cap, co
        dau van tay, co ghi nhat ky su kien.
        """
        pb = meta.get("phien_ban") or self.phien_ban_moi(meta.get("dau_van_tay", "nofp"))
        d = self._duong_dan(pb)
        if os.path.exists(d):
            raise FileExistsError("phien ban %s da ton tai - mo hinh la bat bien" % pb)
        return self._ghi_phien_ban(pb, d, {"meta.txt": booster},
                                   dict(meta, loai=META), the)

    def _ghi_phien_ban(self, pb: str, d: str, boosters: Dict[str, object],
                       meta: Dict, the: str) -> str:
        tam = d + ".dang_ghi"
        shutil.rmtree(tam, ignore_errors=True)
        os.makedirs(tam)
        try:
            for ten_tep, b in boosters.items():
                b.save_model(os.path.join(tam, ten_tep))
            meta = dict(meta)
            meta["phien_ban"] = pb
            meta["luu_luc"] = time.time()
            with open(os.path.join(tam, "meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2, default=str)
            if the:
                with open(os.path.join(tam, "the_mo_hinh.md"), "w", encoding="utf-8") as f:
                    f.write(the)
            # Doi ten la thao tac nguyen tu: khong bao gio ton tai thu muc phien
            # ban ghi do dang ma nguoi khac nap phai.
            os.rename(tam, d)
        except Exception:
            shutil.rmtree(tam, ignore_errors=True)
            raise

        self.ghi_su_kien("luu", pb, meta.get("ghi_chu", ""))
        logger.info("Da luu phien ban %s (chua thang cap)", pb)
        return pb

    # ---------- doc ----------
    def danh_sach(self) -> List[str]:
        ds = [os.path.basename(p) for p in glob.glob(os.path.join(self.thu_muc, "v*"))
              if os.path.isdir(p) and os.path.exists(os.path.join(p, "meta.json"))]
        return sorted(ds)

    def nap(self, phien_ban: str) -> MoHinhPolicy:
        import lightgbm as lgb

        d = self._duong_dan(phien_ban)
        if not os.path.isdir(d):
            raise FileNotFoundError("khong co phien ban %s" % phien_ban)
        with open(os.path.join(d, "meta.json"), encoding="utf-8") as f:
            meta = json.load(f)

        # Nhan dang theo TEP CO MAT chu khong chi theo truong `loai` trong
        # meta.json: mot phien ban ghi truoc khi co truong do van phai nap dung.
        tep_meta = os.path.join(d, "meta.txt")
        if os.path.exists(tep_meta):
            meta.setdefault("loai", META)
            return MoHinhPolicy(
                phien_ban=phien_ban,
                booster_long=lgb.Booster(model_file=tep_meta),
                booster_short=None,
                meta=meta,
            )
        meta.setdefault("loai", HAI_CHIEU)
        return MoHinhPolicy(
            phien_ban=phien_ban,
            booster_long=lgb.Booster(model_file=os.path.join(d, "long.txt")),
            booster_short=lgb.Booster(model_file=os.path.join(d, "short.txt")),
            meta=meta,
        )

    def doc_meta(self, phien_ban: str) -> Dict:
        p = os.path.join(self._duong_dan(phien_ban), "meta.json")
        if not os.path.exists(p):
            return {}
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    # ---------- champion ----------
    def champion_hien_tai(self) -> Optional[str]:
        if not os.path.exists(self._tep_champion):
            return None
        try:
            with open(self._tep_champion, encoding="utf-8") as f:
                return json.load(f).get("phien_ban")
        except (json.JSONDecodeError, OSError):
            logger.error("champion.json hong - coi nhu KHONG co champion")
            return None

    def thong_tin_champion(self) -> Dict:
        if not os.path.exists(self._tep_champion):
            return {}
        try:
            with open(self._tep_champion, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def nap_champion(self) -> Optional[MoHinhPolicy]:
        pb = self.champion_hien_tai()
        if not pb:
            return None
        try:
            return self.nap(pb)
        except (FileNotFoundError, OSError) as e:
            logger.error("Khong nap duoc champion %s: %s", pb, e)
            return None

    def thang_cap(self, phien_ban: str, ly_do: str) -> None:
        if not os.path.isdir(self._duong_dan(phien_ban)):
            raise FileNotFoundError("khong the thang cap phien ban khong ton tai: %s"
                                    % phien_ban)
        truoc = self.champion_hien_tai()
        self._ghi_champion({"phien_ban": phien_ban, "truoc_do": truoc,
                            "thang_cap_luc": time.time(), "ly_do": ly_do})
        self.ghi_su_kien("thang_cap", phien_ban, ly_do, truoc_do=truoc)
        logger.warning("THANG CAP champion: %s -> %s | %s", truoc, phien_ban, ly_do)

    def ha_cap(self, ly_do: str) -> Optional[str]:
        """Tra champion ve phien ban truoc do. None = khong con mo hinh nao.

        Khi tra ve None, bot KHONG dung lai - no chay tiep bang chien luoc luat.
        Do la trang thai an toan mac dinh, va la ly do policy luon la mot lop
        THEM VAO chu khong phai lop thay the.
        """
        tt = self.thong_tin_champion()
        hien = tt.get("phien_ban")
        truoc = tt.get("truoc_do")
        if truoc and os.path.isdir(self._duong_dan(truoc)):
            self._ghi_champion({"phien_ban": truoc, "truoc_do": None,
                                "thang_cap_luc": time.time(),
                                "ly_do": "ha cap tu %s: %s" % (hien, ly_do)})
            self.ghi_su_kien("ha_cap", truoc, ly_do, truoc_do=hien)
            logger.warning("HA CAP champion: %s -> %s | %s", hien, truoc, ly_do)
            return truoc

        # Khong co duong lui -> go champion, quay ve chay thuan luat
        if os.path.exists(self._tep_champion):
            os.remove(self._tep_champion)
        self.ghi_su_kien("ha_cap_hoan_toan", "", ly_do, truoc_do=hien)
        logger.error("HA CAP HOAN TOAN: go champion %s, quay ve chay thuan luat | %s",
                     hien, ly_do)
        return None

    def _ghi_champion(self, du_lieu: Dict) -> None:
        tam = self._tep_champion + ".tmp"
        with open(tam, "w", encoding="utf-8") as f:
            json.dump(du_lieu, f, ensure_ascii=False, indent=2)
        os.replace(tam, self._tep_champion)

    # ---------- nhat ky su kien ----------
    def ghi_su_kien(self, loai: str, phien_ban: str, ly_do: str = "", **them) -> None:
        ban_ghi = {"ts": time.time(), "thoi_diem": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "loai": loai, "phien_ban": phien_ban, "ly_do": ly_do}
        ban_ghi.update(them)
        with open(self._tep_su_kien, "a", encoding="utf-8") as f:
            f.write(json.dumps(ban_ghi, ensure_ascii=False, default=str) + "\n")

    def su_kien(self, gioi_han: int = 50) -> List[Dict]:
        if not os.path.exists(self._tep_su_kien):
            return []
        with open(self._tep_su_kien, encoding="utf-8") as f:
            dong = [l for l in f.read().splitlines() if l.strip()]
        ra = []
        for l in dong[-gioi_han:]:
            try:
                ra.append(json.loads(l))
            except json.JSONDecodeError:
                continue
        return ra
