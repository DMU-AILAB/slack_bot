"""채널 파싱·추정 (상세구현명세서 7.2). 규칙만 쓰므로 LLM 호출이 없다."""
import re
from dataclasses import dataclass, field

from src.common.text import norm_text

CHANNEL_LABEL = {"contest": "공모전", "news": "인공지능-소식", "coding": "코딩테스트"}

ALIASES = {
    "contest": ["2-공모전", "공모전"],
    "news": ["인공지능-소식", "인공지능 소식", "인공지능소식", "ai 소식", "ai-소식", "ai소식"],
    "coding": ["2026-코딩테스트", "코딩테스트", "코딩-테스트", "코테"],
}

KEYWORDS = {
    "contest": ["공모전", "대회", "해커톤", "경진대회", "마감", "접수", "시상", "수상", "참가", "우수작"],
    "news": ["소식", "뉴스", "이슈", "기사", "동향", "발표", "출시"],
    "coding": ["코딩테스트", "코딩 테스트", "코테", "오늘의 문제", "프로그래머스", "programmers", "swea", "swexpert",
               "풀이", "해설", "힌트"],
}
_NUM_PROBLEM = re.compile(r"\d{2,}\s*번")


@dataclass
class Parsed:
    channel: str | None
    question: str
    candidates: list[str] = field(default_factory=list)
    unsupported: str | None = None


def _to_hash_form(text: str) -> str:
    """슬랙 자동완성 `<#C123|이름>`을 `#이름`으로."""
    return re.sub(r"<#[A-Z0-9]+\|([^>]*)>", r"#\1", text)


def _alias_channel(name: str) -> str | None:
    n = norm_text(name).lower()
    for ch, names in ALIASES.items():
        if any(n == a.lower() or a.lower() in n for a in names):
            return ch
    return None


def parse(text: str) -> Parsed:
    t = norm_text(_to_hash_form(text))
    # 1) 명시된 채널
    m = re.search(r"#([^\s#]+)", t)
    if m:
        ch = _alias_channel(m[1])
        rest = norm_text(t.replace(m[0], " ", 1))
        if ch:
            return Parsed(ch, rest)
        return Parsed(None, rest, unsupported=m[1])
    # 2) 키워드 추정
    low = t.lower()
    hits = [ch for ch, kws in KEYWORDS.items() if any(k in low for k in kws)]
    if "coding" not in hits and _NUM_PROBLEM.search(t):
        hits.append("coding")
    if len(hits) == 1:
        return Parsed(hits[0], t)
    # 둘 이상이거나 하나도 없으면 되묻기
    return Parsed(None, t, candidates=hits or list(CHANNEL_LABEL))


def choice_from_reply(text: str, candidates: list[str]) -> str | None:
    """되묻기 답변(번호 또는 채널 이름)을 채널 키로."""
    t = norm_text(text)
    m = re.fullmatch(r"(\d)\s*[.번]?", t)
    order = list(CHANNEL_LABEL)  # 1.공모전 2.인공지능-소식 3.코딩테스트
    if m and 1 <= int(m[1]) <= 3:
        return order[int(m[1]) - 1]
    return _alias_channel(t.lstrip("#"))


def ask_text(candidates: list[str]) -> str:
    lines = ["어느 채널 자료로 답할까요? 번호나 채널 이름으로 답해 주세요."]
    for i, ch in enumerate(CHANNEL_LABEL, 1):
        lines.append(f"{i}. {CHANNEL_LABEL[ch]}" + (" (추정)" if ch in candidates and len(candidates) < 3 else ""))
    return "\n".join(lines)


def unsupported_text(name: str) -> str:
    return (f"`#{name}` 채널은 지원하지 않습니다. 지원 채널은 아래 3개입니다.\n"
            "1. 공모전 (`#2-공모전`)\n2. 인공지능-소식 (`#인공지능-소식`)\n3. 코딩테스트 (`#2026-코딩테스트`)")
