"""회전 로그. 질문은 앞 200자만, 사용자는 해시로, 비밀값과 CSV URL은 마스킹한다."""
import hashlib
import logging
import os
import re
from logging.handlers import RotatingFileHandler

from src import config

_MASKS = [
    (re.compile(r"xox[a-z]-[A-Za-z0-9-]+"), "xox*-***"),
    (re.compile(r"xapp-[A-Za-z0-9-]+"), "xapp-***"),
    (re.compile(r"https://hooks\.slack\.com/\S+"), "<webhook>"),
    (re.compile(r"https://docs\.google\.com/spreadsheets/\S+"), "<sheet-url>"),
    (re.compile(r"(lsv2_[A-Za-z0-9_]+)"), "lsv2_***"),
]


class MaskFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for rx, rep in _MASKS:
            msg = rx.sub(rep, msg)
        record.msg, record.args = msg, ()
        return True


def user_hash(user_id: str) -> str:
    salt = os.environ.get("USER_HASH_SALT", "ailab-bot")
    return hashlib.sha256((salt + user_id).encode()).hexdigest()[:10]


def short_q(q: str, n: int = 200) -> str:
    return (q or "")[:n]


def setup_logging(level: int = logging.INFO) -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = RotatingFileHandler(config.LOG_DIR / "bot.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    sh = logging.StreamHandler()
    for h in (fh, sh):
        h.setFormatter(fmt)
        h.addFilter(MaskFilter())
        root.addHandler(h)
    root.setLevel(level)
    for noisy in ("httpx", "urllib3", "chromadb", "slack_bolt", "slack_sdk"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
