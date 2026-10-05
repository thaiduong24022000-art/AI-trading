"""
LLM veto filter - Nang cap 1 (giai doan 4, mac dinh TAT).

VAI TRO CUA LLM O DAY LA GI VA KHONG PHAI LA GI:

  KHONG PHAI: sinh tin hieu mua/ban. Tin lon duoc phan anh vao gia trong vai
  tram mili-giay den vai giay. Duong di cua bot (nguon tin cap nhat -> goi LLM
  -> parse -> gui lenh) cham hon thi truong vai chuc giay den vai phut. Giao dich
  theo tin o do tre do la mua dung dinh cu nhay tin, dung luc nguoi vao truoc
  dang thoat hang.

  LA: lop PHU QUYET. Tin hieu ky thuat da sinh ra lenh; LLM chi tra loi mot cau
  hoi - "co su kien nao khien vao lenh nay la ngu ngoc khong?". Cau hoi nay
  khong can nhanh, chi can dung, va chi bao ky thuat thi hoan toan mu truoc no.

RANG BUOC KIEN TRUC: ham o day chi duoc tra ve QUYET DINH CHAN hoac GIAM QUY MO.
Khong bao gio duoc tao lenh moi. Do la ranh gioi quan trong nhat cua ban v2.
"""
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import List, Optional

import config

logger = logging.getLogger(__name__)

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    anthropic = None
    ANTHROPIC_AVAILABLE = False


VETO_PROMPT = """Ban la bo loc rui ro cho mot he thong giao dich crypto tu dong.

He thong ky thuat vua sinh ra tin hieu sau:
- Ma: {symbol}
- Huong: {side}
- Gia hien tai: {price}
- Ly do ky thuat: {reason}

Boi canh tin tuc 24 gio gan nhat:
{news}

Nhiem vu cua ban: tra loi DUY NHAT cau hoi "co su kien nao dang dien ra khien
viec vao lenh nay la nguy hiem bat thuong khong?".

Chan lenh (veto) CHI khi co dau hieu nghiem trong, vi du: san giao dich gap su co
rut tien, stablecoin mat peg, mot giao thuc/san lon bi hack, tin phap ly dot ngot
anh huong truc tiep den tai san nay, hoac thi truong dang trong trang thai hoang loan.

KHONG chan chi vi tin xau thong thuong, vi ban khong dong y voi huong lenh, hoac
vi thi truong bien dong binh thuong. Nghi ngo thi KHONG chan.

Tra ve DUY NHAT mot doi tuong JSON, khong kem giai thich nao khac:
{{"veto": true/false, "size_multiplier": 0.0-1.0, "confidence": 0.0-1.0, "reason": "mot cau ngan"}}

size_multiplier: 1.0 = giu nguyen quy mo, 0.5 = giam nua, 0.0 = tuong duong veto."""


@dataclass
class VetoResult:
    veto: bool = False
    size_multiplier: float = 1.0
    confidence: float = 0.0
    reason: str = ""
    llm_used: bool = False

    @property
    def allows_trade(self) -> bool:
        return not self.veto and self.size_multiplier > 0.05


def _bool_an_toan(x) -> bool:
    """Ep ve bool ma KHONG dinh bay chuoi.

    LLM tra JSON dang van ban, va "veto": "false" la ket qua rat hay gap.
    bool("false") trong Python la True - tuc la bot se chan SACH moi lenh
    trong khi log van bao "LLM dang chay binh thuong". Day dung kieu hong im
    lang: nhin tu ngoai giong het "hom nay khong co tin hieu nao".
    """
    if isinstance(x, str):
        return x.strip().lower() in ("true", "1", "yes", "co", "chan")
    return bool(x)


def _no_veto(reason: str) -> VetoResult:
    return VetoResult(veto=False, size_multiplier=1.0, reason=reason, llm_used=False)


def _extract_json(text: str) -> Optional[dict]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


class VetoFilter:
    def __init__(self, cfg=config):
        self.cfg = cfg
        self.client = None
        self._cache = {}
        if cfg.ENABLE_LLM_VETO and ANTHROPIC_AVAILABLE and cfg.ANTHROPIC_API_KEY:
            self.client = anthropic.Anthropic(api_key=cfg.ANTHROPIC_API_KEY)

    def check(self, symbol: str, side: str, price: float, reason: str,
              news: List[str] = None) -> VetoResult:
        """Kiem tra mot tin hieu truoc khi cho phep vao lenh."""
        if not self.cfg.ENABLE_LLM_VETO:
            return _no_veto("LLM veto dang tat")
        if self.client is None:
            return _no_veto("chua cau hinh ANTHROPIC_API_KEY hoac chua cai anthropic")

        # Cau hoi veto la ve BOI CANH THI TRUONG (san bi hack, stablecoin mat
        # peg), khong phai ve cay nen. Boi canh do doi cham hon nhieu so voi
        # nhip goi cua bot, nen hoi lai moi ma moi vong chi ton tien va lam
        # cham vong lap. TTL ngan giu tinh cap nhat ma van cat phan lon so goi.
        ttl = getattr(self.cfg, "LLM_VETO_CACHE_SECONDS", 900)
        khoa = (symbol, side)
        if ttl > 0:
            cu = self._cache.get(khoa)
            if cu and (time.time() - cu[0]) < ttl:
                return cu[1]

        news_text = "\n".join("- %s" % n for n in (news or [])) or "(khong co tin dang chu y)"
        prompt = VETO_PROMPT.format(symbol=symbol, side=side, price=price,
                                    reason=reason, news=news_text)
        try:
            resp = self.client.messages.create(
                model=self.cfg.LLM_MODEL,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
                timeout=self.cfg.LLM_TIMEOUT_SECONDS,
            )
            text = "".join(block.text for block in resp.content if hasattr(block, "text"))
            data = _extract_json(text)
            if not data:
                return self._on_failure("LLM tra ve dinh dang khong doc duoc")

            result = VetoResult(
                veto=_bool_an_toan(data.get("veto", False)),
                size_multiplier=float(data.get("size_multiplier", 1.0)),
                confidence=float(data.get("confidence", 0.0)),
                reason=str(data.get("reason", ""))[:300],
                llm_used=True,
            )
            result.size_multiplier = max(0.0, min(1.0, result.size_multiplier))
            if ttl > 0:
                self._cache[khoa] = (time.time(), result)
            if result.veto:
                logger.warning("LLM CHAN lenh %s %s: %s", side, symbol, result.reason)
            return result

        except Exception as e:
            return self._on_failure("loi goi LLM: %s" % e)

    def _on_failure(self, reason: str) -> VetoResult:
        """LLM hong thi lam gi?

        Mac dinh fail-open: van cho giao dich. Ly do la tin hieu ky thuat moi la
        nguon alpha chinh, con LLM chi la lop loc phu - de LLM hong lam dung ca
        he thong la trao cho no quyen luc lon hon vai tro cua no.
        Doi ben trong .env neu muon than trong hon (LLM_FAIL_OPEN=false).
        """
        logger.warning("VetoFilter that bai (%s) - %s", reason,
                       "van cho giao dich" if self.cfg.LLM_FAIL_OPEN else "chan giao dich")
        if self.cfg.LLM_FAIL_OPEN:
            return _no_veto(reason)
        return VetoResult(veto=True, size_multiplier=0.0, reason=reason, llm_used=False)
