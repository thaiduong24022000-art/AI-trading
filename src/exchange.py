"""
Factory chon client san giao dich theo config.EXCHANGE.

Day la CHO DUY NHAT quyet dinh dung BybitClient hay OkxClient. main.py,
run_backtest.py va cac script tai du lieu deu goi qua day thay vi import
truc tiep tung client - doi san chi can sua .env (EXCHANGE=bybit|okx),
khong phai sua code o nhieu noi.
"""
import config as default_cfg


def build_client(cfg=None, testnet: bool = None):
    """Tao client san dung theo cfg.EXCHANGE.

    testnet, neu truyen vao, ghi de len co testnet/demo mac dinh cua tung
    san (dung khi tai du lieu lich su can mainnet du bot dang chay testnet -
    xem config.DATA_TESTNET va chu thich trong config.py).
    """
    cfg = cfg or default_cfg
    exchange = getattr(cfg, "EXCHANGE", "bybit").strip().lower()

    if exchange == "okx":
        from src.okx_client import OkxClient
        return OkxClient(cfg=cfg, testnet=testnet)
    if exchange == "bybit":
        from src.bybit_client import BybitClient
        return BybitClient(cfg=cfg, testnet=testnet)
    raise ValueError("EXCHANGE=%s khong hop le (chi nhan bybit|okx)" % exchange)
