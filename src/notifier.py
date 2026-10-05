"""
Canh bao qua Telegram - Nang cap 7 (do ben van hanh).

VI SAO CAN: kien truc v2 noi "cham dieu kien nao thi dung mo lenh moi, bao
Telegram va CHO NGUOI". Ve chu "cho nguoi" chi co nghia neu nguoi do BIET la
minh dang duoc cho. Truoc file nay, moi canh bao chi di vao logs/bot.log tren
mot may tinh ca nhan - tuc la khong ai biet gi cho den luc mo may ra xem.

Vi du that trong chinh du an nay: bot crash-loop suot 6 tieng vi API key
testnet tra 401, lap lai moi 2 giay. Log ghi day du va dung ngay tu lan dau.
Khong ai doc.

BA QUY TAC, THEO THU TU QUAN TRONG:

1. LOP NAY KHONG BAO GIO DUOC LAM DUNG VONG GIAO DICH.
   Moi loi mang, timeout, token sai deu bi nuot tai day va chi ghi log. Mot
   bot dung giao dich vi Telegram sap la mot bot te hon bot khong co Telegram.
   Timeout ngan (mac dinh 5 giay) vi cung ly do.

2. KHONG SPAM.
   Circuit breaker bat thi no bat MAI cho den khi nguoi reset - neu bao moi
   vong lap 15 phut thi sau mot dem la 96 tin nhan giong het nhau, va tin
   nhan thu 97 se khong con ai doc. Dedup theo khoa: cung mot khoa chi bao
   lai sau `lap_lai_sau` giay.

3. TAT LA MAC DINH.
   Khong co token thi lop nay im lang tro thanh no-op. Khong canh bao, khong
   loi, khong lam phien - bot chay y het nhu truoc.

Bao mat: TELEGRAM_BOT_TOKEN nhay cam ngang API key san (ai co token deu gui
duoc tin nhan gia danh bot cua ban). No nam trong .env, trong KHOA_BI_MAT cua
web UI, va khong bao gio duoc log ra.
"""
import logging
import time
from typing import Dict, Optional

import requests

import config

logger = logging.getLogger(__name__)

API = "https://api.telegram.org/bot%s/sendMessage"

# Khoa dedup dung chung - de cho goi xoa_dedup() dung ten.
BREAKER = "breaker"
DOI_SOAT = "doi_soat"
LOI_API = "loi_api"


class Notifier:
    """Gui canh bao Telegram. Im lang va vo hai khi chua cau hinh."""

    def __init__(self, cfg=config):
        self.cfg = cfg
        self.token = getattr(cfg, "TELEGRAM_BOT_TOKEN", "")
        self.chat_id = getattr(cfg, "TELEGRAM_CHAT_ID", "")
        self.bat = bool(getattr(cfg, "ENABLE_TELEGRAM", False)
                       and self.token and self.chat_id)
        self.timeout = getattr(cfg, "TELEGRAM_TIMEOUT_SECONDS", 5)
        self._da_gui: Dict[str, float] = {}
        if getattr(cfg, "ENABLE_TELEGRAM", False) and not self.bat:
            logger.warning("ENABLE_TELEGRAM=true nhung thieu TELEGRAM_BOT_TOKEN "
                           "hoac TELEGRAM_CHAT_ID - canh bao Telegram se khong chay")

    # ---------- lop duoi ----------
    def _gui(self, text: str) -> bool:
        """Gui that. Nuot MOI loi - xem quy tac 1 o dau file."""
        if not self.bat:
            return False
        try:
            r = requests.post(API % self.token,
                              json={"chat_id": self.chat_id, "text": text,
                                    "disable_web_page_preview": True},
                              timeout=self.timeout)
            if r.status_code != 200:
                # Khong log body: response loi cua Telegram co the lap lai token.
                logger.warning("Telegram tu choi tin nhan (HTTP %s)", r.status_code)
                return False
            return True
        except Exception as e:
            logger.warning("Khong gui duoc Telegram (bo qua): %s", type(e).__name__)
            return False

    def bao(self, text: str, khoa: str = None, lap_lai_sau: float = 3600.0) -> bool:
        """Gui mot canh bao. `khoa` bat dedup: cung khoa chi gui lai sau
        `lap_lai_sau` giay, de mot trang thai keo dai khong thanh 96 tin nhan.
        """
        if not self.bat:
            return False
        if khoa:
            gui_lan_truoc = self._da_gui.get(khoa)
            if gui_lan_truoc is not None and (time.time() - gui_lan_truoc) < lap_lai_sau:
                return False
            self._da_gui[khoa] = time.time()
        return self._gui(text)

    def xoa_dedup(self, khoa: str) -> None:
        """Cho phep mot khoa duoc bao lai ngay lap tuc.

        Goi khi trang thai da doi that su - vi du nguoi vua reset circuit
        breaker: lan bat ke tiep la mot su kien MOI, khong phai tieng vang cua
        lan cu, nen no xung dang mot tin nhan.
        """
        self._da_gui.pop(khoa, None)

    # ---------- cac su kien cu the ----------
    def khoi_dong(self, san: str, testnet: bool, dry_run: bool, symbols,
                  chien_luoc) -> None:
        che_do = ("DRY-RUN" if dry_run
                  else "TESTNET/DEMO" if testnet else "!!! TIEN THAT !!!")
        self.bao("[BOT] Da khoi dong\nSan: %s\nChe do: %s\nMa: %s\nChien luoc: %s"
                 % (san.upper(), che_do, ",".join(symbols), ",".join(chien_luoc)))

    def dung(self, ly_do: str = "") -> None:
        self.bao("[BOT] Da dung%s\nLuu y: vi the dang mo VAN CON tren san."
                 % (" - %s" % ly_do if ly_do else ""))

    def doi_soat_that_bai(self, ly_do: str) -> None:
        # Dedup 30 phut: bot khoi dong lai lien tuc khi loi thi khong nen bao
        # moi lan, nhung cung khong duoc im qua lau vi day la loi CHAN bot chay.
        self.bao("[DUNG LAI] Doi soat that bai - bot khong chay duoc.\n%s\n\n"
                 "Bot dung o day co chu dich: khong doc duoc trang thai san thi "
                 "khong duoc doan." % ly_do, khoa=DOI_SOAT, lap_lai_sau=1800)

    def breaker_bat(self, ly_do: str) -> None:
        self.bao("[CIRCUIT BREAKER] Da ngat - khong mo lenh moi.\n%s\n\n"
                 "Can nguoi kiem tra va reset thu cong." % ly_do,
                 khoa=BREAKER, lap_lai_sau=6 * 3600)

    def mo_lenh(self, symbol: str, side: str, qty: float, gia: float,
                sl: float, tp: float, chien_luoc: str, dry_run: bool) -> None:
        self.bao("%s MO %s %s\nqty=%.6f @ %.4f\nSL=%.4f  TP=%.4f\nchien luoc: %s"
                 % ("[DRY-RUN]" if dry_run else "[LENH]", side, symbol,
                    qty, gia, sl, tp, chien_luoc))

    def dong_lenh(self, symbol: str, side: str, qty: float, gia_vao: float,
                  gia_ra: float, pnl: float, ly_do: str, dry_run: bool) -> None:
        self.bao("%s DONG %s %s\n%.4f -> %.4f\nPnL: %+.2f USDT\nly do: %s"
                 % ("[DRY-RUN]" if dry_run else "[LENH]", side, symbol,
                    gia_vao, gia_ra, pnl, ly_do))

    def nhat_ky(self, noi_dung: str, gioi_han: int = 3500) -> None:
        """Nhat ky dem. Telegram gioi han 4096 ky tu moi tin nhan."""
        if len(noi_dung) > gioi_han:
            noi_dung = noi_dung[:gioi_han] + "\n... (cat bot, xem day du trong DB)"
        self.bao("[NHAT KY DEM]\n%s" % noi_dung)
