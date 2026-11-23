"""SWEA 로그인과 문제 읽기.

보안 규칙 (상세구현명세서 8.3, 10장)
- 계정은 이 모듈 안에서만 환경변수로 읽는다. 인자, LangGraph 상태, 로그, 추적에 넣지 않는다.
- 세션 쿠키는 메모리에만 둔다.
- 캡차나 추가 인증이 보이면 우회하지 않고 LoginBlocked로 멈춘다.
- 이 모듈에는 @traceable을 쓰지 않으며 LangChain 체인 밖에서 호출한다.

[확인] 로그인 폼의 실제 필드와 샘플 입출력 형식은 계정으로 직접 열어 보고 확정해야 한다.
이 구현은 폼을 동적으로 찾는 최선의 시도이며, 읽지 못하면 안내 문구로 끝낸다.
"""
import logging
import re
import threading
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src import config

log = logging.getLogger(__name__)
LOGIN_PAGE = "https://swexpertacademy.com/main/identity/anonymous/loginPage.do"
_lock = threading.Lock()
_session: requests.Session | None = None


class LoginBlocked(Exception):
    """캡차·추가 인증·약관 동의 등으로 자동 로그인이 불가능."""


_BLOCK_MSG = "로그인 단계에서 추가 인증이 요구되어 SWEA 문제를 읽지 못했습니다."
_BLOCK_PAT = re.compile(r"captcha|recaptcha|보안문자|자동입력방지|추가\s*인증|2단계|otp", re.I)


def _credentials() -> tuple[str, str]:
    uid, pw = config.env("SWEA_ID"), config.env("SWEA_PW")
    if not uid or not pw:
        raise LoginBlocked("SWEA 계정이 설정되지 않아 문제를 읽지 못했습니다.")
    return uid, pw


def _login() -> requests.Session:
    uid, pw = _credentials()
    s = requests.Session()
    s.headers["User-Agent"] = config.HTTP_USER_AGENT
    page = s.get(LOGIN_PAGE, timeout=config.HTTP_TIMEOUT_SEC)
    if _BLOCK_PAT.search(page.text):
        raise LoginBlocked(_BLOCK_MSG)
    soup = BeautifulSoup(page.text, "html.parser")
    form = next((f for f in soup.find_all("form") if f.find("input", {"type": "password"})), None)
    if not form:
        raise LoginBlocked("SWEA 로그인 폼을 찾지 못해 문제를 읽지 못했습니다.")
    data = {i.get("name"): i.get("value", "") for i in form.find_all("input") if i.get("name")}
    pw_field = form.find("input", {"type": "password"}).get("name")
    id_field = next((i.get("name") for i in form.find_all("input")
                     if i.get("type") in ("text", "email") and i.get("name")), None)
    if not (pw_field and id_field):
        raise LoginBlocked("SWEA 로그인 폼 형식을 알 수 없어 문제를 읽지 못했습니다.")
    data[id_field], data[pw_field] = uid, pw
    r = s.post(urljoin(LOGIN_PAGE, form.get("action") or LOGIN_PAGE), data=data, timeout=config.HTTP_TIMEOUT_SEC)
    if _BLOCK_PAT.search(r.text):
        raise LoginBlocked(_BLOCK_MSG)
    log.info("SWEA 로그인 시도 완료 (HTTP %s)", r.status_code)  # 계정·쿠키·응답 헤더는 기록하지 않음
    return s


def fetch_problem_html(url: str) -> str | None:
    global _session
    with _lock:
        if _session is None:
            _session = _login()
        r = _session.get(url, timeout=config.HTTP_TIMEOUT_SEC)
        if r.status_code != 200 or re.search(r"loginPage|로그인이 필요", r.text[:3000]):
            _session = None  # 세션 만료: 다음 요청에서 다시 로그인
            return None
        return r.text


def parse_problem(html_str: str) -> tuple[str, list[dict]]:
    """본문 텍스트와 예시. 샘플이 파일 다운로드로만 제공되면 예시는 빈 목록."""
    soup = BeautifulSoup(html_str, "html.parser")
    node = soup.select_one(".problem_box, .problem-view, #problemView, .problem_view") or soup
    for t in node(["script", "style"]):
        t.decompose()
    text = "\n".join(l.strip() for l in node.get_text("\n").splitlines() if l.strip())
    examples: list[dict] = []
    # '샘플 입력' / '샘플 출력' 이 <pre>로 나란히 있는 경우만 짝지어 사용
    pres = [p.get_text("\n").strip() for p in node.find_all("pre")]
    if len(pres) >= 2 and len(pres) % 2 == 0:
        examples = [{"input": pres[i], "expected": pres[i + 1]} for i in range(0, len(pres), 2)]
    return text[:3000], examples
