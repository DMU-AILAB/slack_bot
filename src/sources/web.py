"""외부 페이지 요청(캐시, 지연, robots.txt, 사설망 차단)과 링커리어 상세 파서 (상세구현명세서 6.4)."""
import ipaddress
import json
import logging
import re
import socket
import threading
import time
import urllib.robotparser
from datetime import date, datetime
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

from src import config
from src.common.text import KST, norm_text

log = logging.getLogger(__name__)
_lock = threading.Lock()
_last_request = 0.0
_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}


# ---------------------------------------------------------------- 캐시
def cache_path(kind: str, key: str):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", key)
    return config.CACHE_DIR / kind / f"{safe}.json"


def cache_get(kind: str, key: str, max_age_hours: float | None = None):
    p = cache_path(kind, key)
    if not p.exists():
        return None
    if max_age_hours is not None and time.time() - p.stat().st_mtime > max_age_hours * 3600:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def cache_put(kind: str, key: str, value) -> None:
    p = cache_path(kind, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- 안전한 요청
def is_safe_url(url: str) -> bool:
    """http(s)이고 사설망·루프백이 아닌 주소만 허용(SSRF 방지)."""
    p = urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    try:
        for info in socket.getaddrinfo(p.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
    except (socket.gaierror, ValueError):
        return False
    return True


def robots_allows(url: str) -> bool:
    p = urlsplit(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = requests.get(base + "/robots.txt", timeout=config.HTTP_TIMEOUT_SEC,
                             headers={"User-Agent": config.HTTP_USER_AGENT})
            if r.status_code == 200:
                rp.parse(r.text.splitlines())
                _robots[base] = rp
            else:
                _robots[base] = None  # robots.txt가 없으면 허용
        except requests.RequestException:
            _robots[base] = None
    rp = _robots[base]
    return True if rp is None else rp.can_fetch(config.HTTP_USER_AGENT, url)


def fetch_html(url: str, *, check_robots: bool = True) -> str | None:
    """요청 사이에 HTTP_DELAY_SEC 지연을 둔다. 실패하면 None(상태 코드만 로그)."""
    global _last_request
    if not is_safe_url(url):
        log.warning("허용되지 않는 주소라 읽지 않음")
        return None
    if check_robots and not robots_allows(url):
        log.info("robots.txt에서 허용되지 않아 읽지 않음: %s", urlsplit(url).netloc)
        return None
    with _lock:
        wait = config.HTTP_DELAY_SEC - (time.time() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.time()
    try:
        r = requests.get(url, timeout=config.HTTP_TIMEOUT_SEC, headers={"User-Agent": config.HTTP_USER_AGENT})
        if r.status_code != 200:
            log.warning("페이지 요청 실패: HTTP %s (%s)", r.status_code, urlsplit(url).netloc)
            return None
        r.encoding = r.apparent_encoding if r.encoding in (None, "ISO-8859-1") else r.encoding
        return r.text
    except requests.RequestException as e:
        log.warning("페이지 요청 예외: %s", type(e).__name__)
        return None


def html_to_text(html_str: str) -> str:
    soup = BeautifulSoup(html_str, "html.parser")
    for t in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        t.decompose()
    text = soup.get_text("\n")
    lines = [norm_text(l) for l in text.splitlines()]
    return "\n".join(l for l in lines if l)


def fragment_to_text(fragment: str) -> str:
    """<p>, <br> 단위로 줄을 나눠 텍스트로."""
    soup = BeautifulSoup(fragment or "", "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for p in soup.find_all(["p", "li", "div", "h1", "h2", "h3", "h4", "h5", "h6"]):
        p.append("\n")
    lines = [norm_text(l) for l in soup.get_text().splitlines()]
    return "\n".join(l for l in lines if l)


# ---------------------------------------------------------------- 링커리어 상세
SECTION_KEYS = {
    "theme": ["공모 주제", "공모주제", "주제", "과제", "공모 분야", "공모분야", "개요", "행사 개요"],
    "eligibility": ["참가 대상", "참가대상", "참가 자격", "참가자격", "지원 자격", "응모 자격", "응모자격",
                    "참여 대상", "모집 대상", "참가 조건", "대상"],
    "prize": ["시상 내역", "시상내역", "시상", "상금", "포상", "혜택", "상격"],
    "period": ["접수 기간", "접수기간", "모집 기간", "모집기간", "공모 기간", "일정", "기간", "접수 방법"],
    "criteria": ["심사 기준", "심사기준", "평가 기준", "평가기준", "심사 방법", "심사"],
}
_HEAD_MARK = "■□▶▷◆◇●○◎▣☞※★☆[【<"


def _is_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 30:
        return False
    return s[0] in _HEAD_MARK or bool(re.match(r"^\d+[.)]\s*\S", s))


def _heading_section(line: str) -> str | None:
    s = re.sub(r"^[■□▶▷◆◇●○◎▣☞※★☆\[【<\d.)\s]+|[\]】>:\s]+$", "", line.strip())
    if re.search(r"시상\s*(식|일정|발표|장소)|발표\s*일정", s):   # '시상' 단어가 있어도 시상 내역이 아닌 일정 항목
        return "period"
    for section, keys in SECTION_KEYS.items():
        if any(k in s for k in keys):
            return section
    return None


def split_sections(text: str) -> dict[str, str]:
    """본문을 제목 줄(■ …)로 나눠 theme/eligibility/prize/period/criteria 로 매핑한다. 못 찾으면 빈 문자열."""
    out = {k: "" for k in SECTION_KEYS}
    cur = None
    for line in text.splitlines():
        if _is_heading(line):
            cur = _heading_section(line)
            continue
        if cur:
            out[cur] = (out[cur] + "\n" + line).strip()
    return {k: v[:1200] for k, v in out.items()}


def _ms_to_date(ms) -> date | None:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, KST).date()
    except (TypeError, ValueError, OSError):
        return None


def _resolve_names(state: dict, value) -> list[str]:
    names = []
    for v in value if isinstance(value, list) else [value]:
        ref = state.get(v.get("__ref")) if isinstance(v, dict) else None
        if isinstance(ref, dict) and ref.get("name"):
            names.append(ref["name"])
        elif isinstance(v, str):
            names.append(v)
    return names


def parse_linkareer_detail(html_str: str, activity_id: str) -> dict | None:
    """__NEXT_DATA__의 Apollo 상태에서 주최, 접수 기간, 분야, 본문 항목을 뽑는다."""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html_str, re.S)
    if not m:
        return None
    try:
        state = json.loads(m.group(1))["props"]["pageProps"]["__APOLLO_STATE__"]
    except (KeyError, ValueError):
        return None
    act = state.get(f"Activity:{activity_id}")
    if not act:
        return None
    ref = (act.get("detailText") or {}).get("__ref")
    body = fragment_to_text((state.get(ref) or {}).get("text", "")) if ref else ""
    sections = split_sections(body)
    start, end = _ms_to_date(act.get("recruitStartAt")), _ms_to_date(act.get("recruitCloseAt"))
    topics = _resolve_names(state, act.get("interests", [])) + _resolve_names(state, act.get("categories", []))
    targets = _resolve_names(state, act.get("targets", []))
    benefits = _resolve_names(state, act.get("benefits", []))
    if not sections["eligibility"] and targets:
        sections["eligibility"] = ", ".join(targets)
    if not sections["prize"] and benefits:
        sections["prize"] = ", ".join(benefits)
    return {
        "activity_id": activity_id,
        "host": act.get("organizationName") or "",
        "start": start.isoformat() if start else "",
        "deadline": end.isoformat() if end else "",
        "homepage": act.get("homepageURL") or "",
        "topic": ", ".join(dict.fromkeys(topics)),
        "overview": body[:500],
        "sections": sections,
    }


def contest_detail(activity_id: str, url: str, *, refresh: bool = False) -> dict | None:
    """상세 페이지를 1회만 읽고 data/cache/contests에 저장한다."""
    if not refresh:
        hit = cache_get("contests", activity_id)
        if hit:
            return hit
    html_str = fetch_html(url)
    if not html_str:
        return None
    detail = parse_linkareer_detail(html_str, activity_id)
    if detail:
        cache_put("contests", activity_id, detail)
    return detail
