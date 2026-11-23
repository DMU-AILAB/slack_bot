"""공모전 질의 분석 (상세구현명세서 8.1). 규칙을 우선하고, 주제는 정리한 질문 문장을 그대로 임베딩 검색에 쓴다."""
import re
from dataclasses import dataclass
from datetime import date, timedelta

from src.common.text import norm_text, week_bounds

ASPECTS = {
    "prize": ["시상", "상금", "혜택", "포상", "상품"],
    "eligibility": ["참가 자격", "참가자격", "자격", "참가 대상", "참가대상", "지원 대상", "응모 자격"],
    "period": ["접수 기간", "접수기간", "일정", "언제까지", "기간"],
    "theme": ["주제", "과제", "공모 분야"],
    "criteria": ["심사", "평가 기준", "평가기준"],
}
_STOP = re.compile(
    r"(알려\s*줘|알려주세요|알려\s*주세요|있어\??|있나요\??|뭐야\??|뭐가|어떤|좀|지금|현재|모집\s*중(인|이야|인가)?|"
    r"나가고\s*싶은데|나가고\s*싶어|참가하고\s*싶은데|공모전|대회|이번\s*주(에)?|새로\s*올라온|마감(되는|임박)?|"
    r"찾아\s*줘|추천해\s*줘|보여\s*줘|정리해\s*줘|분석해\s*줘|특징|수상작들?|우수작|\?)")


@dataclass
class ContestQuery:
    intent: str = "search"          # search | deadline_soon | new | detail | winners
    topic: str = ""                 # 임베딩 검색에 쓸 정리된 문장
    title: str | None = None
    aspect: str = "any"
    include_closed: bool = False
    window_days: int = 7
    until: date | None = None       # deadline_soon의 마지막 날
    raw: str = ""


def clean_topic(q: str) -> str:
    t = _STOP.sub(" ", norm_text(q))
    t = re.sub(r"[을를이가은는에서의도로]\s+", " ", t + " ")
    return norm_text(t)


def detect_aspect(q: str) -> str:
    for asp, kws in ASPECTS.items():
        if any(k in q for k in kws):
            return asp
    return "any"


def analyze(q: str, today: date) -> ContestQuery:
    q = norm_text(q)
    cq = ContestQuery(raw=q, aspect=detect_aspect(q))
    cq.include_closed = bool(re.search(r"마감된|지난|종료된|끝난|예전", q))

    if re.search(r"수상작|우수작|입상작|수상자|우승작|(대상|최우수상).{0,6}(분석|특징)|수상.{0,6}특징", q):
        cq.intent = "winners"
        return cq
    m = re.search(r"(\d+)\s*일\s*(이내|안에|내)", q)
    if re.search(r"이번\s*주.{0,6}마감|마감\s*임박|마감되는|곧\s*마감|마감.{0,4}임박", q) or (m and "마감" in q):
        cq.intent = "deadline_soon"
        if "이번 주" in q or "이번주" in q:
            cq.until = week_bounds(today)[1]
            cq.window_days = (cq.until - today).days
        else:
            cq.window_days = int(m[1]) if m else 7
            cq.until = today + timedelta(days=cq.window_days)
        cq.topic = clean_topic(q)
        return cq
    if re.search(r"새로\s*올라온|신규|새\s*공고|새로운\s*공모전|이번\s*주.{0,6}올라", q):
        cq.intent = "new"
        cq.window_days = 7
        cq.topic = clean_topic(q)
        return cq
    cq.topic = clean_topic(q)
    cq.intent = "search"
    return cq


_TITLE_STOP = {"공모전", "대회", "알려줘", "알려", "시상", "내역", "참가", "자격", "대상", "있어", "뭐야", "주제", "심사",
               "기준", "접수", "기간", "일정", "상금", "혜택", "대한", "관련", "모집", "현재", "지금"}


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[0-9A-Za-z가-힣]+", norm_text(s).lower()) if len(t) >= 2 and t not in _TITLE_STOP}


def find_title(q: str, titles: dict[str, str]) -> str | None:
    """질문에 들어 있는 공모전 이름을 시트 제목과 비교해 activity_id를 돌려준다. 확실하지 않으면 None."""
    qt, ql = _tokens(q), norm_text(q).lower()
    best, best_score = None, 0.0
    for aid, title in titles.items():
        tt = _tokens(title)
        if not tt or not qt:
            continue
        shared = qt & tt
        score = len(shared)
        if norm_text(title).lower() in ql:
            score += 5
        if score >= 2 and score / max(len(qt), 1) >= 0.5 and score > best_score:
            best, best_score = aid, score
    return best
