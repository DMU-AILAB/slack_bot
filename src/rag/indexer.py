"""수집·분할·저장 (상세구현명세서 6장). 실패해도 기존 인덱스를 그대로 쓴다."""
import json
import logging
import re
import time
from dataclasses import asdict
from datetime import timedelta

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src import config
from src.common.text import date_int, kst_now, kst_today, norm_text, parse_date, url_key
from src.rag import state
from src.rag.store import reset_all, upsert_changed
from src.sources import sheets, slack_history, web

log = logging.getLogger(__name__)
_splitter = RecursiveCharacterTextSplitter(chunk_size=config.CHUNK_SIZE, chunk_overlap=config.CHUNK_OVERLAP)
CODING_INDEX = config.CACHE_DIR / "coding_index.json"

AI_KEYWORDS = re.compile(
    r"\bAI\b|인공지능|LLM|GPT|딥러닝|머신러닝|생성형|에이전트|챗봇|오픈AI|OpenAI|Anthropic|Claude|Gemini|제미나이|"
    r"엔비디아|NVIDIA|딥시크|DeepSeek|RAG|파인튜닝|트랜스포머|모델|학습|추론|GPU|거대 ?언어|자율주행|로봇",
    re.I)


# ---------------------------------------------------------------- 슬랙 클라이언트
_client = None
_channel_ids: dict[str, str | None] = {}


def slack_client():
    global _client
    token = config.env("SLACK_BOT_TOKEN")
    if not token:
        return None
    if _client is None:
        from slack_sdk import WebClient
        _client = WebClient(token=token)
    return _client


def channel_id(key: str) -> str | None:
    c = slack_client()
    if c is None:
        return None
    if key not in _channel_ids:
        _channel_ids[key] = slack_history.find_channel_id(c, config.CHANNEL_NAMES[key])
        if not _channel_ids[key]:
            log.warning("슬랙 채널 '%s'를 찾지 못함 (봇 초대 여부 확인)", config.CHANNEL_NAMES[key])
    return _channel_ids[key]


def _oldest(key: str, backfill_days: int) -> str:
    return state.slack_last_ts(key) or str((kst_now() - timedelta(days=backfill_days)).timestamp())


# ---------------------------------------------------------------- 공모전
def contest_docs(row: sheets.ContestRow, detail: dict | None) -> list[tuple[str, str, dict]]:
    detail = detail or {}
    sec = detail.get("sections") or {}
    host, topic = detail.get("host", ""), detail.get("topic", "")
    start = row.start or parse_date(detail.get("start"))
    deadline = row.deadline or parse_date(detail.get("deadline"))
    src = row.deadline_source if row.deadline_source != "none" else ("detail" if deadline else "none")
    base = {
        "channel": "contest", "source": "링커리어", "title": row.title, "url": row.url,
        "date": row.collected_at.isoformat() if row.collected_at else "",
        "activity_id": row.activity_id, "collected_ts": date_int(row.collected_at.date()) if row.collected_at else 0,
        "start_ts": date_int(start), "deadline_ts": date_int(deadline), "has_deadline": deadline is not None,
        "deadline_source": src, "host": host, "topic": topic, "eligibility": (sec.get("eligibility") or "")[:200],
    }
    period = f"{start or '?'} ~ {deadline or '확인 필요'}"
    texts = {
        "overview": f"{row.title}\n주최: {host or '정보 없음'}\n분야: {topic or '정보 없음'}\n접수 기간: {period}\n{detail.get('overview', '')[:300]}",
        "period": f"{row.title}\n접수 기간: {period}\n{sec.get('period', '')}",
        "eligibility": f"{row.title}\n참가 대상: {sec['eligibility']}" if sec.get("eligibility") else "",
        "prize": f"{row.title}\n시상 내역: {sec['prize']}" if sec.get("prize") else "",
        "theme": f"{row.title}\n공모 주제: {sec['theme']}" if sec.get("theme") else "",
        "criteria": f"{row.title}\n심사 기준: {sec['criteria']}" if sec.get("criteria") else "",
    }
    docs = []
    for section, text in texts.items():
        if not text:
            continue
        for i, chunk in enumerate(_splitter.split_text(text) if len(text) > config.CHUNK_SIZE else [text]):
            docs.append((f"contest:{row.activity_id}:{section}:{i}", chunk, {**base, "section": section}))
    return docs


def index_contest() -> str:
    rows = sheets.parse_contest_rows(sheets.fetch_csv(config.sheet_url("contest")))
    today, budget, docs, detail_ok = kst_today(), config.ENRICH_MAX_PER_RUN, [], 0
    for r in rows:
        detail = web.cache_get("contests", r.activity_id)
        open_known = r.deadline is not None and r.deadline >= today
        recent_unknown = (config.ENRICH_UNKNOWN_DEADLINE and r.deadline is None and r.collected_at is not None
                          and (today - r.collected_at.date()).days <= config.ENRICH_RECENT_DAYS)
        if not detail and (open_known or (recent_unknown and budget > 0)):
            if recent_unknown:
                budget -= 1
            detail = web.contest_detail(r.activity_id, r.url)
            detail_ok += bool(detail)
        docs.extend(contest_docs(r, detail))
    changed, total = upsert_changed("contest", docs)
    return f"공모전 {len(rows)}건, 문서 {total}개 중 {changed}개 갱신 (상세 페이지 새로 읽음 {detail_ok}건)"


# ---------------------------------------------------------------- 소식
def _news_key(url: str) -> str:
    m = re.search(r"idxno=(\d+)", url)
    if m and "aitimes" in url:
        return f"aitimes{m[1]}"
    t = re.search(r"news\.hada\.io/topic\?id=(\d+)", url)
    return f"geek{t[1]}" if t else url_key(url)


def index_news() -> str:
    recs: dict[str, dict] = {}
    for key in ("news_inai", "news_aitimes"):
        u = config.sheet_url(key)
        if not u:
            continue
        try:
            for r in sheets.parse_news_rows(sheets.fetch_csv(u)):
                t = r.collected_at   # 시트 기사의 기준 시각은 수집시간
                recs[_news_key(r.url)] = {
                    "title": r.title, "url": r.url, "summary": "", "source_name": r.source_name,
                    "published_epoch": int(t.timestamp()) if t else 0, "truncated": False, "topic_id": "",
                }
        except Exception as e:  # 한 시트 실패가 전체를 막지 않게
            log.warning("소식 시트 %s 읽기 실패: %s", key, type(e).__name__)

    cid, slack_n = channel_id("news"), 0
    if cid:
        arts, last = slack_history.collect_news(slack_client(), cid, _oldest("news", config.SLACK_BACKFILL_DAYS))
        for a in arts:
            k = _news_key(a.url)
            prev = recs.get(k, {})
            recs[k] = {
                "title": a.title or prev.get("title", ""), "url": a.url, "summary": a.summary,
                "source_name": a.source_name,
                "published_epoch": prev.get("published_epoch") or a.published_epoch,
                "truncated": a.truncated, "topic_id": a.topic_id,
            }
        slack_n = len(arts)
        state.set_slack_last_ts("news", last)

    docs = []
    for k, r in recs.items():
        if not r["title"]:
            continue
        text = f"{r['title']}\n{r['summary'][:200]}".strip()
        pub = r["published_epoch"]
        docs.append((f"news:{k}", text, {
            "channel": "news", "source": r["source_name"], "title": r["title"], "url": r["url"],
            "date": time.strftime("%Y-%m-%d", time.localtime(pub)) if pub else "", "source_name": r["source_name"],
            "published_epoch": pub, "topic_id": r["topic_id"], "truncated": r["truncated"],
            "summary": r["summary"][:400], "ai_related": r["source_name"] != "GeekNews" or bool(AI_KEYWORDS.search(text)),
            "body_fetched": False,
        }))
    changed, total = upsert_changed("news", docs)
    return f"소식 {len(recs)}건(슬랙 {slack_n}건), 문서 {total}개 중 {changed}개 갱신"


# ---------------------------------------------------------------- 코딩테스트
def load_coding_index() -> dict:
    try:
        return json.loads(CODING_INDEX.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"problems": {"programmers": [], "swea": []}, "notices": []}


def index_coding() -> str:
    idx = load_coding_index()
    for platform, key in (("programmers", "coding_programmers"), ("swea", "coding_swea")):
        u = config.sheet_url(key)
        if not u:
            continue
        try:
            rows = sheets.parse_coding_rows(sheets.fetch_csv(u), platform)
            idx["problems"][platform] = [asdict(r) for r in rows]
        except Exception as e:
            log.warning("코딩 시트 %s 읽기 실패: %s", key, type(e).__name__)
    cid, n = channel_id("coding"), 0
    if cid:
        notices, last = slack_history.collect_notices(slack_client(), cid, _oldest("coding", 365))
        seen = {(x["platform"], x["problem_id"], x["sent_date"]) for x in idx["notices"]}
        for nt in notices:
            d = {**asdict(nt), "sent_date": nt.sent_date.isoformat() if nt.sent_date else ""}
            if (d["platform"], d["problem_id"], d["sent_date"]) not in seen:
                idx["notices"].append(d)
                n += 1
        state.set_slack_last_ts("coding", last)
    # 슬랙이 없을 때를 대비해 시트의 '완료' 행도 알림 후보로 쓰지는 않는다(날짜를 알 수 없음)
    CODING_INDEX.parent.mkdir(parents=True, exist_ok=True)
    CODING_INDEX.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    return f"코딩 문제 {sum(len(v) for v in idx['problems'].values())}건, 알림 {len(idx['notices'])}건(신규 {n})"


# ---------------------------------------------------------------- 진입점
CHANNELS = {"contest": index_contest, "news": index_news, "coding": index_coding}


def refresh_channel(name: str) -> tuple[bool, str]:
    """(성공 여부, 메시지). 실패해도 예외를 밖으로 던지지 않는다."""
    try:
        msg = CHANNELS[name]()
        state.mark_refreshed(name)
        log.info(msg)
        return True, msg
    except Exception as e:
        log.exception("%s 갱신 실패", name)
        return False, f"{name} 갱신 실패: {type(e).__name__}"


def refresh_all(force: bool = False) -> dict[str, tuple[bool, str]]:
    return {n: refresh_channel(n) for n in CHANNELS if force or state.is_stale(n)}


def refresh_if_stale(name: str) -> bool:
    """질문 처리 전에 호출. 갱신이 필요한데 실패했으면 False(답변 끝에 안내문을 붙임)."""
    if not state.is_stale(name):
        return True
    return refresh_channel(name)[0]


def rebuild() -> None:
    reset_all()
    config.STATE_FILE.unlink(missing_ok=True)
    CODING_INDEX.unlink(missing_ok=True)
