"""문제 본문과 입출력 예시 읽기 (상세구현명세서 8.3). 질문 1건당 페이지 1개, 번호 기준 캐시."""
import ast
import json
import logging
import re
from dataclasses import asdict, dataclass, field

from bs4 import BeautifulSoup

from src.common.text import norm_text
from src.sources import web

log = logging.getLogger(__name__)
STATEMENT_MAX_CHARS = 3000   # 4096 컨텍스트 예산: 풀이 900토큰 + 프롬프트 여유


@dataclass
class Problem:
    platform: str
    problem_id: str
    title: str
    url: str
    statement: str = ""
    examples: list[dict] = field(default_factory=list)   # function: {"args":[...],"expected":...} / stdio: {"input","expected"}
    kind: str = "function"       # function | stdio | sql
    params: list[str] = field(default_factory=list)
    error: str = ""              # 읽지 못한 이유(사용자 안내용)


def _cell_value(s: str):
    s = s.strip()
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "none"):
        return None
    try:
        return ast.literal_eval(s)
    except (ValueError, SyntaxError):
        return s.strip('"')


def parse_programmers(html_str: str) -> tuple[str, str, list[str], list[dict], str]:
    """(제목, 본문, 매개변수 이름, 예시, kind)"""
    soup = BeautifulSoup(html_str, "html.parser")
    title = norm_text((soup.title.string if soup.title else "").replace("코딩테스트 연습 -", "").split("|")[0])
    md = soup.select_one(".guide-section-description .markdown") or soup.select_one(".markdown")
    statement = web.fragment_to_text(str(md)) if md else ""
    cat = re.search(r'challenge_category(?:&quot;|")\s*:\s*(?:&quot;|")(\w+)', html_str)
    # 프로그래머스 SQL 문제의 분류값은 'database'이고 편집기 언어는 mysql/oracle이다 (실제 페이지로 확인)
    is_sql = ((cat and cat[1].lower() in ("sql", "database"))
              or re.search(r'data-language=(?:"|&quot;)(?:mysql|oracle)', html_str) is not None
              or re.search(r"\bSELECT\b|SQL\s*문을\s*작성", statement) is not None)
    kind = "sql" if is_sql else "function"
    params, examples = [], []
    tables = md.find_all("table") if md else []
    table = next((t for t in tables if re.search(r"result|return|answer", t.get_text(" ").lower().split("tbody")[0][:200])), None) or (tables[0] if tables else None)
    if table:
        head = [norm_text(th.get_text()) for th in table.find_all("th")]
        for tr in table.find("tbody").find_all("tr") if table.find("tbody") else []:
            cells = [norm_text(td.get_text(" ")) for td in tr.find_all("td")]
            if len(cells) == len(head) and len(cells) >= 2:
                examples.append({"args": [_cell_value(c) for c in cells[:-1]], "expected": _cell_value(cells[-1])})
        params = head[:-1]
    return title, statement, params, examples, kind


def load_problem(platform: str, problem_id: str, title: str, url: str) -> Problem:
    cached = web.cache_get("problems", f"{platform}_{problem_id}")
    if cached:
        return Problem(**cached)
    p = Problem(platform=platform, problem_id=problem_id, title=title, url=url)
    if platform == "programmers":
        html_str = web.fetch_html(url)
        if not html_str:
            p.error = "문제 페이지를 읽지 못했습니다."
            return p
        t, st, params, ex, kind = parse_programmers(html_str)
        p.title, p.statement, p.params, p.examples, p.kind = t or title, st, params, ex, kind
        if not st:
            p.error = "문제 본문을 찾지 못했습니다."
            return p
    else:
        from src.coding import swea_client
        p.kind = "stdio"
        try:
            html_str = swea_client.fetch_problem_html(url)
        except swea_client.LoginBlocked as e:
            p.error = str(e)
            return p
        if not html_str:
            p.error = "문제 페이지를 읽지 못했습니다."
            return p
        p.statement, p.examples = swea_client.parse_problem(html_str)
    if not p.error:
        web.cache_put("problems", f"{platform}_{problem_id}", asdict(p))
    return p
