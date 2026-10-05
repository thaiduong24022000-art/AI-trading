"""
Wrapper quanh OKX REST API v5 - CUNG GIAO DIEN voi BybitClient (xem
src/bybit_client.py) de main.py, executor.py, reconciliation.py,
run_backtest.py, datafeed.py dung duoc ma khong phai sua gi o cac file do.
Chon san nao chay o src/exchange.py, dieu khien bang config.EXCHANGE.

DA KIEM CHUNG TREN OKX THAT (2026-09-08, qua nut "Thu ket noi san" o web UI):
  - Duong cong khai chay: /market/ticker tra ve gia BTC that, tuc anh xa
    BTCUSDT -> BTC-USDT va toan bo phan goi HTTP dung.
  - Duong rieng tu di den duoc buoc tra cuu khoa: OKX doc header
    OK-ACCESS-KEY roi tra ve 50111 "Invalid OK-ACCESS-KEY" cho mot khoa gia.
    Dieu nay chung minh header dung DINH DANG - NHUNG CHUA chung minh chu ky
    HMAC dung, vi OKX tu choi o buoc khoa TRUOC khi kiem chu ky. Chi mot khoa
    that moi tra loi duoc cau do.

VAN CHUA KIEM CHUNG - BAT BUOC chay thu tren OKX DEMO TRADING (OKX_DEMO=true)
va doc ky response tra ve truoc khi dat DRY_RUN=false:

  1. Chu ky HMAC tren duong rieng tu - can mot khoa that (xem tren).
  2. TP/SL dinh kem lenh qua "attachAlgoOrds" trong place_order() - ten
     truong con (tpTriggerPx/tpOrdPx/slTriggerPx/slOrdPx) can doi chieu lai
     voi tai lieu OKX moi nhat. Neu sai ten truong, OKX co the AM THAM bo
     qua TP/SL ma lenh chinh van khop - kiem tra bang cach doc lai lenh sau
     khi dat va xac nhan co lenh algo di kem.
  3. Gioi han so nen moi lan goi /market/history-candles dang de 100 - OKX
     co the cho phep nhieu hon, kiem tra lai neu can toc do tai du lieu.
  4. Mapping khung ngay/tuan/thang (D/W/M) it duoc dung toi (bot dang chay
     khung "240" = 4H la chinh) - uu tien kiem chung khung phut/gio truoc.
  5. tdMode mac dinh cho SWAP la "cross" - doi "isolated" trong .env neu can.

KHAC BIET KIEN TRUC QUAN TRONG - vi the OKX KHONG mang theo stopLoss/
takeProfit nhu Bybit (OKX quan ly TP/SL bang lenh algo rieng, tach khoi vi
the). Vi vay get_open_positions() o day LUON tra stopLoss/takeProfit rong,
va reconciliation.py se LUON canh bao "vi the khong co stop-loss" cho moi
vi the OKX dang mo. Day la canh bao AN TOAN co chu dich (bao thua con hon bo
sot), khong phai bug - dung tat canh bao do di.

Bao mat: giong het Bybit - API key OKX phai TAT quyen rut tien (Withdraw),
BAT IP whitelist neu chay tren VPS. Passphrase (OKX bat buoc, Bybit thi
khong) nhay cam ngang API secret - cung nam trong .env, cung khong commit.
"""
import base64
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd
import requests

import config

logger = logging.getLogger(__name__)

BASE_URL = "https://www.okx.com"

# khung Bybit (so phut dang chuoi, hoac D/W/M) -> khung OKX
_KHUNG_OKX = {
    "1": "1m", "3": "3m", "5": "5m", "15": "15m", "30": "30m",
    "60": "1H", "120": "2H", "240": "4H", "360": "6H", "720": "12H",
    "D": "1Dutc", "W": "1Wutc", "M": "1Mutc",
}


def _interval_ms_okx(interval: str) -> int:
    phut_theo_chu = {"D": 1440, "W": 10080, "M": 43200}
    iv = str(interval).upper().strip()
    return phut_theo_chu.get(iv, int(iv) if iv.isdigit() else 60) * 60 * 1000


def _to_okx_symbol(symbol: str, inst_type: str) -> str:
    """BTCUSDT -> BTC-USDT (SPOT) hoac BTC-USDT-SWAP (SWAP).

    Bot chi dung cap voi USDT (xem config.SYMBOLS), nen tach 4 ky tu cuoi
    "USDT" la du - khong can bang anh xa base/quote day du.
    """
    sym = symbol.upper().strip()
    base = sym[:-4] if sym.endswith("USDT") else sym
    inst_id = "%s-USDT" % base
    if inst_type.upper() == "SWAP":
        inst_id += "-SWAP"
    return inst_id


def _from_okx_symbol(inst_id: str) -> str:
    """BTC-USDT hoac BTC-USDT-SWAP -> BTCUSDT (khop dinh dang noi bo cua bot)."""
    return (inst_id or "").replace("-SWAP", "").replace("-", "")


class _OkxSession:
    """Shim noi bo: cho datafeed.download_history() goi client.session.get_kline(...)
    y het cach no goi tren BybitClient, nen file datafeed.py khong phai sua gi.
    Xem tests/test_datafeed.py::FakeSession de doi chieu dung contract.
    """

    def __init__(self, client: "OkxClient"):
        self._c = client

    def get_kline(self, category: str = None, symbol: str = None,
                  interval: str = None, limit: int = 200, end: int = None) -> dict:
        rows = self._c._raw_candles(symbol, interval, limit=limit, after_ts=end)
        # Dinh dang lai giong y het list tra ve tu Bybit (7 cot, turnover bo qua)
        # de datafeed.download_history() doc duoc khong doi logic.
        out_rows = [[r[0], r[1], r[2], r[3], r[4], r[5], "0"] for r in rows]
        return {"result": {"list": out_rows}}


class OkxClient:
    def __init__(self, api_key: str = None, api_secret: str = None,
                passphrase: str = None, testnet: bool = None, cfg=config):
        self.cfg = cfg
        self.api_key = api_key or getattr(cfg, "OKX_API_KEY", "")
        self.api_secret = api_secret or getattr(cfg, "OKX_API_SECRET", "")
        self.passphrase = passphrase or getattr(cfg, "OKX_API_PASSPHRASE", "")
        self.demo = getattr(cfg, "OKX_DEMO", True) if testnet is None else testnet

        # Dung chung config.CATEGORY voi Bybit ("spot"|"linear") thay vi bay
        # them mot bien rieng cho OKX - tranh hai config lech nhau ma
        # reconciliation.py chi doc CATEGORY de quyet dinh goi ham nao.
        self.inst_type = "SPOT" if getattr(cfg, "CATEGORY", "spot") == "spot" else "SWAP"
        self.td_mode = "cash" if self.inst_type == "SPOT" else getattr(cfg, "OKX_TD_MODE", "cross")
        self.session = _OkxSession(self)
        logger.info("OkxClient san sang (demo=%s, inst_type=%s, td_mode=%s)",
                    self.demo, self.inst_type, self.td_mode)

    # ---------- ky va goi HTTP ----------
    def _timestamp(self) -> str:
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (now.microsecond // 1000))

    def _sign(self, ts: str, method: str, path: str, body: str = "") -> str:
        msg = ts + method.upper() + path + body
        mac = hmac.new(self.api_secret.encode(), msg.encode(), hashlib.sha256)
        return base64.b64encode(mac.digest()).decode()

    def _auth_headers(self, method: str, path_with_query: str, body: str = "") -> dict:
        ts = self._timestamp()
        h = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": self._sign(ts, method, path_with_query, body),
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }
        if self.demo:
            h["x-simulated-trading"] = "1"
        return h

    def _request(self, method: str, path: str, params: dict = None,
                body: dict = None, auth: bool = True, timeout: int = 15) -> dict:
        query = ""
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                query = "?" + "&".join("%s=%s" % (k, v) for k, v in clean.items())
        body_str = json.dumps(body) if body else ""
        url = BASE_URL + path + query

        headers = (self._auth_headers(method, path + query, body_str) if auth
                  else {})
        try:
            resp = requests.request(method, url, headers=headers,
                                    data=body_str if body_str else None, timeout=timeout)
            data = resp.json()
        except Exception as e:
            logger.error("Loi goi OKX %s %s: %s", method, path, e)
            raise

        if str(data.get("code")) not in ("0", "None"):
            logger.warning("OKX tra ve loi: code=%s msg=%s (%s %s)",
                           data.get("code"), data.get("msg"), method, path)
        return data

    # ---------- du lieu thi truong (khong can API key) ----------
    def _raw_candles(self, symbol: str, interval: str, limit: int = 100,
                     after_ts: int = None) -> List[list]:
        """Goi /market/history-candles, tra ve list row THO cua OKX (chua sap xep).

        after_ts, neu co, nghia la "chi lay nen CU HON moc nay" - cung y
        nghia voi tham so 'end' cua Bybit trong datafeed.download_history,
        dung de phan trang lui ve qua khu.
        """
        bar = _KHUNG_OKX.get(str(interval).upper(), str(interval))
        inst_id = _to_okx_symbol(symbol, self.inst_type)
        params = {"instId": inst_id, "bar": bar, "limit": min(int(limit or 100), 100)}
        if after_ts:
            params["after"] = int(after_ts)
        data = self._request("GET", "/api/v5/market/history-candles",
                             params=params, auth=False)
        return data.get("data", []) or []

    def get_klines(self, symbol: str, interval: str = None, limit: int = None,
                   category: str = None) -> pd.DataFrame:
        """Lay nen, tra ve DataFrame CUNG SHAPE voi BybitClient.get_klines
        (cot: timestamp/open/high/low/close/volume/datetime, tang dan thoi gian).

        Bo nen dang chay: row OKX co san truong 'confirm' ("0"=chua dong,
        "1"=da dong") - dung thang truong do thay vi phai doan qua timestamp
        nhu ben Bybit (Bybit khong tra truong nay).
        """
        rows = self._raw_candles(symbol, interval or self.cfg.KLINE_INTERVAL,
                                 limit=limit or self.cfg.LOOKBACK_BARS)
        cols = ["timestamp", "open", "high", "low", "close", "volume"]
        if not rows:
            logger.warning("Khong lay duoc kline OKX cho %s", symbol)
            return pd.DataFrame(columns=cols)

        # row OKX: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
        recs = []
        for r in rows:
            confirm = r[8] if len(r) > 8 else None
            recs.append({"timestamp": int(r[0]), "open": float(r[1]),
                        "high": float(r[2]), "low": float(r[3]),
                        "close": float(r[4]), "volume": float(r[5]),
                        "_confirm": confirm})
        df = pd.DataFrame(recs).sort_values("timestamp").reset_index(drop=True)

        if len(df):
            confirm_cuoi = df["_confirm"].iloc[-1]
            if confirm_cuoi is not None:
                if str(confirm_cuoi) == "0":
                    df = df.iloc[:-1].reset_index(drop=True)
            else:
                # du phong neu OKX doi format va bo truong confirm: doan qua
                # timestamp giong cach BybitClient dang lam.
                interval_ms = _interval_ms_okx(interval or self.cfg.KLINE_INTERVAL)
                now_ms = time.time() * 1000
                if (now_ms - df["timestamp"].iloc[-1]) < interval_ms:
                    df = df.iloc[:-1].reset_index(drop=True)

        df = df.drop(columns=["_confirm"])
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df

    def get_ticker(self, symbol: str, category: str = None) -> Optional[dict]:
        inst_id = _to_okx_symbol(symbol, self.inst_type)
        data = self._request("GET", "/api/v5/market/ticker",
                             params={"instId": inst_id}, auth=False)
        rows = data.get("data", [])
        return rows[0] if rows else None

    def get_last_price(self, symbol: str) -> Optional[float]:
        t = self.get_ticker(symbol)
        return float(t["last"]) if t and t.get("last") else None

    def get_instrument_info(self, symbol: str, category: str = None) -> Optional[dict]:
        """Tra ve dict CUNG SHAPE voi Bybit (lotSizeFilter.qtyStep/minOrderQty)
        de executor._round_qty() doc duoc khong phai sua gi.
        """
        inst_id = _to_okx_symbol(symbol, self.inst_type)
        data = self._request("GET", "/api/v5/public/instruments",
                             params={"instType": self.inst_type, "instId": inst_id},
                             auth=False)
        rows = data.get("data", [])
        if not rows:
            return None
        r = rows[0]
        return {
            "lotSizeFilter": {"qtyStep": r.get("lotSz"), "minOrderQty": r.get("minSz")},
            "priceFilter": {"tickSize": r.get("tickSz")},
        }

    # ---------- tai khoan (can API key) ----------
    def get_equity(self, account_type: str = None) -> Optional[float]:
        try:
            data = self._request("GET", "/api/v5/account/balance")
            rows = data.get("data", [])
            if not rows:
                return None
            total = rows[0].get("totalEq")
            return float(total) if total else None
        except Exception as e:
            logger.error("Loi lay so du OKX: %s", e)
            return None

    def kiem_tra_ket_noi(self) -> dict:
        """Thu goi mot endpoint CAN KHOA, tra ve {"ok", "chi_tiet"}.

        Khac get_equity() o dung mot cho: get_equity() nuot moi loi thanh None
        vi bot goi no moi vong va khong duoc phep sap vi mot loi mang. O day
        thi nguoc lai - MA LOI chinh la thu ta can, vi "khoa sai" va "tai khoan
        rong" deu cho so du None nhung cach sua khac han nhau.
        """
        try:
            data = self._request("GET", "/api/v5/account/balance")
        except Exception as e:
            return {"ok": False, "chi_tiet": "khong goi duoc OKX: %s" % str(e)[:120]}

        code = str(data.get("code", ""))
        if code not in ("0", ""):
            return {"ok": False, "chi_tiet": "OKX tu choi (code %s): %s"
                                             % (code, str(data.get("msg", ""))[:120])}
        rows = data.get("data", [])
        if not rows:
            return {"ok": False, "chi_tiet": "khoa dung nhung tai khoan khong tra ve du lieu so du"}
        total = rows[0].get("totalEq")
        return {"ok": True, "chi_tiet": "so du %.2f USDT" % float(total or 0)}

    def get_open_positions(self, category: str = None) -> List[dict]:
        """Vi the dang mo THEO SAN - nguon su that cho reconciliation.

        CHU Y: stopLoss/takeProfit luon rong - xem canh bao dau file ve khac
        biet kien truc OKX/Bybit ve cho luu TP/SL.
        """
        data = self._request("GET", "/api/v5/account/positions",
                             params={"instType": self.inst_type})
        out = []
        for p in data.get("data", []):
            size = float(p.get("pos") or 0)
            if size == 0:
                continue
            pos_side = p.get("posSide", "net")
            if pos_side == "long":
                side = "Buy"
            elif pos_side == "short":
                side = "Sell"
            else:
                side = "Buy" if size > 0 else "Sell"
            out.append({
                "symbol": _from_okx_symbol(p.get("instId", "")),
                "side": side,
                "size": str(abs(size)),
                "avgPrice": p.get("avgPx") or "0",
                "stopLoss": None,
                "takeProfit": None,
            })
        return out

    def get_spot_balances(self, account_type: str = None) -> Dict[str, float]:
        """So du tung dong tien - dung de doi soat vi the spot.

        CO Y de loi bay len tren thay vi tra ve {} (giong Bybit) - doi soat
        khong duoc phep nham "khong doc duoc" voi "khong co vi the nao".
        """
        data = self._request("GET", "/api/v5/account/balance")
        rows = data.get("data", [])
        if not rows:
            return {}
        out = {}
        for d in rows[0].get("details", []):
            amount = float(d.get("cashBal") or d.get("eq") or 0)
            if amount > 0:
                out[d["ccy"]] = amount
        return out

    def get_open_orders(self, category: str = None) -> List[dict]:
        data = self._request("GET", "/api/v5/trade/orders-pending",
                             params={"instType": self.inst_type})
        return data.get("data", [])

    # ---------- dat lenh ----------
    def place_order(self, symbol: str, side: str, qty, order_type: str = "Market",
                    category: str = None, take_profit: str = None, stop_loss: str = None,
                    order_link_id: str = None, reduce_only: bool = False) -> dict:
        """Dat lenh that. Tra ve dict CO retCode/retMsg giong Bybit
        (retCode=0 la thanh cong) de executor.py doc duoc khong phai sua gi.

        KHONG goi truc tiep tu logic chien luoc - luon di qua Executor de dam
        bao da qua RiskManager va co orderLinkId chong lenh trung, y het quy
        tac cua BybitClient.place_order.

        CANH BAO: gan TP/SL qua attachAlgoOrds CHUA duoc kiem chung tren OKX
        that (xem canh bao dau file) - bat buoc test tren OKX DEMO TRADING
        va xac nhan lenh algo di kem thuc su duoc tao truoc khi dung tien that.
        """
        inst_id = _to_okx_symbol(symbol, self.inst_type)
        body = {
            "instId": inst_id,
            "tdMode": self.td_mode,
            "side": side.lower(),
            "ordType": order_type.lower(),
            "sz": str(qty),
        }
        if self.inst_type == "SPOT":
            # Khong dat tgtCcy thi OKX hieu sz cua lenh market-buy la so USDT
            # muon chi, khac voi qty (so luong tai san co so) ma risk_manager
            # tinh ra. base_ccy giu dung ngu nghia "qty la so luong coin".
            body["tgtCcy"] = "base_ccy"
        if order_link_id:
            body["clOrdId"] = order_link_id[:32]  # OKX gioi han 32 ky tu (Bybit 36)
        if reduce_only:
            body["reduceOnly"] = True
        if take_profit or stop_loss:
            algo = {}
            if take_profit:
                algo["tpTriggerPx"] = str(take_profit)
                algo["tpOrdPx"] = "-1"  # -1 = dong bang gia thi truong khi cham nguong
            if stop_loss:
                algo["slTriggerPx"] = str(stop_loss)
                algo["slOrdPx"] = "-1"
            body["attachAlgoOrds"] = [algo]

        data = self._request("POST", "/api/v5/trade/order", body=body)
        top_ok = str(data.get("code")) == "0"
        rows = data.get("data", [])
        order_ok = bool(rows) and str(rows[0].get("sCode")) == "0"
        ret_code = 0 if (top_ok and order_ok) else -1
        ret_msg = (rows[0].get("sMsg") if rows else None) or data.get("msg") or "loi khong ro tu OKX"
        return {"retCode": ret_code, "retMsg": ret_msg, "raw": data}

    def cancel_all(self, symbol: str = None, category: str = None) -> dict:
        """OKX khong co API 'huy tat ca' don le nhu Bybit - phai lay danh
        sach lenh cho roi huy theo lo (toi da 20 lenh moi lan goi).
        """
        orders = self.get_open_orders()
        if symbol:
            inst_id = _to_okx_symbol(symbol, self.inst_type)
            orders = [o for o in orders if o.get("instId") == inst_id]
        if not orders:
            return {"retCode": 0, "retMsg": "khong co lenh cho"}

        raw_results = []
        for i in range(0, len(orders), 20):
            batch = [{"instId": o["instId"], "ordId": o["ordId"]}
                    for o in orders[i:i + 20]]
            raw_results.append(self._request(
                "POST", "/api/v5/trade/cancel-batch-orders", body=batch))
        return {"retCode": 0, "retMsg": "da huy %d lenh" % len(orders), "raw": raw_results}
