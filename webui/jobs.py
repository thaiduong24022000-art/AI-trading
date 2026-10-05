"""
Chay tien trinh nen cho web UI.

HAI LOAI TIEN TRINH, CO Y TACH RIENG:

  TAC VU (Job)      chay mot lan roi xong: backtest, walk-forward, tai du lieu,
                    mot vong hoc. Toi da MOT cai chay cung luc - chung an CPU
                    manh, chay song song khong nhanh hon ma chi lam so lieu thoi
                    gian mat y nghia.

  DICH VU (Service) chay lien tuc cho den khi bam dung: bot giao dich, bo thu
                    thap so lenh. Chung KHONG chiem cho cua tac vu, va phai song
                    duoc qua viec nguoi dung dong tab trinh duyet.

Moi thu deu la TIEN TRINH RIENG goi lai chinh cac script CLI, khong phai goi ham
truc tiep. Nho vay UI chay dung mot duong voi terminal - khong the co chuyen
"tren web ra ket qua khac voi tren dong lenh" - va tien trinh con chet thi web
van song de bao loi.
"""
import os
import subprocess
import sys
import threading
import time
import uuid
from typing import Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_LINES = 4000

# Danh sach trang: chi nhung script nay duoc phep chay tu UI.
# Ton tai de mot loi o tang tren khong bien thanh "chay lenh tuy y tren may".
SCRIPT_CHO_PHEP = {
    "run_backtest.py": ["backtest", "walkforward", "download"],
    "run_policy.py": ["hoc", "theo-doi", "thang-cap", "ha-cap", "trang-thai"],
    "run_meta.py": ["hoc", "quet", "trang-thai", "the", "ha-cap"],
    "run_phase0.py": [],
}
MODULE_CHO_PHEP = {
    "research.download_universe",
    "research.download_derivatives",
    "research.ic_study",
    "research.quet_hang_rao",
    "research.strategy_lab",
}


def _python() -> str:
    return sys.executable


class Job:
    def __init__(self, kind: str, script: str, args: List[str], label: str):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.script = script
        self.label = label
        self.args = args
        self.lines: List[str] = []
        self.status = "dang_chay"
        self.returncode: Optional[int] = None
        self.started = time.time()
        self.finished: Optional[float] = None
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    @property
    def duration(self) -> float:
        return (self.finished or time.time()) - self.started

    def to_dict(self, since: int = 0) -> Dict:
        with self._lock:
            return {
                "id": self.id, "kind": self.kind, "label": self.label,
                "status": self.status, "returncode": self.returncode,
                "duration": round(self.duration, 1),
                "total_lines": len(self.lines),
                "lines": self.lines[since:],
            }

    def _append(self, text: str) -> None:
        with self._lock:
            self.lines.append(text)
            if len(self.lines) > MAX_LINES:
                del self.lines[: len(self.lines) - MAX_LINES]

    def _cmd(self) -> List[str]:
        if self.script.startswith("-m "):
            return [_python(), "-u", "-m", self.script[3:]] + self.args
        return [_python(), "-u", os.path.join(BASE_DIR, self.script)] + self.args

    def run(self) -> None:
        self._append("$ %s %s" % (self.script, " ".join(self.args)))
        moi_truong = dict(os.environ, PYTHONIOENCODING="utf-8")
        try:
            self._proc = subprocess.Popen(
                self._cmd(), cwd=BASE_DIR, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace", bufsize=1, env=moi_truong,
            )
        except Exception as e:
            self._append("Khong khoi dong duoc tien trinh: %s" % e)
            self.status = "loi"
            self.finished = time.time()
            return

        for line in self._proc.stdout:
            self._append(line.rstrip("\n"))
        self._proc.wait()

        self.returncode = self._proc.returncode
        self.status = "xong" if self.returncode == 0 else "loi"
        self.finished = time.time()

    def stop(self) -> bool:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            self._append("--- da dung theo yeu cau ---")
            self.status = "da_dung"
            self.finished = time.time()
            return True
        return False


class JobManager:
    """Giu toi da MOT tac vu chay cung luc."""

    def __init__(self):
        self.jobs: Dict[str, Job] = {}
        self.order: List[str] = []
        self._lock = threading.Lock()

    def current(self) -> Optional[Job]:
        with self._lock:
            for jid in reversed(self.order):
                if self.jobs[jid].status == "dang_chay":
                    return self.jobs[jid]
        return None

    def start(self, kind: str, script: str, args: List[str], label: str) -> Job:
        _kiem_tra_script(script)
        if self.current():
            raise RuntimeError("Dang co mot tac vu chay - doi no xong hoac bam Dung")
        job = Job(kind, script, args, label)
        with self._lock:
            self.jobs[job.id] = job
            self.order.append(job.id)
            if len(self.order) > 40:
                del self.jobs[self.order.pop(0)]
        threading.Thread(target=job.run, daemon=True).start()
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    def recent(self, n: int = 15) -> List[Dict]:
        with self._lock:
            ids = self.order[-n:][::-1]
        return [{"id": i, "kind": self.jobs[i].kind, "label": self.jobs[i].label,
                 "status": self.jobs[i].status,
                 "duration": round(self.jobs[i].duration, 1),
                 "started": time.strftime("%H:%M:%S",
                                          time.localtime(self.jobs[i].started))}
                for i in ids]


def _kiem_tra_script(script: str) -> None:
    if script.startswith("-m "):
        if script[3:] not in MODULE_CHO_PHEP:
            raise ValueError("module khong nam trong danh sach cho phep: %s" % script)
        return
    if script not in SCRIPT_CHO_PHEP:
        raise ValueError("script khong nam trong danh sach cho phep: %s" % script)


# ==========================================================
# Dich vu chay dai
# ==========================================================
class Service:
    """Mot tien trinh chay lien tuc do UI quan ly."""

    def __init__(self, ten: str, nhan: str):
        self.ten = ten
        self.nhan = nhan
        self.lines: List[str] = []
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self.started: Optional[float] = None
        self.ghi_chu = ""
        self.lenh_cuoi: List[str] = []

    @property
    def dang_chay(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _append(self, text: str) -> None:
        with self._lock:
            self.lines.append(text)
            if len(self.lines) > MAX_LINES:
                del self.lines[: len(self.lines) - MAX_LINES]

    def start(self, cmd: List[str], ghi_chu: str = "") -> None:
        if self.dang_chay:
            raise RuntimeError("%s dang chay roi" % self.nhan)
        self.lines = []
        self.ghi_chu = ghi_chu
        self.lenh_cuoi = cmd
        self.started = time.time()
        moi_truong = dict(os.environ, PYTHONIOENCODING="utf-8")
        self._append("$ " + " ".join(cmd[1:]))
        if ghi_chu:
            self._append("# " + ghi_chu)
        self._proc = subprocess.Popen(
            cmd, cwd=BASE_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1, env=moi_truong,
        )
        threading.Thread(target=self._doc, daemon=True).start()

    def _doc(self) -> None:
        try:
            for line in self._proc.stdout:
                self._append(line.rstrip("\n"))
        except (ValueError, OSError):
            pass
        ma = self._proc.poll()
        self._append("--- tien trinh ket thuc (ma %s) ---" % ma)

    def stop(self) -> bool:
        if not self.dang_chay:
            return False
        self._proc.terminate()
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            # Bot co xu ly tin hieu de dong vi the mot cach trat tu; neu no khong
            # thoat trong 10 giay thi da treo o dau do va giet la lua chon dung.
            self._append("--- khong thoat sau 10s, buoc dung ---")
            self._proc.kill()
        self._append("--- da dung theo yeu cau ---")
        return True

    def to_dict(self, since: int = 0) -> Dict:
        with self._lock:
            return {
                "ten": self.ten, "nhan": self.nhan,
                "dang_chay": self.dang_chay,
                "pid": self._proc.pid if self._proc else None,
                "giay": round(time.time() - self.started, 1) if self.started else 0,
                "ghi_chu": self.ghi_chu,
                "total_lines": len(self.lines),
                "lines": self.lines[since:],
            }


class ServiceManager:
    def __init__(self):
        self.services: Dict[str, Service] = {
            "bot": Service("bot", "Bot giao dich"),
            "collector": Service("collector", "Thu thap so lenh"),
        }

    def get(self, ten: str) -> Optional[Service]:
        return self.services.get(ten)

    def tat_ca(self) -> Dict[str, Dict]:
        return {t: s.to_dict(since=s.to_dict()["total_lines"])
                for t, s in self.services.items()}


manager = JobManager()
dich_vu = ServiceManager()
