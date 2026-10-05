"""
Boc AI policy thanh mot Strategy de no di dung duong ong da co.

VI SAO KHONG CHO POLICY DAT LENH TRUC TIEP: duong di hien tai la
    chien luoc -> allocator -> LLM veto -> risk engine -> executor
Moi lop trong do la mot rang buoc da duoc kiem dinh (heat toi da, tran tuong
quan, circuit breaker, doi soat voi san). Cho mo hinh moi di tat qua chung la
danh doi toan bo phan an toan cua he thong lay mot thu chua chung minh duoc gi.
Boc thanh Strategy nghia la policy huong DUNG mot dac quyen: duoc noi len y
kien cua no. Con lai khong doi.

BON CHE DO, xep theo muc do duoc phep anh huong:

  off     khong nap mo hinh.
  shadow  co du doan, co ghi vao so, nhung tin hieu tra ve LUON la HOLD.
          Day la che do mac dinh cho mo hinh moi: no chay song song voi he
          thong that trong nhieu tuan va tich luy mot ho so ket qua truc tuyen
          truoc khi duoc dong den mot dong von nao.
  filter  chi duoc CHAN hoac GIAM quy mo tin hieu cua chien luoc luat, giong
          rang buoc dat cho LLM veto. Khong tu tao lenh.
  active  la mot thanh vien binh thuong cua ensemble.

Chuyen che do la QUYET DINH CUA NGUOI, khong phai cua vong hoc. Vong hoc duoc
phep doi champion trong mot che do; no khong duoc phep tu nang che do len.
"""
from typing import Optional

import pandas as pd

from .. import policy as policy_mod
from .base import BUY, HOLD, SELL, Signal, Strategy


class MLPolicyStrategy(Strategy):
    name = "ml_policy"
    preferred_regimes = ()      # policy tu hoc boi canh, khong gan cung theo regime
    default_params = {}

    def __init__(self, policy: policy_mod.MLPolicy = None, cfg=None, **params):
        super().__init__(**params)
        import config as cfg_mac_dinh
        self.cfg = cfg or cfg_mac_dinh
        self.policy = policy or policy_mod.MLPolicy(self.cfg)
        self._symbol: str = ""
        self._panel: Optional[pd.DataFrame] = None
        self.ket_qua_gan_nhat: Optional[policy_mod.KetQuaPolicy] = None

    # ---------- boi canh ----------
    def dat_boi_canh(self, symbol: str, panel: pd.DataFrame) -> None:
        """main.py goi truoc moi lan sinh tin hieu.

        Panel duoc xay MOT LAN cho ca vong (dac trung xep hang cat ngang can
        toan bo cac ma tai cung moc), roi tung ma doc dong cua minh ra tu do.
        """
        self._symbol = symbol
        self._panel = panel

    def xoa_boi_canh(self) -> None:
        self._symbol, self._panel = "", None

    # ---------- tin hieu ----------
    def generate_at(self, df: pd.DataFrame, i: int) -> Signal:
        sig = self._base_signal()
        self.ket_qua_gan_nhat = None

        if self._panel is None or not self._symbol:
            sig.reason = "chua co panel dac trung cho vong nay"
            return sig

        bar_ts = None
        if "timestamp" in df.columns and 0 <= i < len(df):
            bar_ts = int(df["timestamp"].iloc[i])

        hang = policy_mod.lay_hang(self._panel, self._symbol, bar_ts)
        if hang is None:
            sig.reason = "khong tim thay dong panel cho %s tai nen nay" % self._symbol
            return sig

        kq = self.policy.du_doan(hang)
        self.ket_qua_gan_nhat = kq
        sig.metrics = {"p_long": kq.p_long, "p_short": kq.p_short,
                       "ev_long": kq.ev_long, "ev_short": kq.ev_short}

        che_do = self.policy.che_do
        if che_do == policy_mod.BONG:
            # Rang buoc duoc thuc thi BANG CODE, khong bang ky luat: o che do bong
            # ham nay khong co duong nao tra ve BUY/SELL.
            sig.reason = "che do bong - %s (khong tac dong den lenh)" % kq.ly_do
            return sig

        if not kq.co_y_kien:
            sig.reason = kq.ly_do
            return sig

        sig.action, sig.strength = kq.action, kq.strength
        sig.reason = "%s [%s]" % (kq.ly_do, kq.phien_ban)
        return sig

    def y_kien_tho(self) -> Optional[policy_mod.KetQuaPolicy]:
        """Y kien that cua mo hinh, KE CA khi che do bong da nen tin hieu ve HOLD.

        Dung de ghi so va de bao cao, khong bao gio dung de ra quyet dinh -
        neu ai do goi ham nay trong duong di quyet dinh thi che do bong khong
        con nghia ly gi nua.
        """
        return self.ket_qua_gan_nhat
