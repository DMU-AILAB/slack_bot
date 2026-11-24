"""공모전 검색과 답변 조립 (상세구현명세서 8.1). 목록과 링크는 코드가 조립하고 LLM은 상세 항목 요약에만 쓴다."""
import logging
import re
from datetime import date, timedelta

from src import config, llm
from src.common.text import date_int, escape_slack, kst_today, norm_text
from src.contest.query import ContestQuery, analyze, find_title
from src.rag import state
from src.rag.store import get_store
from src.sources import web

log = logging.getLogger(__name__)
SHORT_SECTION_CHARS = 120      # 이보다 짧은 항목은 모델 요약 없이 원문을 보여 준다
LOW_RELEVANCE_DISTANCE = 0.55  # [측정] 코사인 거리. 이보다 멀면 "정확히 맞는 공고 없음"으로 안내


def open_filter(today: date) -> dict:
    """모집 중: 마감일이 있고 오늘 이후, 또는 마감일 미상이지만 최근 수집된 공고."""
    cutoff = date_int(today - timedelta(days=config.ENRICH_RECENT_DAYS))
    return {"$or": [
        {"$and": [{"has_deadline": True}, {"deadline_ts": {"$gte": date_int(today)}}]},
        {"$and": [{"has_deadline": False}, {"collected_ts": {"$gte": cutoff}}]},
    ]}


def _all_titles() -> dict[str, str]:
    got = get_store("contest").get(where={"section": "overview"}, include=["metadatas"])
    return {m["activity_id"]: m["title"] for m in got.get("metadatas", [])}


def _int_to_date(n: int) -> date | None:
    try:
        return date(n // 10000, n // 100 % 100, n % 100) if n else None
    except ValueError:
        return None


def _one_line(s: str, n: int) -> str:
    s = norm_text(s.replace("\n", " "))
    return s if len(s) <= n else s[:n - 1] + "…"


def _plain_section(doc: str) -> str:
    """'제목\n시상 내역: ...' 형태의 청크에서 제목 줄과 항목 이름을 떼어 본문만 남긴다."""
    lines = [l for l in doc.splitlines() if l.strip()]
    body = "\n".join(lines[1:]) if len(lines) > 1 else (lines[0] if lines else "")
    return re.sub(r"^[^:：\n]{2,10}[:：]\s*", "", body, count=1).strip()


def _item(meta: dict, today: date) -> dict:
    d = web.cache_get("contests", meta["activity_id"]) or {}
    sec = d.get("sections") or {}
    deadline = _int_to_date(meta.get("deadline_ts", 0)) if meta.get("has_deadline") else None
    return {
        "id": meta["activity_id"], "title": meta["title"], "url": meta["url"], "deadline": deadline,
        "start": _int_to_date(meta.get("start_ts", 0)), "host": meta.get("host") or d.get("host", ""),
        "eligibility": sec.get("eligibility", ""), "prize": sec.get("prize", ""),
        "collected_ts": meta.get("collected_ts", 0),
    }


def render_item(it: dict, today: date) -> str:
    if it["deadline"]:
        n = (it["deadline"] - today).days
        head = f"*{escape_slack(it['title'])}*  ·  마감 {it['deadline']} ({'D-day' if n == 0 else f'D-{n}' if n > 0 else '마감됨'})"
    else:
        head = f"*{escape_slack(it['title'])}*  ·  마감일 확인 필요"
    bits = []
    if it["host"]:
        bits.append(f"주최 {it['host']}")
    if it["start"] or it["deadline"]:
        bits.append(f"접수 {it['start'] or '?'}~{it['deadline'] or '?'}")
    if it["eligibility"]:
        bits.append(f"대상 {_one_line(it['eligibility'], 60)}")
    if it["prize"]:
        bits.append(f"시상 {_one_line(it['prize'], 60)}")
    lines = [head]
    if bits:
        lines.append(" · ".join(bits))
    lines.append(f"<{it['url']}|링커리어 상세>")
    return "\n".join(lines)


def _footer(n_docs_hint: str = "") -> str:
    t = state.last_refresh("contest")
    return f"_근거: 동아리 공모전 시트{n_docs_hint} · 마지막 갱신 {t.strftime('%m/%d %H:%M') if t else '확인 불가'}_"


def _unique_by_activity(results: list[tuple], limit: int) -> list[tuple[dict, float]]:
    seen, out = set(), []
    for doc, dist in results:
        m = doc.metadata
        if m["activity_id"] in seen:
            continue
        seen.add(m["activity_id"])
        out.append((m, dist))
        if len(out) >= limit:
            break
    return out


def _compose_list(items: list[dict], today: date, header: str, empty_msg: str, note: str = "",
                  by_deadline: bool = True) -> str:
    """by_deadline=False(검색)이면 관련도 순서를 유지하고, 마감일 미상 공고만 따로 묶는다."""
    known = [i for i in items if i["deadline"]]
    if by_deadline:
        known.sort(key=lambda i: i["deadline"])
    unknown = [i for i in items if not i["deadline"]]
    if not items:
        return f"{empty_msg}\n{_footer()}"
    parts = [header]
    if note:
        parts.append(note)
    parts += [render_item(i, today) for i in known]
    if unknown:
        parts.append("*마감일 확인 필요*  (모집 중인지 단정할 수 없습니다)")
        parts += [render_item(i, today) for i in unknown]
    parts.append(_footer())
    return "\n\n".join(parts)


def answer(question: str, today: date | None = None) -> tuple[str, list[dict]]:
    """(슬랙 답변, 이번에 보여 준 공고 목록[{id,title,url}])  — 목록은 후속 질문 해석에 쓴다."""
    today = today or kst_today()
    store = get_store("contest")
    cq = analyze(question, today)
    titles = _all_titles()

    # 개별 상세: 질문에 공모전 이름이 들어 있을 때
    aid = find_title(question, titles) if (cq.aspect != "any" or cq.intent == "search") else None
    if aid and (cq.aspect != "any" or "알려" in question or "상세" in question):
        return _answer_detail(cq, aid, titles[aid], today)

    if cq.intent == "deadline_soon":
        flt = {"$and": [{"has_deadline": True}, {"deadline_ts": {"$gte": date_int(today)}},
                        {"deadline_ts": {"$lte": date_int(cq.until)}}]}
        if cq.topic:
            res = store.similarity_search_with_score(cq.topic, k=40, filter={"$and": [flt, {"section": "overview"}]})
            metas = [m for m, _ in _unique_by_activity(res, 30)]
        else:
            metas = store.get(where={"$and": [flt, {"section": "overview"}]}, include=["metadatas"])["metadatas"]
        items = [_item(m, today) for m in metas]
        txt = _compose_list(items, today, f"*{today} ~ {cq.until} 마감 공모전*", "해당 기간에 마감되는 공모전을 자료에서 찾지 못했습니다.")
    elif cq.intent == "new":
        cutoff = date_int(today - timedelta(days=cq.window_days))
        flt = {"$and": [{"collected_ts": {"$gte": cutoff}}, {"section": "overview"}]}
        metas = store.get(where=flt, include=["metadatas"])["metadatas"]
        if not cq.include_closed:
            metas = [m for m in metas if not m.get("has_deadline") or m["deadline_ts"] >= date_int(today)]
        items = sorted((_item(m, today) for m in metas), key=lambda i: -i["collected_ts"])[:10]
        txt = _compose_list(items, today, f"*최근 {cq.window_days}일 새로 올라온 공모전*", "최근 새로 올라온 공모전을 자료에서 찾지 못했습니다.")
    else:  # search
        flt = None if cq.include_closed else open_filter(today)
        query = cq.topic or question
        res = store.similarity_search_with_score(query, k=config.TOP_K_CONTEST * 4, filter=flt)
        uniq = _unique_by_activity(res, config.TOP_K_CONTEST)
        items = [_item(m, today) for m, _ in uniq]
        note = ""
        if uniq and uniq[0][1] > LOW_RELEVANCE_DISTANCE:
            note = "정확히 맞는 공고는 없고, 가장 가까운 공고는 아래와 같습니다."
        label = "공모전" if cq.include_closed else "모집 중인 공모전"
        txt = _compose_list(items, today, f"*{label}*  (질문: {_one_line(question, 40)})",
                            "조건에 맞는 모집 중 공모전을 자료에서 찾지 못했습니다.", note, by_deadline=False)
    return txt, [{"id": i["id"], "title": i["title"], "url": i["url"]} for i in items]


def _answer_detail(cq: ContestQuery, aid: str, title: str, today: date) -> tuple[str, list[dict]]:
    store = get_store("contest")
    got = store.get(where={"activity_id": aid}, include=["metadatas", "documents"])
    docs = {m["section"]: d for m, d in zip(got["metadatas"], got["documents"])}
    meta = got["metadatas"][0]
    it = _item(meta, today)
    key = cq.aspect if cq.aspect != "any" else "overview"
    body = docs.get(key) or ""
    head = render_item(it, today)
    if not body or key == "overview" and len(body) < 20:
        txt = f"{head}\n\n요청하신 항목({key})은 자료에서 찾지 못했습니다. 상세 페이지에서 확인해 주세요.\n{_footer()}"
        return txt, [{"id": aid, "title": title, "url": it["url"]}]
    summary = _plain_section(body)
    # 근거가 짧으면 요약할 것이 없다. 소형 모델이 "찾지 못했다"와 "기타로 되어 있다"를 함께 쓰는 모순을 막기 위해 원문 그대로 보여 준다.
    if len(summary) > SHORT_SECTION_CHARS:
        try:
            out = llm.generate(f"<자료>\n{body[:1500]}\n</자료>\n질문: {cq.raw}\n자료에 적힌 내용만 정리해서 3문장 이내로 답해라.",
                               run_name="contest-detail")
            if out and "찾지 못했습니다" not in out:   # 자료가 있는데 '찾지 못했다'고 하면 모순이므로 원문 사용
                summary = out
        except llm.LLMUnavailable:
            raise
        except Exception:
            log.exception("상세 요약 실패, 원문 사용")
    return f"{head}\n\n{summary}\n\n{_footer()}", [{"id": aid, "title": title, "url": it["url"]}]
