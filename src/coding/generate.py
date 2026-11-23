"""풀이·힌트 생성 (상세구현명세서 9.5~9.7). 소형 모델에서 JSON이 깨지는 문제를 피하려고 '설명 + 코드블록' 형식으로 받는다."""
import json
import re

from src import config, llm
from src.coding.problems import Problem, STATEMENT_MAX_CHARS
from src.coding.sandbox import ALLOWED_MODULES, RunResult

_CODE_RE = re.compile(r"```(?:python|py|Python)?[ \t]*\n(.*?)```", re.S)


def _fmt_examples(p: Problem, limit: int = 3) -> str:
    rows = []
    for i, ex in enumerate(p.examples[:limit], 1):
        if p.kind == "stdio":
            rows.append(f"예시 {i}\n입력:\n{ex['input']}\n출력:\n{ex['expected']}")
        else:
            args = ", ".join(f"{n}={json.dumps(v, ensure_ascii=False)}" for n, v in zip(p.params or [f"arg{k}" for k in range(len(ex['args']))], ex["args"]))
            rows.append(f"예시 {i}: solution({args}) → {json.dumps(ex['expected'], ensure_ascii=False)}")
    return "\n".join(rows)


def _problem_block(p: Problem) -> str:
    return f"<문제>\n{p.title}\n{p.statement[:STATEMENT_MAX_CHARS]}\n{_fmt_examples(p)}\n</문제>\n"


def _rules(p: Problem) -> str:
    mods = ", ".join(ALLOWED_MODULES)
    if p.kind == "stdio":
        sig = "표준 입력으로 받고 표준 출력으로 낸다. 출력은 각 테스트케이스마다 \"#번호 결과\" 형식."
    else:
        sig = f"def solution({', '.join(p.params) or '...'}): 함수만 작성한다. 입출력(input, print) 코드는 쓰지 않는다."
    return (f"위 문제를 Python 3으로 풀어라.\n- 사용할 수 있는 모듈: {mods}\n- {sig}\n"
            "출력 형식: 먼저 접근 방법을 3~5문장으로 쓰고, 이어서 ```python 코드블록 하나만 쓴다.\n문제 전문을 그대로 옮기지 마라.")


def parse_solution(text: str) -> tuple[str, str]:
    """(접근 설명, 코드). 코드블록이 없으면 코드는 빈 문자열."""
    m = _CODE_RE.search(text)
    if not m:
        return text.strip(), ""
    approach = (text[:m.start()] + text[m.end():]).strip()
    return re.sub(r"\n{3,}", "\n\n", approach), m[1].strip("\n")


def feedback_block(failed: RunResult, example: dict, kind: str) -> str:
    inp = example.get("input") if kind == "stdio" else json.dumps(example.get("args"), ensure_ascii=False)
    return ("앞의 코드를 실행했더니 다음 케이스가 실패했다.\n"
            f"입력: {inp}\n기대 출력: {failed.expected}\n실제 출력: {failed.actual}\n오류: {failed.stderr or '없음'}\n"
            "원인을 짧게 정리하고 수정한 전체 코드를 같은 형식(설명 + ```python 코드블록)으로 출력해라.")


def solve(p: Problem, feedback: str | None = None, prev_code: str = "") -> tuple[str, str]:
    prompt = _problem_block(p) + _rules(p)
    if feedback:
        prompt += f"\n\n이전 코드:\n```python\n{prev_code}\n```\n{feedback}"
    out = llm.generate(prompt, system=False, temperature=0.4 if feedback else config.GEN_TEMPERATURE,
                       num_predict=config.GEN_NUM_PREDICT_CODE, run_name="coding-generate")
    return parse_solution(out)


def hints(p: Problem) -> str:
    prompt = (_problem_block(p) + "정답 코드나 정답 값은 쓰지 말고, 단계별 힌트 3개와 떠올릴 핵심 개념 1개만 써라.\n"
              "형식:\n힌트 1: ...\n힌트 2: ...\n힌트 3: ...\n핵심 개념: ...")
    return llm.generate(prompt, system=False, num_predict=500, run_name="coding-hints")
