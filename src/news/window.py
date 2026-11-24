"""기간·개수·질문 유형 파싱 (상세구현명세서 8.2)."""
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from src import config
from src.common.text import KST, norm_text

_KO_NUM = {"한": 1, "하나": 1, "두": 2, "둘": 2, "세": 3, "셋": 3, "네": 4, "넷": 4, "다섯": 5}


@dataclass
class NewsQuery:
    since: datetime
    until: datetime
    label: str
    top_n: int
    kind: str      # issues | topic
    topic: str
    raw: str


def parse_window(q: str, today: date) -> tuple[date, date, str]:
    """(시작일, 종료일(포함), 라벨)"""
    m = re.search(r"최근\s*(\d+)\s*일", q)
    if m:
        n = int(m[1])
        return today - timedelta(days=n - 1), today, f"최근 {n}일"
    if "어제" in q:
        d = today - timedelta(days=1)
        return d, d, "어제"
    if "오늘" in q:
        return today, today, "오늘"
    if "지난주" in q or "지난 주" in q:
        mon = today - timedelta(days=today.weekday() + 7)
        return mon, mon + timedelta(days=6), "지난주"
    if "이번 주" in q or "이번주" in q:
        if today.weekday() < 2:          # 월·화요일은 이번 주 분량이 하루~이틀뿐이라 최근 7일로 넓힌다
            return today - timedelta(days=6), today, "최근 7일(이번 주가 막 시작돼 넓힘)"
        return today - timedelta(days=today.weekday()), today, "이번 주"
    if "이번 달" in q or "이번달" in q:
        return today.replace(day=1), today, "이번 달"
    n = config.NEWS_DEFAULT_DAYS
    return today - timedelta(days=n - 1), today, f"최근 {n}일"


def parse_count(q: str) -> int:
    m = re.search(r"(\d+)\s*(가지|개)", q)
    if m:
        n = int(m[1])
    else:
        m = re.search(r"(한|하나|두|둘|세|셋|네|넷|다섯)\s*(가지|개)", q)
        n = _KO_NUM[m[1]] if m else config.NEWS_TOP_N
    return max(1, min(n, config.NEWS_MAX_N))


_GENERIC = re.compile(
    r"(최근|이번\s*주|지난\s*주|이번\s*달|어제|오늘|\d+\s*일|가장|중요한|중요|이슈|소식|뉴스|기사|동향|정리해?\s*줘|정리|요약해?\s*줘|요약|"
    r"알려\s*줘|알려주세요|\d+\s*(가지|개)|(한|두|세|네|다섯)\s*(가지|개)|만|좀|관련|에\s*대한|인공지능|AI|들)", re.I)


def extract_topic(q: str) -> str:
    t = _GENERIC.sub(" ", norm_text(q))
    t = re.sub(r"[을를이가은는에서의도로]\s+", " ", t + " ")
    t = re.sub(r"[?!.]", " ", t)
    return norm_text(t)


def analyze(q: str, today: date) -> NewsQuery:
    q = norm_text(q)
    s, e, label = parse_window(q, today)
    topic = extract_topic(q)
    kind = "topic" if len(topic) >= 2 else "issues"
    return NewsQuery(
        since=datetime.combine(s, time.min, KST), until=datetime.combine(e, time.max, KST),
        label=label, top_n=parse_count(q), kind=kind, topic=topic, raw=q)
