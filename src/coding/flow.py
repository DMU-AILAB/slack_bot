"""코딩테스트 처리 단계 (상세구현명세서 8.3). 각 단계는 상태 dict를 받아 갱신분을 돌려주므로 LangGraph 노드로 그대로 쓴다.

상태에는 비밀값(SWEA 계정, 쿠키)을 넣지 않는다.
"""
import logging
from dataclasses import asdict
from datetime import date

from src import config
from src.coding import generate, resolve, sandbox
from src.coding.problems import Problem, load_problem
from src.common.text import escape_slack
from src.rag.indexer import load_coding_index

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- 단계
def step_resolve(s: dict) -> dict:
    r = resolve.resolve(s["question"], load_coding_index(), date.fromisoformat(s["today"]))
    return {"hint_only": r.hint_only, "target": asdict(r.target) if r.target else None, "message": r.message}


def step_fetch(s: dict) -> dict:
    t = s["target"]
    p = load_problem(t["platform"], t["problem_id"], t["title"], t["url"])
    return {"problem": asdict(p), "attempt": 0, "verified": None, "results": []}


def _problem(s: dict) -> Problem:
    return Problem(**s["problem"])


def can_solve(s: dict) -> bool:
    p = s["problem"]
    return not p["error"] and p["kind"] != "sql"


def step_generate(s: dict) -> dict:
    p, attempt = _problem(s), s.get("attempt", 0) + 1
    if s.get("hint_only"):
        return {"hint_text": generate.hints(p), "attempt": attempt}
    feedback = None
    if attempt > 1 and s.get("last_failure"):
        feedback = s["last_failure"]
    approach, code = generate.solve(p, feedback, s.get("code", ""))
    return {"approach": approach, "code": code, "attempt": attempt}


def step_run(s: dict) -> dict:
    p = _problem(s)
    if not p.examples:
        return {"verified": "na", "results": [], "last_failure": None}
    if not s.get("code"):
        return {"verified": "fail", "results": [], "last_failure": "앞의 응답에 코드가 없었다. ```python 코드블록으로 전체 코드를 출력해라."}
    res = sandbox.run_examples(p.kind, s["code"], p.examples)
    ok = all(r.passed for r in res)
    failure = None
    if not ok:
        i = next(k for k, r in enumerate(res) if not r.passed)
        failure = generate.feedback_block(res[i], p.examples[i], p.kind)
    return {"verified": "pass" if ok else "fail", "results": [asdict(r) for r in res], "last_failure": failure}


def should_retry(s: dict) -> bool:
    return s.get("verified") == "fail" and s.get("attempt", 0) < config.MAX_REGEN


# ---------------------------------------------------------------- 응답 조립
def _header(t: dict, p: dict) -> str:
    bits = [t["tier"]] if t.get("tier") else []
    if t.get("rate"):
        bits.append(f"정답률 {t['rate']}%")
    head = (f"*{resolve.PLATFORM_LABEL[t['platform']]} {t['problem_id']}번 {escape_slack(p.get('title') or t['title'])}*  "
            f"<{t['url']}|문제 보기>" + ("  ·  " + " · ".join(bits) if bits else ""))
    return head + (f"\n_{t['note']}_" if t.get("note") else "")


def compose(s: dict) -> str:
    if not s.get("target"):
        return s.get("message") or "대상 문제를 찾지 못했습니다."
    t, p = s["target"], s["problem"]
    head = _header(t, p)
    if p["error"]:
        return f"{head}\n\n{p['error']} 문제 링크에서 직접 확인해 주세요."
    if p["kind"] == "sql":
        return f"{head}\n\nSQL 문제라 풀이를 만들지 않습니다. (이 봇은 Python 풀이만 지원합니다.)"
    if s.get("hint_only"):
        return f"{head}\n\n*힌트* (정답 코드는 포함하지 않았습니다)\n{s.get('hint_text', '').strip()}"
    parts = [head, f"*접근*  {s.get('approach', '').strip() or '(설명을 만들지 못했습니다)'}"]
    if s.get("code"):
        parts.append(f"```python\n{s['code']}\n```")
    res, n = s.get("results", []), len(s.get("results", []))
    if s.get("verified") == "pass":
        parts.append(f"*검증*  검증 통과 (예시 {n}/{n})")
    elif s.get("verified") == "na":
        reason = "예시를 읽지 못함" if not p["examples"] else "실행하지 못함"
        parts.append(f"*검증*  검증 불가({reason})")
    else:
        passed = sum(1 for r in res if r["passed"])
        line = f"*검증*  검증 실패 (예시 {passed}/{n}, 시도 {s.get('attempt', 0)}회)"
        bad = next((r for r in res if not r["passed"]), None)
        if bad:
            line += f"\n실패 케이스: 기대 `{bad['expected']}` / 실제 `{bad['actual']}`" + (f" / 오류 `{bad['stderr'][:120]}`" if bad["stderr"] else "")
        parts.append(line + "\n정답이라고 보장할 수 없습니다.")
    parts.append("_입출력 예시를 통과해도 숨겨진 테스트의 통과는 보장하지 않습니다._")
    return "\n\n".join(parts)


# ---------------------------------------------------------------- 그래프 없이 실행(테스트·CLI)
def run_all(question: str, today: date, progress=None) -> dict:
    s = {"question": question, "today": today.isoformat()}
    s.update(step_resolve(s))
    if not s["target"]:
        s["answer"] = compose(s)
        return s
    s.update(step_fetch(s))
    if can_solve(s):
        while True:
            s.update(step_generate(s))
            if s.get("hint_only"):
                break
            s.update(step_run(s))
            if not should_retry(s):
                break
    s["answer"] = compose(s)
    return s
