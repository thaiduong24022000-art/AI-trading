"""
Vong lap chinh cua bot - AI Trade Bot v2.

THU TU CAC LOP (quan trong):
  du lieu -> chi bao -> regime -> ensemble chien luoc (+ AI POLICY)
  -> allocator -> LLM VETO -> RISK ENGINE -> thuc thi -> ghi log

LLM veto nam SAU khi tin hieu da sinh ra va TRUOC risk engine.
No chi co quyen CHAN hoac GIAM QUY MO, khong bao gio duoc tu tao lenh.
Day la rang buoc kien truc quan trong nhat cua ban v2.

AI policy (Nang cap 5) di vao dung duong ong tren chu khong duoc di tat. Vi tri
cua no trong duong ong phu thuoc POLICY_MODE:
  shadow  chay SONG SONG, chi ghi so, khong nam trong ensemble va khong anh
          huong mot chut nao den trong so cua cac chien luoc luat.
  filter  chay sau ensemble, chi duoc chan hoac giam quy mo - giong LLM veto.
  active  la mot thanh vien binh thuong cua ensemble.
Du o che do nao, policy cung khong bao gio bo qua risk engine hay circuit breaker.

Chay:
    python main.py                # vong lap lien tuc
    python main.py --once         # chay mot vong roi thoat (de test)
"""
import argparse
import logging
import os
import signal
import sys
import time
from datetime import datetime

import config
from src import indicators
from src import notifier as notifier_mod
from src import meta_policy as meta_policy_mod
from src import policy as policy_mod
from src import regime as regime_mod
from src.allocator import allocate, combine_signals
from src.exchange import build_client
from src.executor import Executor
from src.journal import TradingJournal
from src.notifier import Notifier
from src.position_manager import PositionManager
from src.reconciliation import reconcile
from src.risk_manager import CircuitBreaker, RiskManager
from src.sentiment import VetoFilter
from src.storage import Storage
from src.strategies import build_ensemble
from src.strategies.base import BUY, HOLD, SELL

logger = logging.getLogger("bot")
_shutdown = False


def setup_logging() -> None:
    os.makedirs(os.path.dirname(config.LOG_PATH), exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        handlers=[logging.FileHandler(config.LOG_PATH, encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)],
    )


def _handle_signal(signum, frame):
    global _shutdown
    logger.warning("Nhan tin hieu dung (%s) - se thoat sau vong hien tai", signum)
    _shutdown = True


class TradingBot:
    def __init__(self):
        self.storage = Storage()
        self.breaker = CircuitBreaker(config)
        self.risk = RiskManager(config, self.breaker)
        self.strategies = build_ensemble(config.ENABLED_STRATEGIES)
        self.luat_bong = self._tao_luat_bong()
        self.veto = VetoFilter(config)
        self.journal = TradingJournal(self.storage, config)
        self.client = None
        self.executor = None
        self.notifier = Notifier(config)
        self.positions = PositionManager(risk=self.risk, breaker=self.breaker,
                                        storage=self.storage, cfg=config,
                                        notifier=self.notifier)
        self.last_journal_day = None
        self.last_policy_day = None
        self.policy_strategy = self._tao_policy()
        self.bo_loc_meta = self._tao_bo_loc_meta()

    def _tao_luat_bong(self):
        """Chien luoc luat dang o che do BONG - chay song song, chi ghi so.

        CO Y khong nam trong self.strategies, cung ly do voi AI policy che do
        shadow: allocator chuan hoa trong so tren danh sach chien luoc, nen chi
        viec co mat trong danh sach da lam doi trong so cua cac chien luoc that
        - va nhu vay che do bong khong con la bong nua.
        """
        try:
            from src.strategies.kho_luat import BONG, KhoLuat
            ds = [cls() for cls in KhoLuat().bien_dich_theo_trang_thai(BONG)]
            if ds:
                logger.info("Chay %d chien luoc luat o che do BONG: %s",
                            len(ds), ", ".join(s.name for s in ds))
            return ds
        except Exception as e:
            # Kho luat hong khong duoc lam dung bot - do chi la lop quan sat.
            logger.exception("Khong nap duoc kho luat (bo qua): %s", e)
            return []

    def _chay_luat_bong(self, symbol: str, df, i: int, bar_ts: int) -> None:
        """Ghi tin hieu cua chien luoc bong. Khong bao gio anh huong quyet dinh."""
        gia = float(df["close"].iloc[i])
        for st in self.luat_bong:
            try:
                d = st.prepare(df)
                sig = st.generate_at(d, i)
                self.storage.log_shadow_signal(
                    symbol, st.name, sig.action, sig.strength, gia,
                    bar_ts=bar_ts, reason=sig.reason)
                if sig.is_actionable:
                    logger.info("%s | [BONG] %s: %s (%.2f)",
                                symbol, st.name, sig.action, sig.strength)
            except Exception as e:
                logger.exception("Loi o chien luoc bong %s (bo qua): %s", st.name, e)

    def _tao_bo_loc_meta(self):
        """Bo loc meta-label - cham diem tin hieu cua chien luoc luat.

        Khac AI policy o cho no khong bao gio TAO tin hieu, chi cham diem tin
        hieu da co. Vi vay no khong can che do rieng: co champion thi no chay,
        khong co thi tin hieu di tiep nguyen ven. Khong co champion la trang
        thai binh thuong, khong phai loi.
        """
        if not getattr(config, "META_BAT", True):
            return None
        try:
            from src.meta_policy import MetaPolicy
            mp = MetaPolicy(cfg=config)
        except Exception as e:
            logger.exception("Khong tao duoc bo loc meta (bo qua): %s", e)
            return None
        if mp.san_sang:
            logger.info("Bo loc meta: %s (loc tin hieu cua %s)",
                        mp.mo_hinh.phien_ban, ",".join(mp.chien_luoc_nguon))
        return mp

    def _tao_policy(self):
        """Tao lop AI policy va dat no dung vi tri theo POLICY_MODE.

        Che do `shadow` va `filter` CO Y khong nam trong self.strategies. Ly do:
        allocator chuan hoa trong so tren danh sach chien luoc, nen chi viec co
        mat trong danh sach da lam thay doi trong so cua breakout - va nhu vay
        che do bong khong con la bong nua. Muon khong anh huong gi thi phai
        khong co mat, chu khong phai co mat roi tu hua se im lang.
        """
        che_do = getattr(config, "POLICY_MODE", policy_mod.TAT)
        if che_do == policy_mod.TAT:
            return None
        if che_do not in policy_mod.CAC_CHE_DO:
            logger.error("POLICY_MODE=%s khong hop le (chi nhan %s) - tat policy",
                         che_do, ", ".join(policy_mod.CAC_CHE_DO))
            return None

        from src.strategies.ml_policy import MLPolicyStrategy
        st = MLPolicyStrategy(cfg=config)
        if not st.policy.san_sang:
            logger.warning("POLICY_MODE=%s nhung chua co champion dung duoc - "
                           "bot chay thuan chien luoc luat", che_do)
        if che_do == policy_mod.CHU_DONG:
            self.strategies = list(self.strategies) + [st]
        return st

    # ---------- khoi dong ----------
    def startup(self) -> bool:
        logger.info("=" * 60)
        logger.info("AI Trade Bot v2 khoi dong")
        la_testnet = (config.BYBIT_TESTNET if config.EXCHANGE == "bybit"
                     else config.OKX_DEMO)
        logger.info("  san=%s | testnet/demo=%s | dry_run=%s | category=%s",
                    config.EXCHANGE, la_testnet, config.DRY_RUN, config.CATEGORY)
        logger.info("  LLM veto=%s | nhat ky dem=%s",
                    config.ENABLE_LLM_VETO, config.ENABLE_NIGHTLY_JOURNAL)
        pol = self.policy_strategy
        mp = self.bo_loc_meta
        logger.info("  Bo loc meta=%s",
                    mp.mo_hinh.phien_ban if mp and mp.san_sang else "khong co")
        logger.info("  AI policy=%s | champion=%s", config.POLICY_MODE,
                    (pol.policy.mo_hinh.phien_ban if pol and pol.policy.san_sang
                     else "khong co"))
        logger.info("  rui ro/lenh=%.2f%% | heat toi da=%.2f%% | DD ngay toi da=%.2f%%",
                    config.RISK_PER_TRADE * 100, config.MAX_PORTFOLIO_HEAT * 100,
                    config.MAX_DAILY_DRAWDOWN * 100)
        logger.info("  khung=%s | ma=%s | chien luoc=%s",
                    config.KLINE_INTERVAL, ",".join(config.SYMBOLS),
                    ",".join(s.name for s in self.strategies))
        logger.info("=" * 60)

        if not config.DRY_RUN and la_testnet is False:
            logger.warning("!!! DANG CHAY VON THAT TREN MAINNET (san=%s) !!!", config.EXCHANGE)

        try:
            self.client = build_client(config)
            self.executor = Executor(self.client, self.storage, config)
            self.positions.client = self.client
            self.positions.executor = self.executor
        except ImportError as e:
            logger.error("Khong khoi tao duoc ket noi san: %s", e)
            logger.error("Cai dat: pip install -r requirements.txt")
            return False
        except Exception as e:
            logger.error("Loi ket noi san: %s", e)
            return False

        # Doi soat trang thai: nguon su that la SAN, khong phai file local
        rec = reconcile(self.client, self.storage, config)
        if not rec.ok:
            logger.error("Doi soat that bai - DUNG LAI de nguoi kiem tra: %s", rec.message)
            self.notifier.doi_soat_that_bai(rec.message)
            return False
        if rec.exchange_positions:
            logger.warning("San dang co vi the san co: %s", rec.message)
            self.risk.sync_positions(rec.exchange_positions)

        equity = self.client.get_equity()
        if equity is None:
            logger.error("Khong doc duoc so du tai khoan - dung lai")
            return False
        self.breaker.reset_daily(equity)
        logger.info("Von hien tai: %.2f USDT", equity)
        self.notifier.khoi_dong(config.EXCHANGE, la_testnet, config.DRY_RUN,
                                config.SYMBOLS, [s.name for s in self.strategies])
        return True

    # ---------- mot vong quyet dinh ----------
    # ---------- AI policy ----------
    def _chay_policy(self, symbol: str, bar_ts: int, df, i: int):
        """Lay y kien policy va ghi vao so. Tra ve KetQuaPolicy hoac None.

        Ghi CA nhung lan policy noi HOLD. Neu chi ghi luc no vao lenh thi ho so
        ket qua chi con nhung quyet dinh da duoc chon - do la thien lech chon mau,
        va lop theo doi se cham diem mo hinh cao hon thuc te mot cach co he thong.
        """
        st = self.policy_strategy
        if st is None:
            return None
        try:
            # O che do active, generate_at da chay trong vong sinh tin hieu.
            # O cac che do khac policy khong nam trong ensemble nen phai goi rieng.
            if st not in self.strategies:
                st.generate_at(df, i)
            kq = st.y_kien_tho()
            if kq is None:
                return None
            if bar_ts:
                self.storage.log_policy_prediction(symbol, bar_ts, kq,
                                                   che_do=config.POLICY_MODE)
            logger.info("%s | %s", symbol, kq.tom_tat())
            return kq
        except Exception as e:
            # Policy hong khong duoc lam dung vong giao dich. Chien luoc luat
            # van chay binh thuong - do la ly do policy la lop THEM VAO.
            logger.exception("%s: loi o lop policy (bo qua): %s", symbol, e)
            return None

    def _loc_bang_policy(self, kq, action: str, strength: float, reason: str):
        """Che do filter: policy chi duoc CHAN hoac GIAM, khong bao gio tang.

        Ba truong hop:
          nguoc chieu   -> chan han. Mo hinh dang noi chieu kia moi la chieu co
                           ky vong duong; vao lenh nguoc lai la co y chon canh xau.
          khong dong y  -> giam quy mo (policy khong thay du ky vong, nhung cung
                           khong thay bang chung nguoc lai).
          dong chieu    -> giu nguyen. KHONG nhan them: mot lop loc lam tin hieu
                           manh len thi no da tro thanh nguon tin hieu, va nhu vay
                           no phai di qua cong thang cap cua nguon tin hieu.
        """
        if action == HOLD:
            return action, strength, reason
        if not kq.co_y_kien:
            return action, strength, "%s | policy khong y kien (%s)" % (reason, kq.ly_do)

        if kq.action == action:
            return action, strength, "%s | policy dong y" % reason
        if kq.action in (BUY, SELL):
            return HOLD, 0.0, "%s | POLICY CHAN: mo hinh nghieng ve %s" % (reason, kq.action)

        giam = getattr(config, "POLICY_FILTER_GIAM", 0.5)
        return action, strength * giam, "%s | policy giam quy mo x%.2f (%s)" % (
            reason, giam, kq.ly_do)

    def _loc_bang_meta(self, symbol, panel, df, i, regime, signals,
                       action, strength, reason):
        """Cho bo loc meta cham diem tin hieu. Chi duoc CHAN hoac GIAM.

        Bo loc duoc huan luyen tren tin hieu cua mot tap chien luoc cu the, nen
        no chi duoc phep cham diem dung nhung tin hieu do. Neu quyet dinh cuoi
        cung den tu mot chien luoc khac (hoac tu tong hop nhieu chien luoc ma
        chien luoc thang khong nam trong tap huan luyen) thi bo loc dung ngoai -
        cham diem mot thu khac voi thu no da hoc la doan mo.
        """
        mp = self.bo_loc_meta
        if mp is None or not mp.san_sang or action == HOLD or panel is None:
            return action, strength, reason

        thang = max((s for s in signals if s.action == action),
                    key=lambda s: s.strength, default=None)
        if thang is None or thang.strategy not in mp.chien_luoc_nguon:
            return action, strength, reason

        try:
            hang = policy_mod.lay_hang(
                panel, symbol,
                int(df["timestamp"].iloc[i]) if "timestamp" in df.columns else None)
            if hang is None:
                return action, strength, reason
            kq = mp.danh_gia(hang, action, thang.strength, regime)
        except Exception as e:
            # Bo loc hong khong duoc lam dung vong giao dich, va cung khong duoc
            # chan bua - tin hieu di tiep nguyen ven.
            logger.exception("%s: loi o bo loc meta (bo qua): %s", symbol, e)
            return action, strength, reason

        logger.info("%s | %s", symbol, kq.tom_tat())
        if not kq.co_y_kien:
            return action, strength, "%s | bo loc khong y kien (%s)" % (reason, kq.ly_do)
        if kq.quyet_dinh == meta_policy_mod.CHAN:
            return HOLD, 0.0, "%s | BO LOC CHAN: %s" % (reason, kq.ly_do)
        if kq.quyet_dinh == meta_policy_mod.GIAM:
            return action, strength * kq.he_so, "%s | bo loc giam x%.2f (%s)" % (
                reason, kq.he_so, kq.ly_do)
        return action, strength, "%s | bo loc dong y (p=%.3f)" % (reason, kq.p_thang)

    def _xay_panel(self, frames):
        """Panel dac trung cat ngang cho vong nay. None neu policy khong chay."""
        can_panel = (self.policy_strategy is not None
                     or (self.bo_loc_meta is not None and self.bo_loc_meta.san_sang))
        if not can_panel or len(frames) < 2:
            return None
        try:
            return policy_mod.chuan_bi_panel_live(frames, config)
        except Exception as e:
            logger.exception("Khong xay duoc panel dac trung (bo qua policy vong nay): %s", e)
            return None

    def bao_tri_policy(self) -> None:
        """Dien ket qua that cho cac du doan cu va kiem tra co phai ha cap khong.

        Chay hang ngay trong chinh vong lap giao dich, khong phai bang mot cong
        viec ben ngoai ma ai do phai nho bat. Duong ha cap can co ich nhat vao
        luc khong ai dang nhin man hinh.
        """
        if self.policy_strategy is None:
            return
        try:
            from src import continual
            so = continual.dong_ket_qua(self.storage, list(config.SYMBOLS),
                                        config.KLINE_INTERVAL, config)
            kq = continual.theo_doi_champion(self.storage, self.policy_strategy.policy.kho,
                                             config)
            logger.info("Bao tri policy: dien %d ket qua | theo doi champion: %s",
                        so, kq.get("trang_thai"))
            if kq.get("trang_thai") == "da_ha_cap":
                logger.error("CHAMPION DA BI HA CAP -> %s", kq.get("champion_moi"))
                self.policy_strategy.policy.nap_lai()
        except Exception as e:
            logger.exception("Loi bao tri policy (bo qua): %s", e)

    def process_symbol(self, symbol: str, equity: float, df=None, panel=None) -> None:
        if df is None:
            df = self.client.get_klines(symbol)
        if len(df) < indicators.warmup_bars():
            logger.warning("%s: chi co %d nen, can >= %d", symbol, len(df),
                           indicators.warmup_bars())
            return

        df = indicators.add_indicators(df)
        for strat in self.strategies:
            df = strat.prepare(df)
        i = len(df) - 1

        # Circuit breaker: du lieu cu va gia nhay bat thuong
        if "timestamp" in df.columns:
            self.breaker.check_data_freshness(float(df["timestamp"].iloc[i]) / 1000.0)
        bar_range = float(df["high"].iloc[i] - df["low"].iloc[i])
        self.breaker.check_price_jump(bar_range, float(df["atr"].iloc[i]))
        if self.breaker.tripped:
            logger.error("%s: bo qua vi circuit breaker: %s", symbol, self.breaker.reason)
            return

        reg = regime_mod.classify_at(df, i, config)
        bar_ts_nen = int(df["timestamp"].iloc[i]) if "timestamp" in df.columns else 0
        if self.policy_strategy is not None:
            self.policy_strategy.dat_boi_canh(symbol, panel)

        # Chien luoc luat che do bong: ghi so truoc, va hoan toan tach roi
        # khoi duong ra quyet dinh ben duoi.
        if self.luat_bong:
            self._chay_luat_bong(symbol, df, i, bar_ts_nen)

        signals = [s.generate_at(df, i) for s in self.strategies]
        performance = self.storage.strategy_performance()
        alloc = allocate(self.strategies, reg, performance, config)
        action, strength, reason = combine_signals(signals, alloc, config)

        # ----- AI policy: ghi so o moi che do, tac dong chi o che do filter -----
        y_policy = self._chay_policy(symbol, bar_ts_nen, df, i)
        if y_policy is not None and config.POLICY_MODE == policy_mod.LOC:
            action, strength, reason = self._loc_bang_policy(
                y_policy, action, strength, reason)

        # ----- Bo loc meta: cham diem chinh tin hieu vua sinh ra -----
        # Dat SAU ensemble va TRUOC risk engine, cung cho voi LLM veto: no chi
        # duoc lam tin hieu yeu di hoac bien mat, khong bao gio manh len.
        action, strength, reason = self._loc_bang_meta(
            symbol, panel, df, i, reg.regime, signals, action, strength, reason)

        logger.info("%s | regime=%s | quyet dinh=%s (%.2f) | %s",
                    symbol, reg.regime, action, strength, reason)

        if action == HOLD:
            self.storage.log_decision(symbol, HOLD, strength, reg.regime, signals,
                                      alloc.weights, reason=reason)
            return

        price = float(df["close"].iloc[i])
        side = "Buy" if action == BUY else "Sell"

        # ----- Thoat khi tin hieu dao chieu (buoc signal_reverse cua backtest) -----
        # Phai nam TRUOC risk engine: dong vi the nguoc chieu tra heat ve, nho do
        # lenh moi cung chieu tin hieu con cua de duoc duyet. Dat sau risk engine
        # thi lenh moi bi tu choi vi day vi the, roi vi the cu moi duoc dong -
        # va bot bo lo dung cay nen ma backtest gia dinh la no vao lenh.
        if self.positions.thoat_khi_dao_chieu(symbol, action, price):
            logger.info("%s: da thoat vi the nguoc chieu truoc khi xet lenh moi", symbol)

        # ----- LLM veto: chi duoc CHAN hoac GIAM QUY MO -----
        veto_result = self.veto.check(symbol, side, price, reason)
        if not veto_result.allows_trade:
            logger.warning("%s: LLM chan lenh - %s", symbol, veto_result.reason)
            self.storage.log_decision(symbol, action, strength, reg.regime, signals,
                                      alloc.weights, llm_veto=True,
                                      llm_reason=veto_result.reason, reason=reason)
            return
        strength *= veto_result.size_multiplier

        # ----- Risk engine: cong kiem duyet cuoi cung -----
        atr_value = float(df["atr"].iloc[i])
        decision = self.risk.evaluate(symbol, side, price, atr_value, equity, strength)
        if not decision.approved:
            logger.info("%s: risk tu choi - %s", symbol, "; ".join(decision.reasons))
            self.storage.log_decision(symbol, action, strength, reg.regime, signals,
                                      alloc.weights, risk={"rejected": decision.reasons},
                                      reason=reason)
            return

        winner = max((s for s in signals if s.action == action),
                     key=lambda s: s.strength, default=None)
        bar_ts = float(df["timestamp"].iloc[i]) if "timestamp" in df.columns else time.time()
        exec_result = self.executor.open_position(
            symbol, side, decision, price, bar_ts,
            strategy=winner.strategy if winner else "ensemble")

        if exec_result.success and exec_result.position:
            self.risk.register_position(exec_result.position)
            self.breaker.record_api_success()
            if config.TELEGRAM_BAO_TUNG_LENH:
                p = exec_result.position
                self.notifier.mo_lenh(symbol, side, p.qty, p.entry_price, p.stop_loss,
                                      p.take_profit, p.strategy, exec_result.dry_run)
        elif not exec_result.success:
            self.breaker.record_api_error()

        self.storage.log_decision(
            symbol, action, strength, reg.regime, signals, alloc.weights,
            risk={"qty": decision.qty, "stop": decision.stop_loss, "tp": decision.take_profit},
            llm_veto=False, llm_reason=veto_result.reason,
            executed=exec_result.success, reason="%s | %s" % (reason, exec_result.message))

    # ---------- kenh dieu khien tu web UI ----------
    # Danh sach trang CHAT: kenh nay lam bot HANH DONG, nen no phai het suc hep.
    # Khong co lenh nao dong vi the hay doi cau hinh o day - dong vi the la
    # viec cua chien luoc va risk engine, con cau hinh doi thi phai khoi dong
    # lai bot mot cach co y thuc.
    LENH_CHO_PHEP = ("reset_breaker", "nap_lai_kho_luat")

    def _xu_ly_lenh_dieu_khien(self) -> None:
        try:
            cho = self.storage.lenh_cho_xu_ly()
        except Exception as e:
            logger.exception("Khong doc duoc lenh dieu khien (bo qua): %s", e)
            return

        for row in cho:
            lenh = row["lenh"]
            if lenh not in self.LENH_CHO_PHEP:
                self.storage.danh_dau_lenh(row["id"], "tu_choi",
                                           "lenh khong nam trong danh sach cho phep")
                logger.warning("Tu choi lenh dieu khien la: %s", lenh)
                continue
            try:
                if lenh == "reset_breaker":
                    ly_do_cu = self.breaker.reason
                    self.breaker.manual_reset()
                    self.notifier.xoa_dedup(notifier_mod.BREAKER)
                    kq = "da reset breaker (truoc do: %s)" % (ly_do_cu or "khong ngat")
                elif lenh == "nap_lai_kho_luat":
                    self.luat_bong = self._tao_luat_bong()
                    kq = "da nap lai %d chien luoc luat che do bong" % len(self.luat_bong)
                self.storage.danh_dau_lenh(row["id"], "xong", kq)
                logger.info("Lenh dieu khien '%s': %s", lenh, kq)
            except Exception as e:
                self.storage.danh_dau_lenh(row["id"], "loi", str(e))
                logger.exception("Loi khi chay lenh '%s': %s", lenh, e)

    def _ghi_nhip_tim(self, equity: float = None) -> None:
        """Ghi trang thai bot vao DB de web biet bot dang nghi gi.

        Khong co buoc nay thi web chi biet tien trinh con song hay khong - no
        khong the biet circuit breaker dang ngat, va do la dung thu can biet nhat.
        """
        try:
            self.storage.ghi_trang_thai_bot(
                breaker_ngat=self.breaker.tripped,
                breaker_ly_do=self.breaker.reason or "",
                so_vi_the=len(self.risk.positions),
                heat=self.risk.current_heat(equity) if equity else 0.0,
                equity=equity,
                chien_luoc_bong=",".join(s.name for s in self.luat_bong))
        except Exception as e:
            logger.exception("Khong ghi duoc nhip tim (bo qua): %s", e)

    def run_cycle(self) -> None:
        self._xu_ly_lenh_dieu_khien()
        equity = self.client.get_equity()
        if equity is None:
            logger.error("Khong doc duoc von - bo qua vong nay")
            self.breaker.record_api_error()
            return

        self.breaker.check_equity(equity)

        # Nap nen cua TAT CA cac ma truoc, vi dac trung xep hang cat ngang can
        # nhin thay ca ro tai cung mot moc thoi gian. Truoc day moi ma tu nap
        # nen cua no; gop lai o day vua cho phep xay panel vua bot mot luot goi.
        frames = {}
        for symbol in config.SYMBOLS:
            try:
                frames[symbol] = self.client.get_klines(symbol)
            except Exception as e:
                logger.error("Khong nap duoc nen cua %s: %s", symbol, e)
                self.breaker.record_api_error()

        # Ghi nhan cac lenh da dong TRUOC khi xet tin hieu moi, va truoc ca cong
        # circuit breaker: "dung mo lenh moi" khong co nghia la "ngung ghi so".
        # Neu bo qua buoc nay luc breaker bat, heat khong bao gio duoc tra ve va
        # trang thai local troi xa khoi san dung luc can chinh xac nhat.
        so_dong = self.positions.dong_bo(frames)
        if so_dong:
            logger.info("Da ghi nhan %d lenh dong trong vong nay", so_dong)

        heat = self.risk.current_heat(equity)
        self.storage.log_equity(equity, len(self.risk.positions), heat)
        self._ghi_nhip_tim(equity)

        if self.breaker.tripped:
            logger.error("CIRCUIT BREAKER DANG BAT (%s) - khong mo lenh moi. "
                         "Can nguoi kiem tra va reset thu cong.", self.breaker.reason)
            self.notifier.breaker_bat(self.breaker.reason or "khong ro ly do")
            return
        # Breaker da duoc reset -> lan bat ke tiep la su kien moi, dang mot tin nhan.
        self.notifier.xoa_dedup(notifier_mod.BREAKER)

        if self.policy_strategy is not None:
            self.policy_strategy.policy.kiem_tra_champion_moi()
        if self.bo_loc_meta is not None:
            self.bo_loc_meta.kiem_tra_champion_moi()
        panel = self._xay_panel(frames)

        for symbol in config.SYMBOLS:
            if symbol not in frames:
                continue
            try:
                self.process_symbol(symbol, equity, frames[symbol], panel)
            except Exception as e:
                logger.exception("Loi khi xu ly %s: %s", symbol, e)
                self.breaker.record_api_error()
            finally:
                if self.policy_strategy is not None:
                    self.policy_strategy.xoa_boi_canh()

        self.maybe_write_journal()
        self.maybe_bao_tri_policy()

    def bao_tri_bong(self) -> None:
        """Dien ket qua that cho tin hieu che do bong. Chay hang ngay.

        Khong co buoc nay thi che do bong chi la mot khoang cho: co tin hieu
        duoc ghi nhung khong ai biet chung dung hay sai, va cong thang cap chi
        con dem duoc so ngay.
        """
        if not self.luat_bong:
            return
        try:
            from src import cham_diem_bong
            so = cham_diem_bong.dien_ket_qua(
                self.storage, list(config.SYMBOLS), config.KLINE_INTERVAL, config)
            if so:
                logger.info("Cham diem che do bong: dien %d ket qua", so)
        except Exception as e:
            logger.exception("Loi cham diem che do bong (bo qua): %s", e)

    def maybe_bao_tri_policy(self) -> None:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        if self.last_policy_day != today:
            self.last_policy_day = today
            if self.policy_strategy is not None:
                self.bao_tri_policy()
            self.bao_tri_bong()

    def maybe_write_journal(self) -> None:
        if not config.ENABLE_NIGHTLY_JOURNAL:
            return
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        if now.hour >= 23 and self.last_journal_day != today:
            content = self.journal.generate(now)
            if content:
                logger.info("NHAT KY HANG DEM:\n%s", content)
            self.last_journal_day = today

    def run(self, once: bool = False) -> int:
        if not self.startup():
            return 1
        while not _shutdown:
            try:
                self.run_cycle()
            except Exception as e:
                logger.exception("Loi khong mong doi trong vong lap: %s", e)
                self.breaker.record_api_error()
            if once:
                break
            for _ in range(config.LOOP_INTERVAL_SECONDS):
                if _shutdown:
                    break
                time.sleep(1)
        logger.info("Bot da dung. Luu y: cac vi the dang mo VAN CON tren san.")
        self.notifier.dung()
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="AI Trade Bot v2")
    parser.add_argument("--once", action="store_true", help="chay mot vong roi thoat")
    args = parser.parse_args()

    setup_logging()
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    return TradingBot().run(once=args.once)


if __name__ == "__main__":
    sys.exit(main())
