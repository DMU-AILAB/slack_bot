"""평가 채점 함수 (모델·네트워크 없이 테스트 가능). 정답 문장 비교가 아니라 규칙으로 채점한다."""
import re
from datetime import date, timedelta

URL_RE = re.compile(r"https?://[^\s|>)\]]+")
DEADLINE_RE = re.compile(r"마감 (\d{4}-\d{2}-\d{2}) \((D-day|D-\d+|마감됨)\)")
NUMBERED_RE = re.compile(r"^\s*\d+\.\s", re.M)
ERROR_MARKERS = ("답변을 만들지 못했습니다", "모델 서버에 연결하지 못했습니다", "처리 중 오류가 났습니다", "너무 오래 걸려")
EMPTY_MARKERS = ("찾지 못했습니다",)


def urls_in(text: str) -> list[str]:
    return [u.rstrip(".,") for u in URL_RE.findall(text)]


def route_of(parsed) -> str:
    """router.Parsed → 'contest' | 'news' | 'coding' | 'ask' | 'unsupported'"""
    if parsed.unsupported:
        return "unsupported"
    return parsed.channel or "ask"


def score_route(item: dict, got_channel: str, got_intent: str | None) -> dict:
    want = item["channel"]
    ok = got_channel == want or (bool(item.get("ok_ask")) and got_channel == "ask")
    intent_ok = None
    if item.get("intent") and got_channel == "contest":
        intent_ok = got_intent == item["intent"]
    return {
        "ok": ok,
        "exact": got_channel == want,
        "misroute": got_channel not in (want, "ask"),  # 확신하고 틀린 경우 (되묻기보다 나쁨)
        "intent_ok": intent_ok,
    }


def check_answer(item: dict, answer: str, known_urls: set[str], today: date, extra_links: list[str] | None = None) -> dict:
    """항목의 조건을 검사해 {이름: 통과 여부}를 돌려준다. 해당하지 않는 조건은 넣지 않는다."""
    c: dict[str, bool] = {}
    c["no_error"] = bool(answer.strip()) and not any(m in answer for m in ERROR_MARKERS)

    links = urls_in(answer)
    unknown = [u for u in links if u not in known_urls]
    c["links_known"] = not unknown                        # 모델이 지어낸 링크가 없는가

    empty = any(m in answer for m in EMPTY_MARKERS) and len(set(links)) == 0
    if "min_items" in item:
        c["min_items"] = len(set(links)) >= item["min_items"] or (bool(item.get("empty_ok")) and empty)
    elif not item.get("empty_ok"):
        c["has_content"] = len(set(links)) >= 1
    if item.get("contains_any"):
        c["contains_any"] = any(k in answer for k in item["contains_any"])
    if item.get("not_contains"):
        c["not_contains"] = not any(k in answer for k in item["not_contains"])
    if "max_numbered" in item:
        c["max_numbered"] = len(NUMBERED_RE.findall(answer)) <= item["max_numbered"]

    dls = DEADLINE_RE.findall(answer)
    if item.get("open_only"):
        c["open_only"] = all(tag != "마감됨" and date.fromisoformat(d) >= today for d, tag in dls)
    if item.get("deadline_within_days") is not None:
        lim = today + timedelta(days=item["deadline_within_days"])
        c["deadline_within"] = all(today <= date.fromisoformat(d) <= lim for d, _ in dls)
    if extra_links:
        c["has_expected_link"] = all(u in links for u in extra_links)
    c["length_ok"] = len(answer) <= 3800                  # 슬랙 분할 기준 이내(초과해도 분할되지만 길이 폭주를 잡는다)
    return c


def passed(checks: dict[str, bool]) -> bool:
    return all(checks.values())


def pct(n: int, d: int) -> float:
    return round(100 * n / d, 1) if d else 0.0


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return round(s[min(len(s) - 1, int(p * len(s)))], 2)


def shorten_title(title: str, n_tokens: int = 4) -> str:
    """검색 평가용: 대괄호 태그를 빼고 앞쪽 몇 단어만 남겨 '대충 기억나는 이름'을 흉내 낸다."""
    t = re.sub(r"[\[\(【][^\]\)】]*[\]\)】]", " ", title)
    toks = [x for x in re.findall(r"[0-9A-Za-z가-힣]+", t) if len(x) >= 2]
    return " ".join(toks[:n_tokens])


# ---------------------------------------------------------------- 근거 충실도 (환각 탐지)
_WORD = re.compile(r"\d+(?:[.,]\d+)*[A-Za-z가-힣%]*|[A-Za-z가-힣]+\d*")   # 12.84GWh 같은 수치를 한 덩어리로
_NUM_CORE = re.compile(r"\d+(?:[.,]\d+)*[a-z%]*")
_ENDINGS = ("습니다", "입니다", "했습니다", "됩니다", "있다", "이다", "한다", "했다", "된다", "하며", "하고", "으로", "에서", "에게", "까지", "부터")
_STOP = {"있습니다", "되었습니다", "했습니다", "합니다", "관련", "대한", "통해", "위해", "따라", "또한", "이에", "것으로", "있으며",
         "다음", "이번", "최근", "등을", "하는", "있는", "위한", "대해", "에서", "으로", "이며", "때문", "경우", "내용", "정리", "요약", "제목"}
_EVIDENCE_BLOCK = re.compile(r"<자료>(.*?)</자료>", re.S)


def evidence_of(prompt: str) -> str:
    """프롬프트에서 근거 자료 부분만 꺼낸다."""
    m = _EVIDENCE_BLOCK.search(prompt)
    return m[1] if m else prompt


def _grounded(tok: str, ev: str) -> bool:
    if tok in ev:
        return True
    if any(c.isdigit() for c in tok):
        core = _NUM_CORE.match(tok)                    # 숫자는 (조사를 뗀) 값이 정확히 일치해야 한다
        return bool(core) and core[0] in ev
    for cut in (1, 2):                                 # 조사·어미를 잘라 어간으로 비교
        if len(tok) - cut >= 2 and tok[:-cut] in ev:
            return True
    for e in _ENDINGS:
        if tok.endswith(e) and len(tok) - len(e) >= 2 and tok[: -len(e)] in ev:
            return True
    return False


def grounding(output: str, evidence: str) -> dict:
    """출력의 내용어 중 근거 자료에서 찾을 수 없는 것의 비율과 목록. 숫자는 정확히 일치해야 한다."""
    out = re.sub(r"https?://\S+|\[\d+\]", " ", output).lower()
    ev = evidence.lower()
    toks = [t for t in _WORD.findall(out) if len(t) >= 2 and t not in _STOP]
    if not toks:
        return {"rate": 0.0, "n": 0, "ungrounded": [], "numbers_ok": True}
    bad = [t for t in toks if not _grounded(t, ev)]
    nums = [t for t in bad if any(c.isdigit() for c in t)]
    return {"rate": round(len(bad) / len(toks), 3), "n": len(toks), "ungrounded": sorted(set(bad))[:15], "numbers_ok": not nums}
