"""생성한 풀이를 격리 실행해 예시와 비교한다 (상세구현명세서 8.3).

1순위 Docker(--network none, 읽기 전용, 메모리·프로세스 제한). Docker를 쓸 수 없으면 로컬 subprocess(1차 방어)로 대체한다.
문제 페이지의 글이 프롬프트에 들어가므로 격리는 필수다. import 허용 목록과 open 제거는 보조 수단이다.
"""
import json
import logging
import math
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass

from src import config

log = logging.getLogger(__name__)
ALLOWED_MODULES = ["math", "itertools", "collections", "heapq", "bisect", "functools", "re", "string", "fractions",
                   "decimal", "operator", "copy", "typing", "statistics", "array", "datetime", "sys"]
MARKER = "__RESULT__"

RUNNER = r'''
import builtins, copy, io, json, os, signal, sys, traceback
HERE = os.path.dirname(os.path.abspath(__file__))
cfg = json.load(open(os.path.join(HERE, "cases.json"), encoding="utf-8"))
CODE = open(os.path.join(HERE, "solution.py"), encoding="utf-8").read()
ALLOWED = set(cfg["allowed"])
real_import, real_stdout = builtins.__import__, sys.stdout

def guarded(name, g=None, l=None, fromlist=(), level=0):
    if name.split(".")[0] not in ALLOWED:
        raise ImportError("허용되지 않은 모듈: " + name.split(".")[0])
    return real_import(name, g, l, fromlist, level)

safe = {k: getattr(builtins, k) for k in dir(builtins) if k not in ("open", "breakpoint", "exit", "quit", "help")}
safe["__import__"] = guarded

class TO(Exception): pass
def on_alarm(*a): raise TO()
signal.signal(signal.SIGALRM, on_alarm)

def jsonable(v):
    return json.loads(json.dumps(v, default=repr))

out = []
for i, case in enumerate(cfg["cases"]):
    r = {"id": i, "actual": None, "error": "", "timeout": False}
    sys.stdout = io.StringIO()
    try:
        g = {"__builtins__": safe, "__name__": "__solution__"}
        signal.setitimer(signal.ITIMER_REAL, cfg["timeout"])
        if cfg["kind"] == "stdio":
            sys.stdin = io.StringIO(case["input"])
            exec(compile(CODE, "solution", "exec"), g)
            r["actual"] = sys.stdout.getvalue()
        else:
            exec(compile(CODE, "solution", "exec"), g)
            r["actual"] = jsonable(g["solution"](*copy.deepcopy(case["args"])))
    except TO:
        r["timeout"] = True
    except BaseException as e:
        tb = traceback.format_exception_only(type(e), e)
        r["error"] = "".join(tb).strip()[-300:]
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        sys.stdout = real_stdout
    out.append(r)
print("\n" + "__RESULT__" + json.dumps(out, ensure_ascii=False))
'''


@dataclass
class RunResult:
    case_id: int
    passed: bool
    actual: object
    expected: object
    stderr: str = ""
    timed_out: bool = False


# ---------------------------------------------------------------- 비교
def _num(s: str):
    try:
        return float(s)
    except ValueError:
        return None


def text_equal(expected: str, actual: str) -> bool:
    """양끝·줄 끝 공백 무시, 줄 단위 비교. 숫자 토큰은 상대 오차 1e-6."""
    e = [l.rstrip() for l in str(expected).strip().splitlines()]
    a = [l.rstrip() for l in str(actual).strip().splitlines()]
    if len(e) != len(a):
        return False
    for le, la in zip(e, a):
        if le == la:
            continue
        te, ta = le.split(), la.split()
        if len(te) != len(ta):
            return False
        for x, y in zip(te, ta):
            if x == y:
                continue
            fx, fy = _num(x), _num(y)
            if fx is None or fy is None or not math.isclose(fx, fy, rel_tol=1e-6, abs_tol=1e-9):
                return False
    return True


def values_equal(expected, actual) -> bool:
    if isinstance(expected, float) or isinstance(actual, float):
        try:
            return math.isclose(float(expected), float(actual), rel_tol=1e-6, abs_tol=1e-9)
        except (TypeError, ValueError):
            return False
    if isinstance(expected, (list, tuple)) and isinstance(actual, (list, tuple)):
        return len(expected) == len(actual) and all(values_equal(x, y) for x, y in zip(expected, actual))
    if isinstance(expected, dict) and isinstance(actual, dict):
        return expected.keys() == actual.keys() and all(values_equal(expected[k], actual[k]) for k in expected)
    return expected == actual


# ---------------------------------------------------------------- 실행
def _limits():  # 로컬 대체 방식 전용
    import resource
    mem = config.RUN_MEM_LIMIT_MB * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (mem * 2, mem * 2))
    resource.setrlimit(resource.RLIMIT_CPU, (config.RUN_TIMEOUT_SEC * 20, config.RUN_TIMEOUT_SEC * 20))
    resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))


def _docker_cmd(tmp: str, total: int) -> list[str]:
    return ["docker", "run", "--rm", "--network", "none", "--read-only", "--memory", f"{config.RUN_MEM_LIMIT_MB}m",
            "--cpus", "1", "--pids-limit", "64", "--user", "65534", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "-v", f"{tmp}:/work:ro", config.SANDBOX_IMAGE,
            "timeout", str(total), "python", "-I", "-B", "/work/runner.py"]


def _execute(tmp: str, total: int) -> tuple[str, str, bool]:
    """(stdout, stderr, 전체 시간 초과 여부)"""
    use_docker = config.SANDBOX == "docker" and shutil.which("docker")
    if use_docker:
        try:
            p = subprocess.run(_docker_cmd(tmp, total), capture_output=True, text=True, timeout=total + 15)
            if "Cannot connect to the Docker daemon" not in p.stderr and p.returncode != 125:
                return p.stdout, p.stderr, p.returncode == 124
            log.warning("Docker를 쓸 수 없어 로컬 실행으로 대체합니다")
        except subprocess.TimeoutExpired:
            return "", "", True
    env = {"PYTHONIOENCODING": "utf-8", "PATH": os.environ.get("PATH", "/usr/bin")}
    try:
        p = subprocess.run([sys.executable, "-I", "-B", os.path.join(tmp, "runner.py")], cwd=tmp, env=env,
                           capture_output=True, text=True, timeout=total, preexec_fn=_limits)
        return p.stdout, p.stderr, False
    except subprocess.TimeoutExpired:
        return "", "", True


def run_examples(kind: str, code: str, examples: list[dict]) -> list[RunResult]:
    """예시마다 실행해 기대값과 비교한다. 예시가 없으면 빈 목록(검증 불가)."""
    if not examples:
        return []
    try:
        compile(code, "solution", "exec")
    except SyntaxError as e:
        return [RunResult(i, False, None, ex.get("expected"), f"SyntaxError: {e.msg} (줄 {e.lineno})") for i, ex in enumerate(examples)]
    total = config.RUN_TIMEOUT_SEC * len(examples) + 5
    with tempfile.TemporaryDirectory(prefix="ailab_run_") as tmp:
        os.chmod(tmp, 0o755)
        files = {"solution.py": code, "runner.py": RUNNER,
                 "cases.json": json.dumps({"kind": kind, "timeout": config.RUN_TIMEOUT_SEC, "allowed": ALLOWED_MODULES,
                                           "cases": examples}, ensure_ascii=False, default=repr)}
        for name, content in files.items():
            path = os.path.join(tmp, name)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            os.chmod(path, 0o644)
        stdout, stderr, whole_timeout = _execute(tmp, total)
    if whole_timeout:
        return [RunResult(i, False, None, ex.get("expected"), "시간 초과", True) for i, ex in enumerate(examples)]
    raw = stdout.split(MARKER)[-1] if MARKER in stdout else ""
    try:
        outs = json.loads(raw)
    except ValueError:
        err = (stderr or stdout)[-300:] or "실행 결과를 읽지 못했습니다"
        return [RunResult(i, False, None, ex.get("expected"), err) for i, ex in enumerate(examples)]
    results = []
    for o, ex in zip(outs, examples):
        exp = ex.get("expected")
        if o["timeout"] or o["error"]:
            ok = False
        elif kind == "stdio":
            ok = text_equal(exp, o["actual"] or "")
        else:
            ok = values_equal(json.loads(json.dumps(exp, default=repr)), o["actual"])
        results.append(RunResult(o["id"], ok, o["actual"], exp, (o["error"] or ("시간 초과" if o["timeout"] else ""))[:500], o["timeout"]))
    return results
