"""
Doi soat trang thai khi khoi dong - Nang cap 7.

Kich ban that: bot crash luc dang giu vi the, khoi dong lai, khong biet minh
dang co lenh, va mo them lenh nua. Day la mot trong nhung cach mat tien
ngu ngoc nhat, va no xay ra thuong xuyen hon nguoi ta tuong.

NGUYEN TAC: nguon su that la SAN, khong phai file local.
Neu trang thai local va san LECH nhau -> DUNG LAI va bao nguoi.
Khong doan, khong tu dong "sua" - vi doan sai luc nay ton tien that.
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, List

from .risk_manager import Position

logger = logging.getLogger(__name__)


@dataclass
class ReconcileResult:
    ok: bool
    exchange_positions: Dict[str, Position] = field(default_factory=dict)
    discrepancies: List[str] = field(default_factory=list)
    message: str = ""


def doc_vi_the_tu_san(client, cfg) -> Dict[str, Position]:
    """Doc vi the dang mo TU SAN. Loi duoc nem len tren, KHONG nuot.

    Tach rieng khoi reconcile() vi position_manager.py can dung y het phep doc
    nay o moi vong lap. Hai ban sao cua cung mot phep doc la hai co hoi de
    chung lech nhau - va luc chung lech thi mot ben se nghi bot dang trang tay
    trong khi ben kia biet no dang giu hang.
    """
    ra: Dict[str, Position] = {}
    if cfg.CATEGORY == "spot":
        balances = client.get_spot_balances()
        # Voi spot, coi moi so du coin khac USDT (tren nguong bui) la mot vi the
        for coin, amount in balances.items():
            if coin in ("USDT", "USDC"):
                continue
            symbol = "%sUSDT" % coin
            price = client.get_last_price(symbol)
            if price is None or amount * price < 10:  # bo qua so du bui
                continue
            ra[symbol] = Position(
                symbol=symbol, side="Buy", qty=amount, entry_price=price,
                stop_loss=0.0, take_profit=0.0, strategy="unknown",
            )
    else:
        for p in client.get_open_positions():
            symbol = p["symbol"]
            ra[symbol] = Position(
                symbol=symbol,
                side="Buy" if p["side"] == "Buy" else "Sell",
                qty=float(p["size"]),
                entry_price=float(p["avgPrice"]),
                stop_loss=float(p.get("stopLoss") or 0) or 0.0,
                take_profit=float(p.get("takeProfit") or 0) or 0.0,
                strategy="unknown",
            )
    return ra


def reconcile(client, storage=None, cfg=None) -> ReconcileResult:
    """Doc vi the that tu san va so sanh voi trang thai bot nghi minh dang co."""
    import config as default_cfg
    cfg = cfg or default_cfg

    result = ReconcileResult(ok=True)

    if client is None:
        result.message = "khong co ket noi san - bo qua doi soat (che do backtest/dry-run)"
        return result

    try:
        result.exchange_positions = doc_vi_the_tu_san(client, cfg)
    except Exception as e:
        result.ok = False
        result.message = "khong doc duoc trang thai tu san: %s" % e
        logger.error(result.message)
        return result

    try:
        open_orders = client.get_open_orders()
    except Exception as e:
        # KHONG duoc coi "doc that bai" la "khong co lenh cho". Neu tren san
        # dang co lenh cho ma ta khong doc duoc, bot se dat them lenh chong len
        # - dung kich ban ma module nay sinh ra de ngan.
        result.ok = False
        result.message = "khong doc duoc lenh cho tu san: %s" % e
        logger.error(result.message)
        return result

    if result.exchange_positions:
        result.discrepancies.append(
            "San dang co %d vi the: %s"
            % (len(result.exchange_positions), ", ".join(result.exchange_positions)))
    if open_orders:
        result.discrepancies.append("San dang co %d lenh cho" % len(open_orders))

    # Vi the khong co stop-loss la rui ro khong kiem soat duoc -> canh bao manh
    unprotected = [s for s, p in result.exchange_positions.items() if not p.stop_loss]
    if unprotected:
        result.discrepancies.append(
            "CANH BAO: vi the KHONG co stop-loss: %s" % ", ".join(unprotected))

    result.message = ("; ".join(result.discrepancies)
                      if result.discrepancies else "khong co vi the/lenh cho nao tren san")
    logger.info("Doi soat: %s", result.message)
    return result
