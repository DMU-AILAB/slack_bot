"""정규화·날짜 유틸 (상세구현명세서 5.1)."""
import hashlib
import html
import re
import unicodedata
from datetime import date, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
ZERO_WIDTH = "​‌‍﻿⁠"
_ZW_TABLE = {ord(c): None for c in ZERO_WIDTH}


def norm_text(s: str | None) -> str:
    """제로폭 문자 제거, NFKC, 연속 공백 1칸, strip."""
    if not s:
        return ""
    s = s.translate(_ZW_TABLE)
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_url(u: str | None) -> str:
    """&amp; 해제, fragment·utm_* 제거, 호스트 소문자, 끝의 '/' 제거(id, idxno 쿼리는 유지)."""
    if not u:
        return ""
    u = html.unescape(u.strip())
    p = urlsplit(u)
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
    path = p.path.rstrip("/") if p.path != "/" else ""
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, urlencode(query), ""))


def url_key(u: str) -> str:
    return hashlib.sha1(norm_url(u).encode()).hexdigest()[:16]


def kst_now() -> datetime:
    return datetime.now(KST)


def kst_today() -> date:
    return kst_now().date()


def epoch_to_kst(ts: float) -> datetime:
    return datetime.fromtimestamp(float(ts), KST)


def date_int(d: date | None) -> int:
    """YYYYMMDD 정수. None이면 0 (Chroma 필터용)."""
    return d.year * 10000 + d.month * 100 + d.day if d else 0


def parse_date(s: str | None) -> date | None:
    """'2026-11-20', '2026. 11. 20', '2026/11/20 12:00' 등에서 날짜를 읽는다."""
    if not s:
        return None
    m = re.search(r"(\d{4})\D{1,3}(\d{1,2})\D{1,3}(\d{1,2})", str(s))
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def parse_dt(s: str | None) -> datetime | None:
    """'2026-03-29 4:08' (시가 한 자리)도 허용. KST로 간주."""
    if not s:
        return None
    m = re.search(r"(\d{4})\D{1,3}(\d{1,2})\D{1,3}(\d{1,2})(?:\D+(\d{1,2}):(\d{2}))?", str(s))
    if not m:
        return None
    try:
        return datetime(int(m[1]), int(m[2]), int(m[3]), int(m[4] or 0), int(m[5] or 0), tzinfo=KST)
    except ValueError:
        return None


def title_deadline(title: str, collected_at: datetime | date | None = None) -> date | None:
    """제목의 '(~11/20)'에서 마감일 추정. 수집 월보다 작은 월이면 다음 해."""
    m = re.search(r"\(~\s*(\d{1,2})/(\d{1,2})\)", title or "")
    if not m:
        return None
    base = collected_at or kst_today()
    base_d = base.date() if isinstance(base, datetime) else base
    month, day = int(m[1]), int(m[2])
    year = base_d.year + (1 if month < base_d.month else 0)
    try:
        return date(year, month, day)
    except ValueError:
        return None


def week_bounds(today: date) -> tuple[date, date]:
    """이번 주 월요일 ~ 일요일."""
    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=6)


def escape_slack(s: str) -> str:
    """슬랙 mrkdwn 링크 텍스트용 이스케이프."""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("|", "¦")
