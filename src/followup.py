"""같은 스레드의 후속 질문 해석 (상세구현명세서 7.3). 직전 답변에 보여 준 목록(last_results)만 참조한다."""
import re

from src.common.text import norm_text

_ORD = re.compile(r"(첫|두|세|네|다섯|\d+)\s*번째|마지막")
_ORD_NUM = {"첫": 1, "두": 2, "세": 3, "네": 4, "다섯": 5}
_THAT_PROBLEM = re.compile(r"그\s*문제|방금\s*(그\s*)?문제|위\s*문제|그거|이\s*문제")
_LABEL = {"programmers": "프로그래머스", "swea": "SWEA"}


def ordinal_index(q: str, n: int) -> int | None:
    m = _ORD.search(q)
    if not m:
        return None
    if m[0] == "마지막":
        return n - 1
    k = _ORD_NUM.get(m[1]) or int(m[1])
    return k - 1 if 1 <= k <= n else None


def resolve(question: str, last_channel: str | None, last_results: list[dict] | None) -> tuple[str, str] | None:
    """(채널, 풀어쓴 질문) 또는 None. 해석할 수 없으면 None이라 일반 질문으로 처리한다."""
    if not last_channel or not last_results:
        return None
    q = norm_text(question)
    if last_channel == "contest":
        i = ordinal_index(q, len(last_results))
        if i is None:
            return None
        rest = norm_text(_ORD.sub(" ", q).replace("공고", " ").replace("그 중", " ").replace("그중", " "))
        return "contest", f"{last_results[i]['title']} {rest}".strip()
    if last_channel == "coding" and _THAT_PROBLEM.search(q):
        r = last_results[0]
        rest = norm_text(_THAT_PROBLEM.sub(" ", q))
        return "coding", f"{_LABEL.get(r.get('platform', ''), '')} {r['id']}번 {rest}".strip()
    return None
