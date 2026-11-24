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
# 'otp' 같은 짧은 단어는 JS 변수명(var getOtpFlag = false)에도 있어 오탐이 난다 → 실제 요구 신호만 본다
_BLOCK_PAT = re.compile(
    r"g-recaptcha|class=[\"'][^\"']*captcha|<img[^>]+captcha|보안\s*문자|자동\s*입력\s*방지|추가\s*인증|2\s*단계\s*인증|"
    r"getOtpFlag\s*=\s*true", re.I)


def _credentials() -> tuple[str, str]:
    uid, pw = config.env("SWEA_ID"), config.env("SWEA_PW")
    if not uid or not pw:
        raise LoginBlocked("SWEA 계정이 설정되지 않아 문제를 읽지 못했습니다.")
    return uid, pw


LOGIN_URL = "https://swexpertacademy.com/main/identity/anonymous/login.do"
# 로그인 응답 JSON의 message → 사용자 안내. 5회 연속 실패하면 계정이 잠기므로 실패 시 재시도하지 않는다.
_FAIL_MSG = {
    "LoginIdFail": "SWEA에 없는 ID입니다. .env의 SWEA_ID를 확인해 주세요.",
    "LoginIdPwdFail": "SWEA 로그인에 실패했습니다. SWEA_PW를 확인해 주세요(5회 실패 시 계정이 잠깁니다).",
    "LoginPwdErrorCount": "SWEA 계정이 로그인 실패 5회로 잠겨 문제를 읽지 못했습니다. 비밀번호 찾기가 필요합니다.",
    "LoginInactive": "SWEA 계정이 비활성화 상태입니다. 이메일 인증이 필요합니다.",
    "BlockedId": "SWEA 계정이 차단(Block)되어 문제를 읽지 못했습니다.",
    "DormancyAccount": "SWEA 휴면 계정입니다. 사이트에서 직접 휴면 해제 후 다시 시도해 주세요.",
    "tempPwdExpired": "SWEA 임시 비밀번호가 만료되었습니다. 비밀번호를 재발급받아야 합니다.",
    "mfaError": _BLOCK_MSG,
}
_login_failure: str | None = None   # 자격증명 거부 시 프로세스가 살아 있는 동안 재시도하지 않는다(계정 잠금 방지)


def _login() -> requests.Session:
    global _login_failure
    if _login_failure:
        raise LoginBlocked(_login_failure)
    uid, pw = _credentials()
    s = requests.Session()
    s.headers["User-Agent"] = config.HTTP_USER_AGENT
    page = s.get(LOGIN_PAGE, timeout=config.HTTP_TIMEOUT_SEC)
    if _BLOCK_PAT.search(page.text):
        raise LoginBlocked(_BLOCK_MSG)
    # 사이트의 로그인 버튼은 폼 제출이 아니라 이 주소로 보내는 AJAX(JSON) 요청이다.
    r = s.post(LOGIN_URL, data={"id": uid, "pwd": pw, "lang": "ko_KR", "clientTimezone": "Asia/Seoul"},
               headers={"X-Requested-With": "XMLHttpRequest", "Referer": LOGIN_PAGE}, timeout=config.HTTP_TIMEOUT_SEC)
    try:
        ret = r.json()
    except ValueError:
        raise LoginBlocked("SWEA 로그인 응답을 해석하지 못해 문제를 읽지 못했습니다.") from None
    msg = str(ret.get("message") or "")
    log.info("SWEA 로그인 응답: success=%s message=%s", bool(ret.get("success")), msg or "-")  # 계정·쿠키는 기록하지 않음
    if ret.get("success") and msg == "mfa":
        raise LoginBlocked(_BLOCK_MSG)          # 2차 인증은 우회하지 않는다
    if not ret.get("success"):
        text = _FAIL_MSG.get(msg, "SWEA 로그인에 실패해 문제를 읽지 못했습니다.")
        if msg in ("LoginIdFail", "LoginIdPwdFail", "LoginPwdErrorCount", "LoginInactive", "BlockedId",
                   "DormancyAccount", "tempPwdExpired"):
            _login_failure = text
        raise LoginBlocked(text)
    return s


def fetch_problem_html(url: str) -> str | None:
    global _session
    with _lock:
        if _session is None:
            _session = _login()
        r = _session.get(url, timeout=config.HTTP_TIMEOUT_SEC)
        if r.status_code != 200 or 'id="LoginForm"' in r.text or re.search(r"로그인이 필요", r.text[:3000]):
            _session = None  # 세션 만료: 다음 요청에서 다시 로그인
            return None
        return r.text


def _box_text(node) -> str:
    """<br> 기준으로 줄을 나눠 텍스트를 얻는다(&nbsp; 정리)."""
    for br in node.find_all("br"):
        br.replace_with("\n")
    return "\n".join(l.strip() for l in node.get_text().replace("\xa0", " ").splitlines() if l.strip())


def parse_problem(html_str: str) -> tuple[str, list[dict]]:
    """본문 텍스트와 예시. 본문은 .box4, 제한은 .box3, 예시는 .box_type1의 입력/출력 상자(.box5).
    샘플이 파일 다운로드로만 제공되면 예시는 빈 목록."""
    soup = BeautifulSoup(html_str, "html.parser")
    for t in soup(["script", "style"]):
        t.decompose()
    parts = []
    box3, box4 = soup.select_one(".box3"), soup.select_one(".box4")
    if box3:
        parts.append(_box_text(box3))
    if box4:
        parts.append(_box_text(box4))
    examples: list[dict] = []
    left, right = soup.select_one(".box_type1 .left .box5"), soup.select_one(".box_type1 .right .box5")
    if left and right:
        def sample(box) -> str:
            for x in box.select(".title1, .down_area"):
                x.decompose()
            return _box_text(box)
        inp, out = sample(left), sample(right)
        if inp and out:
            examples = [{"input": inp, "expected": out}]
    if not parts:  # 구조가 바뀐 경우의 대비: 문서 전체 텍스트
        node = soup.select_one(".problem_box, .problem-view, #problemView, .problem_view") or soup
        parts.append(_box_text(node))
    return "\n\n".join(parts)[:3000], examples
