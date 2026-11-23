"""슬랙 메시지 파서와 수집기 (상세구현명세서 2.2, 6.3).

웹훅 메시지는 blocks 중심이므로 blocks를 먼저 읽고, 비어 있으면 text를 쓴다.
"""
import html
import logging
import re
from dataclasses import dataclass, field
from datetime import date

from src.common.text import epoch_to_kst, norm_text, norm_url

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- blocks → 텍스트
def flatten_blocks(blocks: list[dict] | None) -> tuple[str, list[str], list[str]]:
    """(줄바꿈으로 이은 텍스트, 버튼 URL 목록, 이미지 URL 목록)"""
    lines, urls, images = [], [], []
    for b in blocks or []:
        t = b.get("type")
        if t in ("header", "section"):
            tx = (b.get("text") or {}).get("text")
            if tx:
                lines.append(tx)
            for f in b.get("fields") or []:
                if f.get("text"):
                    lines.append(f["text"])
        elif t == "context":
            parts = [e.get("text", "") for e in b.get("elements") or [] if e.get("text")]
            if parts:
                lines.append(" ".join(parts))
        elif t == "actions":
            for e in b.get("elements") or []:
                if e.get("url"):
                    urls.append(e["url"])
        elif t == "image" and b.get("image_url"):
            images.append(b["image_url"])
    return "\n".join(lines), urls, images


def message_text(msg: dict) -> str:
    text, _, _ = flatten_blocks(msg.get("blocks"))
    return html.unescape(text if text.strip() else (msg.get("text") or ""))


# ---------------------------------------------------------------- 기사 (GeekNews, AI타임스 계열)
@dataclass
class SlackArticle:
    title: str
    url: str
    summary: str
    source_name: str
    published_epoch: int
    truncated: bool = False
    topic_id: str = ""
    extra: dict = field(default_factory=dict)


_TITLE_LINE = re.compile(r"^\*<(?P<url>[^|>]+)\|(?P<title>.+?)>\*\s*$")


def _split_article(text: str):
    lines = [l for l in html.unescape(text).splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return None
    m = _TITLE_LINE.match(lines[0].strip())
    if not m:
        return None
    return m["url"], m["title"], lines[1:]


def parse_geeknews(text: str, ts: str | float) -> SlackArticle | None:
    parsed = _split_article(text)
    if not parsed or "news.hada.io" not in parsed[0]:
        return None
    url, title, rest = parsed
    summary_lines = [l.strip()[2:].strip() for l in rest if l.strip().startswith("- ")]
    summary = " ".join(summary_lines).strip()
    clean = norm_url(url)
    tid = re.search(r"[?&]id=(\d+)", clean)
    return SlackArticle(
        title=norm_text(title), url=clean, summary=summary, source_name="GeekNews",
        published_epoch=int(float(ts)), truncated=summary.endswith(("…", "...")),
        topic_id=tid[1] if tid else "",
    )


def parse_aitimes(text: str, ts: str | float) -> SlackArticle | None:
    parsed = _split_article(text)
    if not parsed or "aitimes." not in parsed[0]:
        return None
    url, title, rest = parsed
    summary = norm_text(" ".join(l for l in rest if l.strip()))
    if summary == "요약 정보가 없습니다.":
        summary = ""
    clean = norm_url(url)
    return SlackArticle(
        title=norm_text(title), url=clean, summary=summary,
        source_name="인공지능신문" if "aitimes.kr" in clean else "AI TIMES",
        published_epoch=int(float(ts)), truncated=summary.endswith(("…", "...")),
    )


def parse_news_message(msg: dict) -> SlackArticle | None:
    text, ts = message_text(msg), msg.get("ts", 0)
    return parse_geeknews(text, ts) or parse_aitimes(text, ts)


# ---------------------------------------------------------------- 코딩테스트 알림
@dataclass
class Notice:
    platform: str
    problem_id: str
    title: str
    url: str
    level: str
    participants: int
    rate: float
    sent_date: date | None
    count: int = 0


_N_LINK = re.compile(r"<(?P<url>https?://[^|>]+)\|(?P<id>\d+)번 : (?P<title>[^>]+)>")
_N_LEVEL = re.compile(r"레벨 (?P<level>\d+)")
_N_PART = re.compile(r"참여 인원 : \*(?P<n>[\d,]+)명\*")
_N_RATE = re.compile(r"정답률 : \*(?P<rate>[\d.]+)%\*")
_N_DATE = re.compile(r"전송일 : \*(?P<yy>\d\d)/(?P<mm>\d\d)/(?P<dd>\d\d)\*")
_N_COUNT = re.compile(r"문제\s*-\s*(\d+)")


def parse_notice(text: str) -> Notice | None:
    text = html.unescape(text or "")
    link = _N_LINK.search(text)
    if not link:  # 소진 알림 등 시스템 메시지는 여기서 걸러짐
        return None
    url = html.unescape(link["url"])
    platform = "programmers" if "programmers" in url else ("swea" if "swexpertacademy" in url else "")
    if not platform:
        return None
    lv, pt, rt, dt, ct = (_N_LEVEL.search(text), _N_PART.search(text), _N_RATE.search(text),
                          _N_DATE.search(text), _N_COUNT.search(text))
    sent = None
    if dt:
        try:
            sent = date(2000 + int(dt["yy"]), int(dt["mm"]), int(dt["dd"]))
        except ValueError:
            pass
    return Notice(
        platform=platform, problem_id=link["id"], title=norm_text(link["title"]), url=url,
        level=lv["level"] if lv else "", participants=int(pt["n"].replace(",", "")) if pt else 0,
        rate=float(rt["rate"]) if rt else 0.0, sent_date=sent, count=int(ct[1]) if ct else 0,
    )


# ---------------------------------------------------------------- 공모전 메시지 (선택)
def parse_contest_message(msg: dict) -> dict | None:
    text, urls, images = flatten_blocks(msg.get("blocks"))
    m = re.match(r"^\*(?P<t>.+?)\*", text.strip()) if text else None
    act = next((u for u in urls if "linkareer.com/activity/" in u), "")
    if not (m and act):
        return None
    return {"title": norm_text(m["t"]), "url": norm_url(act), "poster": images[0] if images else ""}


# ---------------------------------------------------------------- 수집기
def find_channel_id(client, name: str) -> str | None:
    """채널 ID는 코드에 쓰지 않고 이름으로 조회한다."""
    cursor = None
    while True:
        res = client.conversations_list(types="public_channel,private_channel", limit=200,
                                        cursor=cursor, exclude_archived=True)
        for c in res.get("channels", []):
            if c.get("name") == name:
                return c["id"]
        cursor = (res.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return None


def fetch_history(client, channel_id: str, oldest: str | float = 0):
    """conversations.history를 next_cursor가 없을 때까지 돌며 메시지를 낸다."""
    cursor = None
    while True:
        res = client.conversations_history(channel=channel_id, oldest=str(oldest), limit=200, cursor=cursor)
        yield from res.get("messages", [])
        cursor = (res.get("response_metadata") or {}).get("next_cursor")
        if not (res.get("has_more") and cursor):
            return


def collect_news(client, channel_id: str, oldest: str | float) -> tuple[list[SlackArticle], str]:
    arts, last_ts, skipped = [], str(oldest), 0
    for msg in fetch_history(client, channel_id, oldest):
        if float(msg.get("ts", 0)) > float(last_ts):
            last_ts = msg["ts"]
        a = parse_news_message(msg)
        if a:
            arts.append(a)
        else:
            skipped += 1
    if skipped:
        log.info("소식 채널: 형식을 읽지 못해 건너뛴 메시지 %d건", skipped)
    return arts, last_ts


def collect_notices(client, channel_id: str, oldest: str | float) -> tuple[list[Notice], str]:
    out, last_ts = [], str(oldest)
    for msg in fetch_history(client, channel_id, oldest):
        if float(msg.get("ts", 0)) > float(last_ts):
            last_ts = msg["ts"]
        n = parse_notice(message_text(msg))
        if n:
            if n.sent_date is None:
                n.sent_date = epoch_to_kst(msg["ts"]).date()
            out.append(n)
    return out, last_ts
