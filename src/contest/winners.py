"""수상작 분석 (상세구현명세서 8.1.1): 검색 → 읽기 → 추출(map) → 근거 검증 → 종합(reduce).

각 단계는 상태 dict를 받아 갱신분을 돌려주므로 LangGraph 서브그래프 노드로 그대로 쓴다.
"""
import logging
import re
from urllib.parse import urlsplit

from src import config, llm
from src.common.text import escape_slack, norm_text, norm_url
from src.contest.query import clean_topic
from src.sources import search as search_mod
from src.sources import web

log = logging.getLogger(__name__)
AWARD_WORDS = re.compile(r"수상|대상|최우수|우수상|입상|선정|장려|금상|은상|동상|1등|2등|3등|우승")
BAD_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".zip", ".hwp", ".pptx", ".xlsx")
UNAVAILABLE_MSG = "웹 검색을 쓸 수 없어 수상작 분석을 하지 못했습니다."
DISCLAIMER = "_웹 검색 결과를 정리한 것이라 정확하지 않을 수 있습니다. 공식 결과는 링크에서 확인하세요._"


# ---------------------------------------------------------------- 단계
def topic_of(question: str) -> str:
    t = clean_topic(question)
    t = re.sub(r"수상|대상|입상|우수|특징|분석|지난|공통", " ", t)
    return norm_text(t) or "AI"


def step_make_queries(s: dict) -> dict:
    t = topic_of(s["question"])
    qs = [f"{t} 공모전 수상작", f"{t} 공모전 대상 수상 후기", f"{t} 공모전 결과 발표 수상자"]
    return {"topic": t, "queries": qs[: config.SEARCH_MAX_QUERIES], "search_round": 0, "results": [], "unavailable": False}


def step_search(s: dict) -> dict:
    rnd = s.get("search_round", 0)
    qs = s["queries"][0:2] if rnd == 0 else s["queries"][2:3]
    found, seen = list(s.get("results", [])), {r["url"] for r in s.get("results", [])}
    try:
        for q in qs:
            for r in search_mod.search(q, config.SEARCH_TOP_K):
                u = norm_url(r.url)
                if u and u not in seen:
                    seen.add(u)
                    found.append({"title": r.title, "url": u, "snippet": r.snippet})
    except search_mod.SearchUnavailable as e:
        log.warning("웹 검색 불가: %s", e)
        return {"unavailable": True, "results": found, "search_round": rnd + 1}
    return {"results": found, "search_round": rnd + 1}


def step_select_pages(s: dict) -> dict:
    def score(r):
        return -(bool(AWARD_WORDS.search(r["title"])) * 2 + bool(AWARD_WORDS.search(r["snippet"])))
    per_domain, picked = {}, []
    for r in sorted(s["results"], key=score):
        host = urlsplit(r["url"]).netloc
        if r["url"].lower().endswith(BAD_EXT) or per_domain.get(host, 0) >= 2 or r["url"] in {p["url"] for p in s.get("pages", [])}:
            continue
        per_domain[host] = per_domain.get(host, 0) + 1
        picked.append(r)
    taken = len(s.get("pages", []))
    return {"to_read": picked[: max(0, config.WINNERS_MAX_PAGES - taken)]}


def _award_focus(text: str, limit: int = 1500) -> str:
    """수상 관련 줄과 앞뒤 한 줄을 앞쪽에 모아 입력 길이를 줄인다."""
    lines = text.splitlines()
    keep = []
    for i, l in enumerate(lines):
        if AWARD_WORDS.search(l):
            keep += [x for x in lines[max(0, i - 1): i + 2] if x not in keep]
    focus = "\n".join(keep) if keep else text
    return focus[:limit]


def step_read_pages(s: dict) -> dict:
    pages = list(s.get("pages", []))
    for r in s.get("to_read", []):
        html_str = web.fetch_html(r["url"])
        text = web.html_to_text(html_str) if html_str else ""
        body = text if len(text) > 200 else f"{r['title']}\n{r['snippet']}"
        pages.append({"url": r["url"], "title": r["title"], "text": body, "focus": _award_focus(body)})
    return {"pages": pages, "to_read": []}


_FEWSHOT = (
    "예시 자료: 제3회 농업 공모전에서 대상은 한빛팀의 '스마트 온실 제어'가 받았다. 이 서비스는 센서 데이터로 온실 환경을 자동 제어한다. "
    "우수상은 푸른팀의 '병해충 사진 진단'이 받았다.\n"
    '예시 출력: {"entries":[{"award":"대상","work":"스마트 온실 제어","summary":"센서 데이터로 온실 환경을 자동 제어하는 서비스",'
    '"tech":"센서 데이터","evidence":"대상은 한빛팀의 \'스마트 온실 제어\'가 받았다"},'
    '{"award":"우수상","work":"병해충 사진 진단","summary":"","tech":null,"evidence":"우수상은 푸른팀의 \'병해충 사진 진단\'이 받았다"}]}\n'
)


def _extract_prompt(p: dict) -> str:
    return ("아래 <자료>에 적힌 수상작을 JSON으로만 출력해라. 예시와 같은 형식을 쓰되 예시 내용은 쓰지 마라.\n" + _FEWSHOT +
            "규칙: 자료에 적힌 것만 쓴다. 모르는 값은 null. 수상 정보가 없으면 {\"entries\":[]}. "
            "evidence는 자료의 문장을 한 글자도 바꾸지 말고 40자 이내로 옮겨라.\n\n"
            "<자료>\n" + p["title"] + "\n" + p["focus"] + "\n</자료>\n출력:")


_AWARD = r"(대상|최우수상|최우수|우수상|우수|장려상|장려|금상|은상|동상|입상|1등|2등|3등|우승)"
_PATTERN = re.compile(_AWARD + r"[^'‘“\"「『.\n]{0,30}?의\s*[‘'“\"「『](.{2,40}?)[’'”\"」』]")


def regex_entries(text: str) -> list[dict]:
    """'대상은 팀 X의 \"작품\"' 같은 문장에서 수상 항목을 뽑는다. evidence는 일치한 원문이므로 환각이 없다."""
    out = []
    for m in _PATTERN.finditer(text):
        start = max(0, m.start())
        out.append({"award": m[1], "work": m[2].strip(), "summary": "", "tech": None, "evidence": text[start:m.end()][:80]})
    return out


def _squash(x: str) -> str:
    return re.sub(r"\s+", "", x or "")


def verify_entries(entries: list[dict], text: str) -> list[dict]:
    """evidence가 본문에 실제로 들어 있는 항목만 남긴다(환각 방어)."""
    body = _squash(text)
    ok = []
    for e in entries:
        ev = _squash(str(e.get("evidence") or ""))
        if len(ev) >= 8 and ev in body and str(e.get("work") or "").strip():
            ok.append(e)
    return ok


def step_extract(s: dict) -> dict:
    entries = [dict(e) for e in s.get("entries", [])]
    extracted = list(s.get("extracted_urls", []))
    for p in s.get("pages", []):
        if p["url"] in extracted:
            continue
        extracted.append(p["url"])
        data = llm.generate_json(_extract_prompt(p), run_name="winners-extract", num_predict=400)
        raw = (data or {}).get("entries") if isinstance(data, dict) else None
        found = verify_entries([x for x in (raw or []) if isinstance(x, dict)], p["text"])
        found += verify_entries(regex_entries(p["text"]), p["text"])   # 모델 결과 + 문장 패턴 보조 추출(합집합)
        for e in found:
            key = _squash(str(e["work"])).lower()
            hit = next((x for x in entries if _squash(x["work"]).lower() == key), None)
            if hit:   # 같은 수상작이 여러 출처에 나오면 합치고 출처를 모두 기록한다
                hit["urls"] = sorted(set(hit["urls"]) | {p["url"]})
                hit["summary"] = hit["summary"] or str(e.get("summary") or "")
                continue
            entries.append({"award": str(e.get("award") or ""), "work": str(e["work"]).strip(), "summary": str(e.get("summary") or ""),
                            "tech": str(e.get("tech") or "") if e.get("tech") not in (None, "null") else "",
                            "evidence": str(e["evidence"]), "url": p["url"], "urls": [p["url"]], "title": p["title"]})
    return {"entries": entries, "extracted_urls": extracted}


def _urls(e: dict) -> list[str]:
    return e.get("urls") or [e["url"]]


def enough(s: dict) -> bool:
    es = s.get("entries", [])
    return len(es) >= config.WINNERS_MIN_ENTRIES and len({u for e in es for u in _urls(e)}) >= config.WINNERS_MIN_SOURCES


def can_research(s: dict) -> bool:
    return not s.get("unavailable") and s.get("search_round", 0) < 2 and len(s["queries"]) >= 3


def step_rewrite(s: dict) -> dict:
    return {}  # 재검색 질의는 make_queries가 만든 3번째 질의를 쓴다(step_search의 search_round 분기)


def _synth_prompt(entries: list[dict]) -> str:
    lines = [f"[{i}] {e['award']} {e['work']} — {e['summary']}" + (f" (기술: {e['tech']})" if e["tech"] else "")
             for i, e in enumerate(entries, 1)]
    return ("<자료>\n" + "\n".join(lines) + "\n</자료>\n위 수상작들의 공통 특징을 3~5개 써라. 각 특징 끝에 근거가 된 번호를 [1][3] 형태로 붙여라.\n"
            "자료에 없는 평가, 일반론, 심사 기준 추측은 쓰지 마라. 근거가 둘 미만인 것은 특징으로 쓰지 마라.")


def parse_features(text: str, n: int) -> list[tuple[str, list[int]]]:
    """특징 줄과 근거 번호. 유효한 번호가 둘 미만인 줄은 버린다. 사례 수는 코드가 센다."""
    out = []
    for line in text.splitlines():
        refs = sorted({int(x) for x in re.findall(r"\[(\d+)\]", line) if 1 <= int(x) <= n})
        body = re.sub(r"\[\d+\]", "", line).strip(" -•*·\t")
        body = re.sub(r"^\d+[.)]\s*", "", body)
        if len(refs) >= 2 and len(body) >= 6:
            out.append((body, refs))
    return out[:5]


def step_synthesize(s: dict) -> dict:
    es = s["entries"][:12]
    text = llm.generate(_synth_prompt(es), run_name="winners-synthesize", num_predict=450)
    return {"features": [(b, r) for b, r in parse_features(text, len(es))], "entries": s["entries"]}


def compose(s: dict) -> str:
    topic = s.get("topic", "AI")
    if s.get("unavailable") and not s.get("entries"):
        return UNAVAILABLE_MSG
    pages = s.get("pages", [])
    head = f"*{escape_slack(topic)} 공모전 수상작 분석*  (웹 검색 {len(pages)}개 페이지 기준)"
    if not enough(s):
        links = "\n".join(f"• <{p['url']}|{escape_slack(p['title'])[:50]}>" for p in pages[:5])
        return (f"{head}\n\n수상작 자료를 충분히 찾지 못했습니다. 근거 문장을 확인한 수상 항목이 "
                f"{len(s.get('entries', []))}건뿐이라 분석하지 않았습니다." + (f"\n\n*읽은 페이지*\n{links}" if links else "") + f"\n{DISCLAIMER}")
    es = s["entries"][:12]
    lst = "\n".join(f"{i}. {e['award'] or '수상'} — *{escape_slack(e['work'])}*: {e['summary'] or '요약 없음'}  " + " ".join(f"<{u}|출처{k}>" if len(_urls(e)) > 1 else f"<{u}|출처>" for k, u in enumerate(_urls(e)[:3], 1))
                    for i, e in enumerate(es[:8], 1))
    feats = s.get("features", [])
    if feats:
        ftxt = "\n".join(f"• {b}  (사례 {len(r)}/{len(es)}건: " + "".join(f"[{x}]" for x in r) + ")" for b, r in feats)
    else:
        ftxt = "공통 특징을 뽑을 만큼 근거가 겹치지 않았습니다."
    return f"{head}\n\n*수상작*\n{lst}\n\n*공통 특징*\n{ftxt}\n\n{DISCLAIMER}"


# ---------------------------------------------------------------- 그래프 없이 실행(테스트·CLI)
def run_all(question: str) -> dict:
    s = {"question": question}
    s.update(step_make_queries(s))
    while True:
        s.update(step_search(s))
        if s.get("unavailable"):
            break
        s.update(step_select_pages(s))
        s.update(step_read_pages(s))
        s.update(step_extract(s))
        if enough(s) or not can_research(s):
            break
    if enough(s):
        s.update(step_synthesize(s))
    s["answer"] = compose(s)
    return s
