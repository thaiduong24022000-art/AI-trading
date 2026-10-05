"""
Quan ly VONG DOI vi the o ban live - phan tung thieu han giua backtest va bot that.

VAN DE MA FILE NAY SUA:
Truoc file nay, main.py chi biet MO lenh. Khong cho nao goi remove_position(),
record_trade_result() hay log_trade() - ba ham do chi duoc goi trong
backtest/engine.py va trong test. Hau qua that su, khong phai ly thuyet:

  1. Portfolio heat chi tang, khong bao gio giam. Sau MAX_OPEN_POSITIONS lenh
     (mac dinh 3), risk.evaluate() tu choi MOI tin hieu moi - vinh vien. Bot
     giao dich 3 lan roi im lang, va nhin tu ben ngoai thi giong het mot bot
     "khong tim thay tin hieu nao".
  2. Bang `trades` khong bao gio co dong nao -> strategy_performance() rong ->
     allocator khong co du lieu hieu suat de doi trong so -> Nang cap 2 chi
     chay tren giay.
  3. record_trade_result() khong bao gio duoc goi -> circuit breaker
     MAX_CONSECUTIVE_LOSSES la code chet o ban live.
  4. Nhat ky hang dem doc trades_of_day() -> luon rong -> LLM khong co gi de
     phe binh.

KHAC BIET LIVE/BACKTEST QUAN TRONG HON CA:
backtest/engine.py dong vi the o BA truong hop: stop_loss, take_profit va
`signal_reverse` (tin hieu dao chieu). Ban live truoc day khong lam cai thu ba.
Nghia la moi con so walk-forward da tinh deu mo ta MOT CHIEN LUOC KHAC voi cai
dang chay that. Khong the ky vong kiem duoc cai ma backtest do, neu ban live
chay mot chien luoc khac.

NGUYEN TAC GIU NGUYEN TU reconciliation.py: nguon su that la SAN. O che do
tien that, vi the bien mat khoi san = da dong (cham SL/TP dat kem lenh). Bot
KHONG tu suy dien ket qua tu gia local roi tin do la that.

CHE DO DRY-RUN: khong co vi the that tren san de doc, nen o day MO PHONG y het
cach backtest lam - kiem tra high/low cua nen vua dong voi gia dinh bi quan
(cham ca SL lan TP trong mot nen thi tinh la SL truoc). Nho vay dry-run chay
tron mot vong doi lenh day du thay vi treo mai o 3 vi the.
"""
import logging
import time
from typing import Dict, Optional, Tuple

import pandas as pd

import config
from .reconciliation import doc_vi_the_tu_san
from .risk_manager import Position
from .strategies.base import BUY, SELL

logger = logging.getLogger(__name__)

# Ly do thoat - dung chung tu vung voi backtest/engine.py de hai ben so sanh duoc.
STOP_LOSS = "stop_loss"
TAKE_PROFIT = "take_profit"
SIGNAL_REVERSE = "signal_reverse"
DONG_TREN_SAN = "dong_tren_san"      # san bao het vi the, khong ro SL hay TP
STOP_PHIA_BOT = "stop_phia_bot"      # luoi an toan: stop cua san khong chay
DONG_THU_CONG = "dong_thu_cong"


class PositionManager:
    """Theo doi vi the dang mo, phat hien lenh da dong, va ghi nhan ket qua.

    Doi tuong nay KHONG tu quyet dinh mo lenh - do la viec cua risk engine va
    executor. No chi lo phan duoi cua vong doi: dong, ghi so, va tra lai heat.
    """

    def __init__(self, client=None, executor=None, storage=None, risk=None,
                 breaker=None, cfg=config, notifier=None):
        self.client = client
        self.executor = executor
        self.storage = storage
        self.risk = risk
        self.breaker = breaker
        self.cfg = cfg
        self.notifier = notifier

    # ---------- tinh toan ----------
    def _pnl(self, pos: Position, gia_thoat: float) -> float:
        """PnL rong sau phi hai chieu - cung cong thuc voi backtest/engine.py.

        Phi tinh ca hai dau: neu chi tru phi thoat thi moi lenh se dep hon
        thuc te dung mot lan phi vao, va sai lech do don lai qua hang tram lenh
        thanh mot duong von hoan toan khong co that.
        """
        if pos.side == "Buy":
            gross = (gia_thoat - pos.entry_price) * pos.qty
        else:
            gross = (pos.entry_price - gia_thoat) * pos.qty
        phi = (pos.entry_price + gia_thoat) * pos.qty * self.cfg.FEE_TAKER
        return gross - phi

    def _doan_ly_do(self, pos: Position, gia_thoat: float) -> str:
        """Doan SL hay TP dua tren gia thoat gan nguong nao hon.

        Chi la SUY DOAN: khi doc tu san o vong sau, ta khong biet lenh dong vi
        ly do gi. Doan sai lam thong ke `exit_reason` lech, nen truong hop
        khong ro rang thi tra ve DONG_TREN_SAN chu khong doan bua.
        """
        if not pos.stop_loss or not pos.take_profit:
            return DONG_TREN_SAN
        d_sl = abs(gia_thoat - pos.stop_loss)
        d_tp = abs(gia_thoat - pos.take_profit)
        khoang = abs(pos.take_profit - pos.stop_loss) or 1.0
        # Phai gan ro ret mot ben (trong 20% khoang SL-TP) moi dam ket luan.
        if min(d_sl, d_tp) > 0.2 * khoang:
            return DONG_TREN_SAN
        return STOP_LOSS if d_sl < d_tp else TAKE_PROFIT

    def _ghi_nhan_dong(self, pos: Position, gia_thoat: float, ly_do: str,
                      dry_run: bool) -> float:
        """Ghi so mot lenh da dong va tra heat ve cho danh muc."""
        pnl = self._pnl(pos, gia_thoat)
        if self.storage:
            self.storage.log_trade(
                symbol=pos.symbol, strategy=pos.strategy or "unknown", side=pos.side,
                qty=pos.qty, entry_price=pos.entry_price, exit_price=gia_thoat,
                entry_ts=pos.opened_at, exit_ts=time.time(), pnl=pnl,
                exit_reason=ly_do, dry_run=dry_run)
        if self.breaker:
            self.breaker.record_trade_result(pnl)
        if self.risk:
            self.risk.remove_position(pos.symbol)
        logger.info("DONG %s %s qty=%.6f @ %.4f | %s | pnl=%+.2f USDT%s",
                    pos.side, pos.symbol, pos.qty, gia_thoat, ly_do, pnl,
                    " [dry-run]" if dry_run else "")
        if self.notifier is not None and getattr(self.cfg, "TELEGRAM_BAO_TUNG_LENH", True):
            self.notifier.dong_lenh(pos.symbol, pos.side, pos.qty, pos.entry_price,
                                   gia_thoat, pnl, ly_do, dry_run)
        return pnl

    # ---------- che do dry-run: mo phong y het backtest ----------
    def _mo_phong_thoat(self, frames: Dict[str, pd.DataFrame]) -> int:
        so_dong = 0
        for symbol, pos in list(self.risk.positions.items()):
            df = frames.get(symbol)
            if df is None or df.empty:
                continue
            high = float(df["high"].iloc[-1])
            low = float(df["low"].iloc[-1])

            if pos.side == "Buy":
                cham_sl = pos.stop_loss and low <= pos.stop_loss
                cham_tp = pos.take_profit and high >= pos.take_profit
            else:
                cham_sl = pos.stop_loss and high >= pos.stop_loss
                cham_tp = pos.take_profit and low <= pos.take_profit

            # Gia dinh bi quan giong backtest: cham ca hai trong mot nen -> SL truoc.
            if cham_sl:
                self._ghi_nhan_dong(pos, pos.stop_loss, STOP_LOSS, dry_run=True)
                so_dong += 1
            elif cham_tp:
                self._ghi_nhan_dong(pos, pos.take_profit, TAKE_PROFIT, dry_run=True)
                so_dong += 1
        return so_dong

    # ---------- che do that: san la nguon su that ----------
    def _phat_hien_dong_tren_san(self, frames: Dict[str, pd.DataFrame]) -> Tuple[int, bool]:
        """Tra ve (so lenh da ghi nhan, doc duoc san hay khong)."""
        try:
            tren_san = doc_vi_the_tu_san(self.client, self.cfg)
        except Exception as e:
            # KHONG duoc coi "doc that bai" la "khong con vi the nao" - lam vay
            # se ghi nhan hang loat lenh dong gia va tra heat ve sai. Thay vao
            # do bo qua vong nay va de vong sau thu lai.
            logger.error("Khong doc duoc vi the tu san - bo qua dong bo vong nay: %s", e)
            if self.breaker:
                self.breaker.record_api_error()
            return 0, False

        so_dong = 0
        for symbol, pos in list(self.risk.positions.items()):
            if symbol in tren_san:
                continue  # con mo tren san
            gia_thoat = self._gia_hien_tai(symbol, frames)
            if gia_thoat is None:
                logger.warning("%s da dong tren san nhung khong lay duoc gia thoat "
                               "- giu lai de vong sau xu ly", symbol)
                continue
            self._ghi_nhan_dong(pos, gia_thoat, self._doan_ly_do(pos, gia_thoat),
                               dry_run=False)
            so_dong += 1
        return so_dong, True

    def _ep_stop(self, frames: Dict[str, pd.DataFrame]) -> int:
        """LUOI AN TOAN: tu dong stop khi stop cua SAN khong chay.

        VI SAO CAN, du lenh da gui kem stop-loss len san:
        stop dat o san co the khong ton tai ma bot van tuong la co. Bybit gan
        SL thang vao lenh; OKX quan ly SL bang lenh algo rieng va tham so gan
        kem co the doi ten theo phien ban API. Neu ten truong sai, san van khop
        LENH CHINH va AM THAM bo qua phan SL - ket qua la mot vi the khong co
        bao ve, trong khi log cua bot ghi ro rang no co stop o 95.

        Lop nay khong tin ben nao: no doc gia that va tu dong neu gia da xuyen
        qua stop ma vi the VAN con tren san. Khong dung API dac thu cua san nao
        - chi dung get_klines va place_order, hai duong da chay hang ngay.

        Chi chay o che do that. O dry-run, _mo_phong_thoat() da dong vai tro nay.
        """
        if not getattr(self.cfg, "EP_STOP_PHIA_BOT", True) or self.executor is None:
            return 0

        so = 0
        for symbol, pos in list(self.risk.positions.items()):
            df = frames.get(symbol)
            if df is None or df.empty or not pos.stop_loss:
                continue
            gia = float(df["close"].iloc[-1])
            xuyen = (gia <= pos.stop_loss if pos.side == "Buy" else gia >= pos.stop_loss)
            if not xuyen:
                continue

            logger.error("%s: GIA DA XUYEN STOP (%.4f vs %.4f) ma vi the VAN MO tren "
                         "san - stop cua san khong chay. Bot tu dong.",
                         symbol, gia, pos.stop_loss)
            bar_ts = (float(df["timestamp"].iloc[-1]) if "timestamp" in df.columns
                      else None)
            kq = self.executor.close_position(pos, gia, reason=STOP_PHIA_BOT,
                                              bar_timestamp=bar_ts)
            if not kq.success:
                # Khong ghi nhan la da dong khi san chua xac nhan. Vong sau se
                # thu lai, va nho bar_timestamp thi lan thu lai trong cung cay
                # nen dung dung orderLinkId cu - khong tao lenh trung.
                logger.error("%s: khong dong duoc bang lenh thi truong: %s",
                             symbol, kq.message)
                if self.notifier is not None:
                    self.notifier.bao(
                        "[NGUY HIEM] %s: gia da xuyen stop nhung KHONG dong duoc "
                        "vi the. Can vao san kiem tra ngay.\n%s"
                        % (symbol, kq.message), khoa="ep_stop_%s" % symbol,
                        lap_lai_sau=900)
                continue

            self._ghi_nhan_dong(pos, gia, STOP_PHIA_BOT, dry_run=False)
            so += 1
        return so

    def _gia_hien_tai(self, symbol: str, frames: Dict[str, pd.DataFrame]) -> Optional[float]:
        df = frames.get(symbol)
        if df is not None and not df.empty:
            return float(df["close"].iloc[-1])
        try:
            return self.client.get_last_price(symbol)
        except Exception:
            return None

    # ---------- API chinh ----------
    def dong_bo(self, frames: Dict[str, pd.DataFrame] = None) -> int:
        """Phat hien va ghi nhan cac vi the da dong. Tra ve so lenh da ghi nhan.

        Goi moi vong lap, TRUOC khi xet tin hieu moi - de heat duoc tra lai
        truoc khi risk engine quyet dinh con cho mo lenh moi hay khong.
        """
        if self.risk is None or not self.risk.positions:
            return 0
        frames = frames or {}
        if self.cfg.DRY_RUN:
            return self._mo_phong_thoat(frames)
        # Phat hien lenh da dong TRUOC, ep stop SAU: neu lam nguoc lai, mot vi
        # the vua duoc san dong dung stop van con trong so local va se bi gui
        # them mot lenh dong nua.
        so, doc_duoc_san = self._phat_hien_dong_tren_san(frames)
        if not doc_duoc_san:
            # Khong doc duoc san = dang MU. Trang thai local luc nay co the da
            # cu: vi the co the vua duoc san dong dung stop ma ta chua biet.
            # Gui lenh dong dua tren trang thai cu la hanh dong tren mot thu
            # co the khong con ton tai - doi vong sau, luc nhin duoc lai.
            return so
        return so + self._ep_stop(frames)

    def thoat_khi_dao_chieu(self, symbol: str, action: str, gia: float) -> bool:
        """Dong vi the khi tin hieu dao chieu - buoc `signal_reverse` cua backtest.

        Tra ve True neu vua dong mot vi the. Thieu buoc nay thi ban live chay
        mot chien luoc KHAC voi cai da walk-forward: trend-following se om lenh
        cho cham stop thay vi thoat khi xu huong quay dau.
        """
        pos = self.risk.positions.get(symbol) if self.risk else None
        if pos is None or action not in (BUY, SELL):
            return False
        nguoc_chieu = ((pos.side == "Buy" and action == SELL)
                       or (pos.side == "Sell" and action == BUY))
        if not nguoc_chieu:
            return False

        if not self.cfg.DRY_RUN and self.executor is not None:
            kq = self.executor.close_position(pos, gia, reason=SIGNAL_REVERSE)
            if not kq.success:
                # Khong ghi nhan la da dong khi san chua xac nhan - neu ghi bua,
                # bot se tuong minh trang tay va mo them lenh chong len vi the cu.
                logger.error("%s: khong dong duoc vi the khi dao chieu: %s",
                             symbol, kq.message)
                return False

        self._ghi_nhan_dong(pos, gia, SIGNAL_REVERSE, dry_run=self.cfg.DRY_RUN)
        return True
