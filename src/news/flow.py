"""인공지능-소식 답변 (상세구현명세서 8.2): 이슈 요약형(군집화)과 주제 검색형."""
import logging
import re
import time
from datetime import date, datetime

import numpy as np
from bs4 import BeautifulSoup

from src import config, llm
from src.common.text import KST, escape_slack, kst_now, kst_today
from src.news import cluster as cl
from src.news.window import NewsQuery, analyze
from src.rag import state
from src.rag.store import get_store
from src.sources import web

log = logging.getLogger(__name__)
TOPIC_MAX_DISTANCE = 0.62


def _fmt_day(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, KST).strftime("%m/%d") if epoch else "?"


def _footer(nq: NewsQuery) -> str:
    """근거 기간과 매체별 마지막 기사일. 수집이 멈춘 매체가 보이도록 한다."""
    metas = get_store("news").get(include=["metadatas"])["metadatas"]
    last: dict[str, int] = {}
    for m in metas:
        s = m.get("source_name", "")
        last[s] = max(last.get(s, 0), int(m.get("published_epoch", 0)))
    t = state.last_refresh("news")
    srcs = " · ".join(f"{s} {_fmt_day(e)}" for s, e in sorted(last.items()))
    return (f"_근거 기간 {nq.since:%m/%d}~{nq.until:%m/%d} · 마지막 갱신 {t.strftime('%m/%d %H:%M') if t else '확인 불가'}"
            f" · 매체별 마지막 기사 {srcs}_")


# ---------------------------------------------------------------- 기사 본문 발췌
def article_excerpt(url: str, limit: int = 600) -> str:
    key = re.sub(r"\W+", "_", url)[-80:]
    hit = web.cache_get("articles", key)
    if hit is not None:
        return hit.get("text", "")
    html_str = web.fetch_html(url)
    text = ""
    if html_str:
        soup = BeautifulSoup(html_str, "html.parser")
        node = soup.select_one("#article-view-content-div") or soup.find("article") or soup
        paras = [p.get_text(" ", strip=True) for p in node.find_all("p")]
        text = " ".join(p for p in paras if len(p) > 30)[:limit]
    web.cache_put("articles", key, {"text": text})
    return text


# ---------------------------------------------------------------- 이슈 요약형
_TITLE_RE = re.compile(r"제목\s*[:：]\s*(.+)")
_SUM_RE = re.compile(r"요약\s*[:：]\s*(.+)", re.S)


def _summarize_cluster(items: list[dict]) -> tuple[str, str]:
    lines = [f"[{i}] {it['title']} ({it['source_name']}, {_fmt_day(it['published_epoch'])}) {it['excerpt']}".strip()
             for i, it in enumerate(items, 1)]
    prompt = ("<자료>\n" + "\n".join(lines) + "\n</자료>\n위 기사들은 같은 주제를 다룬다. 무슨 일이 있었는지 2~3문장으로 요약하고, "
              "주제를 20자 안팎의 제목으로 써라.\n자료에 없는 평가나 전망은 쓰지 마라.\n출력: 제목: ...\n요약: ...")
    fallback_title = items[0]["title"]
    fallback_sum = items[0]["excerpt"] or " / ".join(it["title"] for it in items[:2])
    try:
        out = llm.generate(prompt, run_name="news-cluster-summary", num_predict=300)
    except llm.LLMUnavailable:
        raise
    except Exception:
        log.exception("군집 요약 실패, 대표 기사 제목으로 대체")
        return fallback_title, fallback_sum
    t, s = _TITLE_RE.search(out), _SUM_RE.search(out)
    title = t[1].strip() if t else fallback_title
    summary = s[1].strip() if s else (out.strip() or fallback_sum)
    return title[:60], summary[:500]


def answer_issues(nq: NewsQuery) -> tuple[str, list[dict]]:
    store = get_store("news")
    where = {"$and": [{"published_epoch": {"$gte": int(nq.since.timestamp())}},
                      {"published_epoch": {"$lte": int(nq.until.timestamp())}}, {"ai_related": True}]}
    got = store.get(where=where, include=["embeddings", "metadatas", "documents"])
    metas, emb = got["metadatas"], got["embeddings"]
    if metas is None or len(metas) == 0:
        return f"{nq.label} 기간의 기사를 자료에서 찾지 못했습니다.\n{_footer(nq)}", []
    labels = cl.cluster_embeddings(np.array(emb))
    top = cl.rank_clusters(labels, metas, time.time(), nq.top_n)

    fetched, blocks, shown = 0, [], []
    for rank, c in enumerate(top, 1):
        items = []
        for i in cl.pick_representatives(c, metas):
            m = metas[i]
            excerpt = m.get("summary", "")
            if not excerpt and fetched < config.NEWS_BODY_FETCH_MAX:
                excerpt, fetched = article_excerpt(m["url"]), fetched + 1
            items.append({**m, "excerpt": excerpt[:600]})
        title, summary = _summarize_cluster(items)
        srcs = ", ".join(sorted({it["source_name"] for it in items}))
        links = " · ".join(f"<{it['url']}|{escape_slack(it['title'])[:40]}>" for it in items[:3])
        blocks.append(f"{rank}. *{escape_slack(title)}* — {summary}  (기사 {c.n_articles}건 · {srcs})\n   {links}")
        shown += [{"id": it["url"], "title": it["title"], "url": it["url"]} for it in items[:3]]
    head = f"*{nq.label} 중요한 이슈 {len(top)}가지*  (선정 기준: 기사 수 · 매체 수 · 최신성)"
    return "\n\n".join([head, *blocks, _footer(nq)]), shown


# ---------------------------------------------------------------- 주제 검색형
def _sanitize_links(text: str, allowed: set[str]) -> str:
    """모델이 만든 URL은 제거한다(7.4)."""
    def repl(m):
        return m[0] if m[1] in allowed else ""
    text = re.sub(r"<(https?://[^|>]+)(?:\|[^>]*)?>", repl, text)
    return re.sub(r"https?://\S+", lambda m: m[0] if m[0].rstrip(").,]") in allowed else "", text)


def answer_topic(nq: NewsQuery) -> tuple[str, list[dict]]:
    store = get_store("news")
    flt = {"$and": [{"published_epoch": {"$gte": int(nq.since.timestamp())}},
                    {"published_epoch": {"$lte": int(nq.until.timestamp())}}]}
    res = store.similarity_search_with_score(nq.topic, k=config.TOP_K_NEWS, filter=flt)
    res = [(d, s) for d, s in res if s <= TOPIC_MAX_DISTANCE]
    if not res:
        return f"'{nq.topic}' 관련 기사를 {nq.label} 자료에서 찾지 못했습니다.\n{_footer(nq)}", []
    ev = []
    for i, (d, _) in enumerate(res, 1):
        m = d.metadata
        ev.append({"n": i, "title": m["title"], "url": m["url"], "src": m["source_name"], "date": m.get("date", ""),
                   "text": (m.get("summary") or d.page_content)[:300]})
    prompt = ("<자료>\n" + "\n".join(f"[{e['n']}] {e['title']} ({e['src']}, {e['date']}) {e['text']}" for e in ev) +
              f"\n</자료>\n질문: {nq.raw}\n관련 기사를 3~5개의 항목으로 정리해라. 각 항목 끝에 근거 번호([1])를 붙여라.")
    body = llm.generate(prompt, run_name="news-topic-answer", num_predict=450)
    allowed = {e["url"] for e in ev}
    body = _sanitize_links(body, allowed)
    body = re.sub(r"\[(\d+)\]", lambda m: f"<{ev[int(m[1]) - 1]['url']}|[{m[1]}]>" if 1 <= int(m[1]) <= len(ev) else "", body)
    sources = "\n".join(f"• <{e['url']}|{escape_slack(e['title'])[:60]}> ({e['src']}, {e['date']})" for e in ev)
    txt = f"*'{nq.topic}' 관련 소식* ({nq.label})\n{body}\n\n*출처*\n{sources}\n{_footer(nq)}"
    return txt, [{"id": e["url"], "title": e["title"], "url": e["url"]} for e in ev]


def answer(question: str, today: date | None = None) -> tuple[str, list[dict]]:
    nq = analyze(question, today or kst_today())
    return answer_topic(nq) if nq.kind == "topic" else answer_issues(nq)
