"""
Wrapper quanh pybit - tach phan con lai cua bot khoi chi tiet API cua Bybit.
Doi sang ccxt hay san khac chi can sua file nay.

Luu y quan trong ve bao mat: API key phai duoc tao voi quyen GIAO DICH,
TAT quyen RUT TIEN, va bat IP whitelist tro ve IP cua VPS. Neu key bi lo
ma khong co quyen rut tien thi thiet hai bi gioi han.
"""
import logging
import time
from typing import Dict, List, Optional

import pandas as pd

import config

logger = logging.getLogger(__name__)

try:
    from pybit.unified_trading import HTTP
    PYBIT_AVAILABLE = True
except ImportError:  # cho phep chay backtest/test ma khong can cai pybit
    HTTP = None
    PYBIT_AVAILABLE = False


_PHUT_THEO_CHU = {"D": 1440, "W": 10080, "M": 43200}


def _interval_ms(interval: str) -> int:
    iv = str(interval).upper().strip()
    return _PHUT_THEO_CHU.get(iv, int(iv) if iv.isdigit() else 60) * 60 * 1000


class BybitClient:
    def __init__(self, api_key: str = None, api_secret: str = None,
                 testnet: bool = None, cfg=config):
        if not PYBIT_AVAILABLE:
            raise ImportError("Chua cai pybit. Chay: pip install pybit")
        self.cfg = cfg
        self.testnet = cfg.BYBIT_TESTNET if testnet is None else testnet
        self.session = HTTP(
            testnet=self.testnet,
            api_key=api_key or cfg.BYBIT_API_KEY,
            api_secret=api_secret or cfg.BYBIT_API_SECRET,
        )
        logger.info("BybitClient san sang (testnet=%s, category=%s)", self.testnet, cfg.CATEGORY)

    # ---------- du lieu thi truong ----------
    def get_klines(self, symbol: str, interval: str = None, limit: int = None,
                   category: str = None) -> pd.DataFrame:
        """Lay nen va tra ve DataFrame chuan hoa, sap xep tang dan theo thoi gian.

        CHU Y: Bybit tra ve ca cay nen DANG CHAY (chua dong). Ham nay LOAI BO
        cay nen cuoi cung de moi tinh toan chi dung nen da dong - day la mot
        trong nhung nguon lookahead bias pho bien nhat khi trade that.
        """
        resp = self.session.get_kline(
            category=category or self.cfg.CATEGORY,
            symbol=symbol,
            interval=interval or self.cfg.KLINE_INTERVAL,
            limit=limit or self.cfg.LOOKBACK_BARS,
        )
        rows = resp.get("result", {}).get("list", [])
        cols = ["timestamp", "open", "high", "low", "close", "volume"]
        if not rows:
            logger.warning("Khong lay duoc kline cho %s", symbol)
            return pd.DataFrame(columns=cols)

        df = pd.DataFrame(rows, columns=cols + ["turnover"]).drop(columns=["turnover"])
        df["timestamp"] = pd.to_numeric(df["timestamp"])
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = df[col].astype(float)
        df = df.sort_values("timestamp").reset_index(drop=True)

        # Bo nen dang chay neu no chua dong.
        # Bybit nhan ca so phut ("60", "240") lan chu ("D", "W", "M"), nen
        # int() truc tiep se vo khi chay khung ngay.
        interval_ms = _interval_ms(interval or self.cfg.KLINE_INTERVAL)
        now_ms = time.time() * 1000
        if len(df) and (now_ms - df["timestamp"].iloc[-1]) < interval_ms:
            df = df.iloc[:-1].reset_index(drop=True)

        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df

    def get_ticker(self, symbol: str, category: str = None) -> Optional[dict]:
        resp = self.session.get_tickers(category=category or self.cfg.CATEGORY, symbol=symbol)
        rows = resp.get("result", {}).get("list", [])
        return rows[0] if rows else None

    def get_last_price(self, symbol: str) -> Optional[float]:
        t = self.get_ticker(symbol)
        return float(t["lastPrice"]) if t and "lastPrice" in t else None

    def get_instrument_info(self, symbol: str, category: str = None) -> Optional[dict]:
        """Lay buoc nhay khoi luong/gia de lam tron lenh cho dung chuan san."""
        resp = self.session.get_instruments_info(
            category=category or self.cfg.CATEGORY, symbol=symbol)
        rows = resp.get("result", {}).get("list", [])
        return rows[0] if rows else None

    # ---------- tai khoan ----------
    def get_equity(self, account_type: str = "UNIFIED") -> Optional[float]:
        try:
            resp = self.session.get_wallet_balance(accountType=account_type)
            rows = resp.get("result", {}).get("list", [])
            if not rows:
                return None
            total = rows[0].get("totalEquity") or rows[0].get("totalWalletBalance")
            return float(total) if total else None
        except Exception as e:
            logger.error("Loi lay so du: %s", e)
            return None

    def kiem_tra_ket_noi(self, account_type: str = "UNIFIED") -> dict:
        """Thu goi mot endpoint CAN KHOA, tra ve {"ok", "chi_tiet"}.

        Khac get_equity() o dung mot cho: get_equity() nuot moi loi thanh None
        vi bot goi no moi vong va khong duoc phep sap vi mot loi mang. O day
        thi nguoc lai - LOI chinh la thu ta can, vi "khoa sai" va "tai khoan
        rong" deu cho so du None nhung cach sua khac han nhau.
        """
        # Hoi /v5/user/query-api TRUOC. Endpoint nay chi doi khoa hop le, khong
        # doi quyen gi ca, nen no tach duoc hai kieu hong ma so du gop chung
        # thanh mot loi 401 kho hieu:
        #     khoa KHONG TON TAI tren san nay (nham testnet voi mainnet)
        #     khoa co that nhung THIEU QUYEN, hoac sai loai tai khoan
        # Hai cai do sua theo hai cach hoan toan khac nhau, va doan nham thi
        # nguoi dung se di tim quyen trong khi van de la ho dang o nham san.
        try:
            info = self.session.get_api_key_information()
            ma_info = str(info.get("retCode", ""))
            if ma_info not in ("0", ""):
                return {"ok": False, "khoa_khong_ton_tai": True,
                        "chi_tiet": "khoa khong hop le tren san nay (retCode %s): %s"
                                    % (ma_info, str(info.get("retMsg", ""))[:100])}
        except Exception as e:
            loi = str(e)
            # 10003 = "API key is invalid": khoa khong ton tai o day. Day la cau
            # tra loi dut khoat nhat ta co the lay duoc, nen noi thang.
            if "10003" in loi or "invalid" in loi.lower():
                return {
                    "ok": False, "khoa_khong_ton_tai": True,
                    "chi_tiet": "Bybit khong nhan ra khoa nay (10003). Khoa testnet "
                                "phai duoc tao tai testnet.bybit.com - do la mot he "
                                "thong rieng, tai khoan mainnet khong dung duoc.",
                }
            return {"ok": False, "chi_tiet": "khong hoi duoc thong tin khoa: %s"
                                             % loi[:140]}

        try:
            resp = self.session.get_wallet_balance(accountType=account_type)
        except Exception as e:
            return {"ok": False,
                    "chi_tiet": "khoa hop le nhung khong doc duoc so du %s: %s. "
                                "Thuong la thieu quyen doc Wallet, hoac tai khoan "
                                "khong phai loai %s."
                                % (account_type, str(e)[:110], account_type)}

        ma = str(resp.get("retCode", ""))
        if ma not in ("0", ""):
            return {"ok": False, "chi_tiet": "Bybit tu choi (retCode %s): %s"
                                             % (ma, str(resp.get("retMsg", ""))[:120])}
        rows = resp.get("result", {}).get("list", [])
        if not rows:
            return {"ok": False, "chi_tiet": "khoa dung nhung tai khoan khong tra ve du lieu so du"}
        total = rows[0].get("totalEquity") or rows[0].get("totalWalletBalance")
        return {"ok": True, "chi_tiet": "so du %.2f USDT" % float(total or 0)}

    def get_open_positions(self, category: str = None) -> List[dict]:
        """Vi the dang mo THEO SAN - day la nguon su that cho reconciliation."""
        cat = category or self.cfg.CATEGORY
        if cat == "spot":
            return []  # spot khong co khai niem 'position', dung so du coin
        resp = self.session.get_positions(category=cat, settleCoin="USDT")
        rows = resp.get("result", {}).get("list", [])
        return [r for r in rows if float(r.get("size", 0)) > 0]

    def get_spot_balances(self, account_type: str = "UNIFIED") -> Dict[str, float]:
        """So du tung coin - dung de doi soat vi the spot.

        CO Y de loi bay len tren thay vi tra ve {}. Doi soat khong duoc phep
        nham "khong doc duoc" voi "khong co vi the nao": nham hai cai do nghia
        la bot tuong minh dang trang tay trong khi thuc te dang giu hang.
        """
        resp = self.session.get_wallet_balance(accountType=account_type)
        rows = resp.get("result", {}).get("list", [])
        if not rows:
            return {}
        out = {}
        for coin in rows[0].get("coin", []):
            amount = float(coin.get("walletBalance", 0) or 0)
            if amount > 0:
                out[coin["coin"]] = amount
        return out

    def get_open_orders(self, category: str = None) -> List[dict]:
        resp = self.session.get_open_orders(category=category or self.cfg.CATEGORY)
        return resp.get("result", {}).get("list", [])

    # ---------- dat lenh ----------
    def place_order(self, symbol: str, side: str, qty: str, order_type: str = "Market",
                    category: str = None, take_profit: str = None, stop_loss: str = None,
                    order_link_id: str = None, reduce_only: bool = False) -> dict:
        """Dat lenh that.

        KHONG goi truc tiep ham nay tu logic chien luoc - luon di qua
        Executor de dam bao da qua RiskManager va co orderLinkId chong lenh trung.
        """
        params = {
            "category": category or self.cfg.CATEGORY,
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "qty": str(qty),
        }
        if take_profit:
            params["takeProfit"] = str(take_profit)
        if stop_loss:
            params["stopLoss"] = str(stop_loss)
        if order_link_id:
            params["orderLinkId"] = order_link_id
        if reduce_only:
            params["reduceOnly"] = True
        return self.session.place_order(**params)

    def cancel_all(self, symbol: str = None, category: str = None) -> dict:
        params = {"category": category or self.cfg.CATEGORY}
        if symbol:
            params["symbol"] = symbol
        return self.session.cancel_all_orders(**params)
