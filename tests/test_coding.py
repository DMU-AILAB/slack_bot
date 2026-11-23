import json
from datetime import date

from src.coding import generate, resolve
from src.coding import problems as pb
from src.coding import sandbox as sb

URL = "https://school.programmers.co.kr/learn/courses/30/lessons/181936"
INDEX = {
    "problems": {
        "programmers": [{"platform": "programmers", "problem_id": "181936", "title": "공배수", "tier": "Lv. 0", "rate": 89.0,
                         "done": True, "hashcode": "", "url": URL},
                        {"platform": "programmers", "problem_id": "59037", "title": "SQL 문제", "tier": "Lv. 1", "rate": 50.0,
                         "done": False, "hashcode": "", "url": URL.replace("181936", "59037")}],
        "swea": [{"platform": "swea", "problem_id": "6329", "title": "연습", "tier": "D2", "rate": 70.2, "done": True,
                  "hashcode": "AV5abc", "url": "https://swexpertacademy.com/x?contestProbId=AV5abc"}]},
    "notices": [{"platform": "programmers", "problem_id": "181936", "title": "공배수", "url": URL, "level": "0", "rate": 89.0,
                 "sent_date": "2026-11-13"},
                {"platform": "swea", "problem_id": "6329", "title": "연습", "url": "https://swexpertacademy.com/x", "level": "1",
                 "rate": 70.2, "sent_date": "2026-11-12"}],
}
SAT = date(2026, 11, 14)


# ---------------------------------------------------------------- 대상 식별
def test_today_without_notice_falls_back_to_latest_with_note():
    r = resolve.resolve("오늘의 프로그래머스 문제 답과 해설", INDEX, SAT)
    assert r.target.problem_id == "181936" and "가장 최근(11/13)" in r.target.note


def test_number_lookup_and_missing_and_hint():
    r = resolve.resolve("181936번 풀이", INDEX, SAT)
    assert r.target.problem_id == "181936" and not r.hint_only
    assert resolve.resolve("99999번 풀이", INDEX, SAT).message
    assert resolve.resolve("답은 말고 힌트만 줘", INDEX, SAT).hint_only


def test_today_notice_wins_and_no_platform_mentions_other():
    r = resolve.resolve("오늘 문제", INDEX, date(2026, 11, 13))
    assert r.target.problem_id == "181936" and not r.target.note.startswith("오늘은 알림이 없어")
    r2 = resolve.resolve("오늘 문제", INDEX, SAT)
    assert "SWEA" in r2.target.note


def test_last_week_multiple_asks_for_number():
    r = resolve.resolve("지난주 문제 해설", INDEX, date(2026, 11, 18))   # 지난주=11/9~11/15 → 2건
    assert r.target is None and "2건" in r.message


# ---------------------------------------------------------------- 문제 파싱
def test_programmers_parse(fixtures):
    title, st, params, ex, kind = pb.parse_programmers((fixtures / "programmers_181936.html").read_text(encoding="utf-8"))
    assert title == "공배수" and kind == "function"
    assert params == ["number", "n", "m"]
    assert ex == [{"args": [60, 2, 3], "expected": 1}, {"args": [55, 10, 5], "expected": 0}]
    assert "배수" in st


def test_cell_values():
    assert pb._cell_value("[1, 2, 3]") == [1, 2, 3] and pb._cell_value('"abc"') == "abc"
    assert pb._cell_value("true") is True and pb._cell_value("hello") == "hello"


# ---------------------------------------------------------------- 풀이 파싱
def test_parse_solution_code_block():
    text = "먼저 나머지를 확인한다.\n\n```python\ndef solution(a):\n    return a\n```\n끝."
    approach, code = generate.parse_solution(text)
    assert "나머지" in approach and code.startswith("def solution")
    assert generate.parse_solution("코드 없음")[1] == ""


# ---------------------------------------------------------------- 비교
def test_compare_rules():
    assert sb.text_equal("1 2 \n3\n", "1 2\n3")
    assert sb.text_equal("0.3333333", "0.33333330001")
    assert not sb.text_equal("1 2", "1 3")
    assert sb.values_equal([1, 2.0], [1, 2.0000001]) and not sb.values_equal([1], [2])


# ---------------------------------------------------------------- 샌드박스 (Docker 필요)
EX = [{"args": [60, 2, 3], "expected": 1}, {"args": [55, 10, 5], "expected": 0}]
GOOD = "def solution(number, n, m):\n    return 1 if number % n == 0 and number % m == 0 else 0"


def test_sandbox_pass_and_fail():
    assert all(r.passed for r in sb.run_examples("function", GOOD, EX))
    res = sb.run_examples("function", "def solution(number, n, m):\n    return 1", EX)
    assert [r.passed for r in res] == [True, False]


def test_sandbox_blocks_imports_open_and_syntax_errors():
    r = sb.run_examples("function", "import os\ndef solution(number, n, m):\n    return os.getcwd()", EX[:1])[0]
    assert not r.passed and "허용되지 않은 모듈" in r.stderr
    r = sb.run_examples("function", "def solution(number, n, m):\n    return open('/etc/passwd').read()", EX[:1])[0]
    assert not r.passed and "open" in r.stderr
    r = sb.run_examples("function", "def solution(:\n", EX[:1])[0]
    assert not r.passed and "SyntaxError" in r.stderr


def test_sandbox_timeout(monkeypatch):
    monkeypatch.setattr(sb.config, "RUN_TIMEOUT_SEC", 1)
    r = sb.run_examples("function", "def solution(number, n, m):\n    while True: pass", EX[:1])[0]
    assert r.timed_out and not r.passed


def test_sandbox_stdio_and_no_examples():
    code = "n=int(input())\nfor i in range(n):\n    a,b=map(int,input().split())\n    print(f'#{i+1} {a+b}')"
    assert sb.run_examples("stdio", code, [{"input": "2\n1 2\n3 4\n", "expected": "#1 3\n#2 7"}])[0].passed
    assert sb.run_examples("function", GOOD, []) == []
