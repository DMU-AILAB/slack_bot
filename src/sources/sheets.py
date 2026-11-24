"""구글 시트 CSV 로더 (읽기 전용, 상세구현명세서 6.2). URL은 토큰처럼 취급해 로그에 찍지 않는다."""
import csv
import io
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime

import requests

from src import config
from src.common.text import norm_text, norm_url, parse_date, parse_dt, title_deadline

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- 다운로드
class SheetNotCsv(Exception):
    """CSV가 아니라 HTML(로그인·편집 화면)이 돌아온 경우. URL 값은 메시지에 넣지 않는다."""


def csv_url(url: str) -> str:
    """편집 화면 주소(/d/<id>/edit?…#gid=N)를 CSV 내보내기 주소로 바꾼다. 게시 주소(/d/e/…/pub)는 그대로 둔다."""
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)/(?:edit|view)", url)
    if not m or "/d/e/" in url:
        return url
    gid = re.search(r"gid=(\d+)", url)
    return f"https://docs.google.com/spreadsheets/d/{m[1]}/export?format=csv" + (f"&gid={gid[1]}" if gid else "")


def fetch_csv(url: str) -> list[dict]:
    r = requests.get(csv_url(url), timeout=config.HTTP_TIMEOUT_SEC)
    r.raise_for_status()
    r.encoding = "utf-8"
    if "html" in r.headers.get("content-type", "").lower() or r.text.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        raise SheetNotCsv("시트 응답이 CSV가 아님: '웹에 게시'(CSV) 주소이거나 링크 공유가 켜져 있어야 함")
    return parse_csv_text(r.text)


def parse_csv_text(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for raw in reader:
        # 헤더보다 칸이 많은 행은 DictReader가 키 None에 리스트로 담는다 → 버린다
        rows.append({k.strip(): (v or "").strip() for k, v in raw.items()
                     if isinstance(k, str) and not isinstance(v, list)})
    return rows


# ---------------------------------------------------------------- 공모전
@dataclass
class ContestRow:
    activity_id: str
    title: str
    url: str
    collected_at: datetime | None
    start: date | None
    deadline: date | None
    deadline_source: str  # sheet | title | none


def parse_contest_rows(rows: list[dict]) -> list[ContestRow]:
    out, skipped = [], 0
    for r in rows:
        url = norm_url(r.get("주소", ""))
        m = re.search(r"/activity/(\d+)", url)
        if not url.startswith("http") or not m:
            skipped += 1
            continue
        title = norm_text(r.get("공모전 제목", ""))
        collected = parse_dt(r.get("수집시간"))
        start = parse_date(r.get("시작일"))
        deadline, src = parse_date(r.get("마감일")), "sheet"
        if deadline is None:
            deadline = title_deadline(title, collected)
            src = "title" if deadline else "none"
        out.append(ContestRow(m[1], title, url, collected, start, deadline, src))
    if skipped:
        log.warning("공모전 시트: 주소가 올바르지 않아 건너뛴 행 %d건", skipped)
    return out


# ---------------------------------------------------------------- 소식
@dataclass
class NewsRow:
    title: str
    url: str
    source_name: str
    collected_at: datetime | None


def source_name_from_url(url: str) -> str:
    u = url.lower()
    if "aitimes.kr" in u:
        return "인공지능신문"
    if "aitimes.com" in u:
        return "AI TIMES"
    if "news.hada.io" in u:
        return "GeekNews"
    return "기타"


def parse_news_rows(rows: list[dict]) -> list[NewsRow]:
    out, skipped = [], 0
    for r in rows:
        url = norm_url(r.get("주소", ""))
        if not url.startswith("http"):
            skipped += 1
            continue
        out.append(NewsRow(
            title=norm_text(r.get("기사 제목", "")),
            url=url,
            source_name=source_name_from_url(url),
            collected_at=parse_dt(r.get("수집시간")),
        ))
    if skipped:
        log.warning("소식 시트: 건너뛴 행 %d건", skipped)
    return out


# ---------------------------------------------------------------- 코딩테스트
@dataclass
class ProblemRow:
    platform: str  # programmers | swea
    problem_id: str
    title: str
    tier: str
    participants: int
    rate: float
    done: bool
    hashcode: str
    url: str


def problem_url(platform: str, problem_id: str, hashcode: str = "") -> str:
    if platform == "programmers":
        return f"https://school.programmers.co.kr/learn/courses/30/lessons/{problem_id}"
    return f"https://swexpertacademy.com/main/code/problem/problemDetail.do?contestProbId={hashcode}"


def _num(s: str, cast=float, default=0):
    try:
        return cast(re.sub(r"[^\d.]", "", s or "") or default)
    except ValueError:
        return default


def parse_coding_rows(rows: list[dict], platform: str) -> list[ProblemRow]:
    out = []
    for r in rows:
        pid = norm_text(r.get("문제번호", ""))
        if not pid:
            continue
        h = norm_text(r.get("해시코드", ""))
        out.append(ProblemRow(
            platform=platform, problem_id=pid, title=norm_text(r.get("제목", "")),
            tier=norm_text(r.get("티어", "")), participants=_num(r.get("참여 인원", ""), int),
            rate=_num(r.get("정답률", ""), float), done=r.get("완료여부", "").strip() == "완료",
            hashcode=h, url=problem_url(platform, pid, h),
        ))
    return out
