"""LangGraph 구성 (상세구현명세서 7.3).

START → parse → (unsupported/ambiguous → ask(interrupt) | channel) → contest | news | coding | winners → format → END

- 되묻기는 interrupt로 일시 정지하고, 같은 thread_id로 resume한다. 상태는 체크포인터에 저장된다.
- 상태에는 비밀값(계정, 쿠키)을 넣지 않는다.
- 필터·군집·링크 조립은 일반 함수가 하고 LLM은 문장 생성에만 쓴다.
"""
import logging
from datetime import date
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from src import router
from src.coding import flow as coding
from src.common.text import kst_today
from src.contest import flow as contest_flow
from src.contest import winners
from src.contest.query import analyze as contest_analyze
from src.followup import resolve as resolve_followup
from src.news import flow as news_flow
from src.rag import indexer, state as rstate

log = logging.getLogger(__name__)


class BotState(TypedDict, total=False):
    # 입력·공통
    question: str
    user_hash: str
    today: str
    channel: str | None
    q: str
    intent: str | None
    candidates: list[str]
    unsupported: str | None
    answer: str | None
    stale: bool
    last_channel: str | None
    last_results: list[dict]
    # 코딩
    hint_only: bool
    target: dict | None
    problem: dict
    attempt: int
    approach: str
    code: str
    results: list[dict]
    verified: str | None
    last_failure: str | None
    hint_text: str
    message: str | None
    # 수상작 분석
    topic: str
    queries: list[str]
    search_round: int
    unavailable: bool
    to_read: list[dict]
    pages: list[dict]
    entries: list[dict]
    extracted_urls: list[str]
    features: list


# 요청마다 초기화할 휘발성 키 (같은 thread_id의 이전 실행 값이 남지 않게)
VOLATILE = {
    "channel": None, "q": "", "intent": None, "candidates": [], "unsupported": None, "answer": None, "stale": False,
    "hint_only": False, "target": None, "problem": {}, "attempt": 0, "approach": "", "code": "", "results": [],
    "verified": None, "last_failure": None, "hint_text": "", "message": None, "topic": "", "queries": [],
    "search_round": 0, "unavailable": False, "to_read": [], "pages": [], "entries": [], "extracted_urls": [], "features": [],
}


def _today(s: BotState) -> date:
    return date.fromisoformat(s["today"]) if s.get("today") else kst_today()


# ---------------------------------------------------------------- 노드
def parse(s: BotState) -> dict:
    out: dict[str, Any] = dict(VOLATILE)
    out["today"] = s.get("today") or kst_today().isoformat()
    fu = resolve_followup(s["question"], s.get("last_channel"), s.get("last_results"))
    if fu:
        out.update(channel=fu[0], q=fu[1])
        return out
    p = router.parse(s["question"])
    out.update(channel=p.channel, q=p.question, candidates=p.candidates, unsupported=p.unsupported)
    if p.unsupported:
        out["answer"] = router.unsupported_text(p.unsupported)
    return out


def ask(s: BotState) -> dict:
    """어느 채널인지 되묻는다. 답이 올 때까지 그래프가 멈춘다(체크포인터)."""
    text = router.ask_text(s.get("candidates", []))
    for _ in range(2):
        reply = interrupt({"text": text})
        ch = router.choice_from_reply(str(reply), s.get("candidates", []))
        if ch:
            return {"channel": ch}
        text = "번호(1~3)나 채널 이름으로 답해 주세요.\n" + router.ask_text(s.get("candidates", []))
    return {"answer": "채널을 정하지 못해 질문을 취소했습니다. 질문을 다시 보내 주세요."}


def contest_prepare(s: BotState) -> dict:
    ok = indexer.refresh_if_stale("contest")
    return {"intent": contest_analyze(s["q"], _today(s)).intent, "stale": not ok}


def contest_answer(s: BotState) -> dict:
    text, last = contest_flow.answer(s["q"], _today(s))
    return {"answer": text, "last_results": last, "last_channel": "contest"}


def news_answer(s: BotState) -> dict:
    ok = indexer.refresh_if_stale("news")
    text, last = news_flow.answer(s["q"], _today(s))
    return {"answer": text, "last_results": last, "last_channel": "news", "stale": not ok, "intent": "news"}


# --- 코딩
def c_resolve(s: BotState) -> dict:
    ok = indexer.refresh_if_stale("coding")
    return {**coding.step_resolve({"question": s["q"], "today": s["today"]}), "stale": not ok, "intent": "coding"}


def c_fetch(s: BotState) -> dict:
    return coding.step_fetch(s)


def c_generate(s: BotState) -> dict:
    return coding.step_generate(s)


def c_run(s: BotState) -> dict:
    return coding.step_run(s)


def c_compose(s: BotState) -> dict:
    t = s.get("target")
    last = [{"id": t["problem_id"], "platform": t["platform"], "title": t["title"], "url": t["url"]}] if t else []
    return {"answer": coding.compose(s), "last_results": last, "last_channel": "coding"}


# --- 수상작 분석
def w_queries(s: BotState) -> dict:
    return winners.step_make_queries({"question": s["q"]})


def w_search(s: BotState) -> dict:
    return winners.step_search(s)


def w_select(s: BotState) -> dict:
    return winners.step_select_pages(s)


def w_read(s: BotState) -> dict:
    return winners.step_read_pages(s)


def w_extract(s: BotState) -> dict:
    return winners.step_extract(s)


def w_synth(s: BotState) -> dict:
    return winners.step_synthesize(s)


def w_compose(s: BotState) -> dict:
    return {"answer": winners.compose(s), "last_channel": "contest", "last_results": [
        {"id": e["url"], "title": e["work"], "url": e["url"]} for e in s.get("entries", [])[:8]]}


def format_answer(s: BotState) -> dict:
    text = s.get("answer") or "답변을 만들지 못했습니다."
    if s.get("stale"):
        t = rstate.last_refresh(s.get("channel") or "")
        text += f"\n_(자료 갱신 실패, 마지막 갱신 {t.strftime('%m/%d %H:%M') if t else '확인 불가'})_"
    return {"answer": text}


# ---------------------------------------------------------------- 분기
def after_parse(s: BotState) -> str:
    if s.get("answer"):
        return "format"
    return s["channel"] if s.get("channel") else "ask"


def after_ask(s: BotState) -> str:
    return "format" if s.get("answer") else s["channel"]


def after_contest_prepare(s: BotState) -> str:
    return "w_queries" if s.get("intent") == "winners" else "contest_answer"


def after_c_resolve(s: BotState) -> str:
    return "c_fetch" if s.get("target") else "c_compose"


def after_c_fetch(s: BotState) -> str:
    return "c_generate" if coding.can_solve(s) else "c_compose"


def after_c_generate(s: BotState) -> str:
    return "c_compose" if s.get("hint_only") else "c_run"


def after_c_run(s: BotState) -> str:
    return "c_generate" if coding.should_retry(s) else "c_compose"


def after_w_search(s: BotState) -> str:
    return "w_compose" if s.get("unavailable") else "w_select"


def after_w_extract(s: BotState) -> str:
    if winners.enough(s):
        return "w_synth"
    return "w_search" if winners.can_research(s) else "w_compose"


# ---------------------------------------------------------------- 조립
def build_graph(checkpointer=None):
    g = StateGraph(BotState)
    for name, fn in [("parse", parse), ("ask", ask), ("contest_prepare", contest_prepare), ("contest_answer", contest_answer),
                     ("news_answer", news_answer), ("c_resolve", c_resolve), ("c_fetch", c_fetch), ("c_generate", c_generate),
                     ("c_run", c_run), ("c_compose", c_compose), ("w_queries", w_queries), ("w_search", w_search),
                     ("w_select", w_select), ("w_read", w_read), ("w_extract", w_extract), ("w_synth", w_synth),
                     ("w_compose", w_compose), ("format", format_answer)]:
        g.add_node(name, fn)
    g.add_edge(START, "parse")
    g.add_conditional_edges("parse", after_parse, {"format": "format", "ask": "ask", "contest": "contest_prepare",
                                                    "news": "news_answer", "coding": "c_resolve"})
    g.add_conditional_edges("ask", after_ask, {"format": "format", "contest": "contest_prepare",
                                                "news": "news_answer", "coding": "c_resolve"})
    g.add_conditional_edges("contest_prepare", after_contest_prepare, {"w_queries": "w_queries", "contest_answer": "contest_answer"})
    g.add_edge("contest_answer", "format")
    g.add_edge("news_answer", "format")
    g.add_conditional_edges("c_resolve", after_c_resolve, {"c_fetch": "c_fetch", "c_compose": "c_compose"})
    g.add_conditional_edges("c_fetch", after_c_fetch, {"c_generate": "c_generate", "c_compose": "c_compose"})
    g.add_conditional_edges("c_generate", after_c_generate, {"c_run": "c_run", "c_compose": "c_compose"})
    g.add_conditional_edges("c_run", after_c_run, {"c_generate": "c_generate", "c_compose": "c_compose"})
    g.add_edge("c_compose", "format")
    g.add_edge("w_queries", "w_search")
    g.add_conditional_edges("w_search", after_w_search, {"w_compose": "w_compose", "w_select": "w_select"})
    g.add_edge("w_select", "w_read")
    g.add_edge("w_read", "w_extract")
    g.add_conditional_edges("w_extract", after_w_extract, {"w_synth": "w_synth", "w_search": "w_search", "w_compose": "w_compose"})
    g.add_edge("w_synth", "w_compose")
    g.add_edge("w_compose", "format")
    g.add_edge("format", END)
    return g.compile(checkpointer=checkpointer)
