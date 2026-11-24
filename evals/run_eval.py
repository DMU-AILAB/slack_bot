#!/usr/bin/env python
"""봇 품질 평가. 골든셋으로 라우팅·검색·답변·코딩을 채점하고 결과를 JSON으로 남긴다.

  python evals/run_eval.py                       # routing + retrieval (모델 없이 빠름, 1분 이내)
  python evals/run_eval.py --suite answers       # 실제 답변(LLM 사용)
  python evals/run_eval.py --suite all --model gemma3:4b
  python evals/run_eval.py --suite coding --coding-n 3
  python evals/run_eval.py --compare evals/results/a.json evals/results/b.json

기본은 LangSmith 추적을 끄고(평가 호출이 운영 추적에 섞이지 않게) 지정한 --data-dir 의 인덱스를 읽기만 한다.
"""
import argparse
import json
import os
import random
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
GOLDEN = ROOT / "evals" / "golden"
RESULTS = ROOT / "evals" / "results"


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", default="fast", choices=["fast", "routing", "retrieval", "answers", "coding", "all"],
                    help="fast = routing+retrieval (기본)")
    ap.add_argument("--model", help="생성 모델 (GEN_MODEL 덮어쓰기). 예: gemma3:4b")
    ap.add_argument("--data-dir", default=os.environ.get("BOT_DATA_DIR") or "data-test",
                    help="읽을 인덱스 폴더 (기본 data-test; 운영 데이터는 data)")
    ap.add_argument("--trace", action="store_true", help="LangSmith로 추적 전송 (프로젝트 ailab-slack-bot-eval)")
    ap.add_argument("--coding-n", type=int, default=3, help="코딩 평가 문제 수")
    ap.add_argument("--only", help="answers 스위트에서 id 접두어로 일부만 실행 (예: c0, n)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--n-retrieval", type=int, default=40, help="검색 평가 표본 수")
    ap.add_argument("--out", help="결과 JSON 경로 (기본 evals/results/<모델>_<시각>.json)")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"), help="결과 두 개를 비교해 표로 출력")
    return ap.parse_args()


# ---------------------------------------------------------------- 보고
def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def flat_metrics(res: dict) -> dict[str, float]:
    out = {}
    for suite, body in res.get("suites", {}).items():
        for k, v in body.get("metrics", {}).items():
            out[f"{suite}.{k}"] = v
    return out


def compare(a_path: str, b_path: str) -> None:
    a, b = (json.loads(Path(p).read_text(encoding="utf-8")) for p in (a_path, b_path))
    ma, mb = flat_metrics(a), flat_metrics(b)
    print(f"{'지표':<34}{a['meta']['model']:>16}{b['meta']['model']:>16}{'차이':>10}")
    for k in sorted(set(ma) | set(mb)):
        va, vb = ma.get(k), mb.get(k)
        diff = f"{vb - va:+.1f}" if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else ""
        print(f"{k:<34}{str(va):>16}{str(vb):>16}{diff:>10}")


# ---------------------------------------------------------------- routing
def suite_routing(today) -> dict:
    from evals import metrics as M
    from src import router
    from src.contest.query import analyze

    items, rows, fails = load_jsonl(GOLDEN / "routing.jsonl"), [], []
    for it in items:
        p = router.parse(it["q"])
        got = M.route_of(p)
        intent = analyze(p.question, today).intent if got == "contest" else None
        s = M.score_route(it, got, intent)
        rows.append(s)
        if not s["ok"] or s["intent_ok"] is False:
            fails.append({"q": it["q"], "want": it["channel"], "got": got, "want_intent": it.get("intent"),
                          "got_intent": intent, "note": it.get("note", "")})
    n = len(rows)
    with_intent = [r for r in rows if r["intent_ok"] is not None]
    return {
        "metrics": {
            "n": n,
            "channel_ok_pct": M.pct(sum(r["ok"] for r in rows), n),
            "exact_pct": M.pct(sum(r["exact"] for r in rows), n),
            "misroute_pct": M.pct(sum(r["misroute"] for r in rows), n),
            "intent_ok_pct": M.pct(sum(r["intent_ok"] for r in with_intent), len(with_intent)),
        },
        "failures": fails,
    }


# ---------------------------------------------------------------- retrieval
def suite_retrieval(args) -> dict:
    from evals import metrics as M
    from src.contest.query import find_title
    from src.rag.store import get_store

    rnd = random.Random(args.seed)
    metrics, fails = {}, []

    # (a) 공모전: 제목을 대충 기억하고 묻는 경우
    cs = get_store("contest")
    got = cs.get(where={"section": "overview"}, include=["metadatas"])
    metas = got.get("metadatas") or []
    if metas:
        titles = {m["activity_id"]: m["title"] for m in metas}
        sample = rnd.sample(metas, min(args.n_retrieval, len(metas)))
        t_ok = s_ok = used = 0
        for m in sample:
            short = M.shorten_title(m["title"])
            if len(short.split()) < 2:
                continue
            used += 1
            got_id = find_title(f"{short} 시상 내역 알려줘", titles)
            if got_id == m["activity_id"]:
                t_ok += 1
            else:
                fails.append({"kind": "contest_title_lookup", "title": m["title"], "query": short,
                              "got": titles.get(got_id) if got_id else None})
            res = cs.similarity_search_with_score(f"{short} 공모전", k=5, filter={"section": "overview"})
            if m["activity_id"] in {d.metadata["activity_id"] for d, _ in res}:
                s_ok += 1
            else:
                fails.append({"kind": "contest_semantic", "title": m["title"], "query": f"{short} 공모전"})
        metrics.update({"contest_n": used, "contest_title_lookup_pct": M.pct(t_ok, used),
                        "contest_recall@5_pct": M.pct(s_ok, used)})
    else:
        metrics["contest_n"] = 0

    # (b) 소식: 제목 앞부분만으로 해당 기사를 찾는가
    ns = get_store("news")
    nm = (ns.get(include=["metadatas"]).get("metadatas")) or []
    if nm:
        sample = rnd.sample(nm, min(args.n_retrieval, len(nm)))
        hit = used = 0
        for m in sample:
            toks = re.findall(r"[0-9A-Za-z가-힣]+", m["title"])
            if len(toks) < 4:
                continue
            q = " ".join(toks[: max(3, int(len(toks) * 0.6))])
            used += 1
            res = ns.similarity_search_with_score(q, k=6)
            if m["url"] in {d.metadata["url"] for d, _ in res}:
                hit += 1
            else:
                fails.append({"kind": "news", "title": m["title"], "query": q})
        metrics.update({"news_n": used, "news_recall@6_pct": M.pct(hit, used)})
    else:
        metrics["news_n"] = 0
    return {"metrics": metrics, "failures": fails[:30]}


# ---------------------------------------------------------------- answers / coding (그래프 실행)
def _graph():
    from langgraph.checkpoint.memory import MemorySaver
    from src import graph as G
    from src.rag import indexer
    # 평가는 슬랙에 접속하거나 인덱스를 갱신하지 않는다 (재현성 + 운영 채널 보호)
    indexer.refresh_if_stale = lambda name: True
    G.indexer.refresh_if_stale = indexer.refresh_if_stale
    return G.build_graph(MemorySaver())


def _run_graph(graph, question: str, today) -> tuple[str, float, dict]:
    cfg = {"configurable": {"thread_id": f"eval:{uuid.uuid4().hex[:8]}"}}
    t0 = time.monotonic()
    out = graph.invoke({"question": question, "user_hash": "eval", "today": today.isoformat()}, cfg)
    dt = time.monotonic() - t0
    if "__interrupt__" in out:   # 되묻기로 멈춤
        return "[되묻기] " + out["__interrupt__"][0].value["text"], dt, {}
    st = graph.get_state(cfg).values
    return st.get("answer") or "", dt, st


GENERATIONS: list[dict] = []


def _capture_generations() -> None:
    """llm.generate 호출의 (입력 자료, 출력)을 기록한다. 운영 코드는 건드리지 않는다."""
    from src import llm
    if getattr(llm.generate, "_eval_wrapped", False):
        return
    orig = llm.generate

    def wrapped(prompt, **kw):
        out = orig(prompt, **kw)
        GENERATIONS.append({"run": kw.get("run_name", "llm"), "prompt": prompt, "output": out})
        return out
    wrapped._eval_wrapped = True
    llm.generate = wrapped


def _known_urls() -> set[str]:
    from src.rag.store import get_store
    urls: set[str] = set()
    for name in ("contest", "news"):
        for m in get_store(name).get(include=["metadatas"]).get("metadatas") or []:
            if m.get("url"):
                urls.add(m["url"])
    return urls


def _dynamic_item(it: dict, today) -> dict | None:
    """시트에서 조건에 맞는 공모전을 골라 질문을 만든다."""
    from src.common.text import date_int
    from src.rag.store import get_store
    section = {"시상 내역": "prize", "참가 자격": "eligibility"}[it["aspect"]]
    st = get_store("contest")
    got = st.get(where={"section": section}, include=["metadatas", "documents"])
    open_ = [(len(d), m["activity_id"]) for m, d in zip(got.get("metadatas") or [], got.get("documents") or [])
             if m.get("has_deadline") and m.get("deadline_ts", 0) >= date_int(today)]
    if not open_:
        return None
    ids = [max(open_)[1]]            # 항목 설명이 가장 긴 공고: 모델 요약 경로를 실제로 쓰게 한다
    meta = st.get(where={"$and": [{"activity_id": ids[0]}, {"section": "overview"}]}, include=["metadatas"])["metadatas"][0]
    return {**it, "q": f"{meta['title']} {it['aspect']} 알려줘", "expect_links": [meta["url"]],
            "not_contains": ["자료에서 찾지 못했습니다", "확인해 주세요"]}


def suite_answers(args, today) -> dict:
    from evals import metrics as M
    _capture_generations()
    known, graph = _known_urls(), _graph()
    rows, fails, all_g = [], [], []
    for raw in load_jsonl(GOLDEN / "answers.jsonl"):
        if args.only and not raw["id"].startswith(args.only):
            continue
        it = _dynamic_item(raw, today) if raw.get("dynamic") else raw
        if it is None:
            fails.append({"id": raw["id"], "skipped": "조건에 맞는 공모전이 없음"})
            continue
        GENERATIONS.clear()
        try:
            ans, dt, _ = _run_graph(graph, it["q"], today)
        except Exception as e:  # 한 문항의 실패가 전체 평가를 멈추지 않게
            ans, dt = f"[예외] {type(e).__name__}", 0.0
        checks = M.check_answer(it, ans, known, today, it.get("expect_links"))
        gs = [{"run": g["run"], **M.grounding(g["output"], M.evidence_of(g["prompt"]))} for g in GENERATIONS]
        if gs:
            checks["numbers_grounded"] = all(g["numbers_ok"] for g in gs)   # 근거에 없는 숫자는 실패
        all_g += gs
        ok = M.passed(checks)
        rows.append({"id": it["id"], "ok": ok, "latency": dt, "checks": checks, "answer": ans[:2500],
                     "grounding": [{k: g[k] for k in ("run", "rate", "ungrounded")} for g in gs]})
        gtxt = f" 근거밖 {max(g['rate'] for g in gs):.0%}" if gs else ""
        print(f"  {'PASS' if ok else 'FAIL'} {it['id']} {dt:5.1f}s{gtxt}  {it['q'][:40]}", flush=True)
        if not ok:
            fails.append({"id": it["id"], "q": it["q"], "failed": [k for k, v in checks.items() if not v],
                          "answer_head": ans[:300]})
    lat = [r["latency"] for r in rows]
    allc = [v for r in rows for v in r["checks"].values()]
    by = lambda k: [r["checks"][k] for r in rows if k in r["checks"]]
    return {
        "metrics": {
            "n": len(rows),
            "pass_pct": M.pct(sum(r["ok"] for r in rows), len(rows)),
            "check_pass_pct": M.pct(sum(allc), len(allc)),
            "links_known_pct": M.pct(sum(by("links_known")), len(by("links_known"))) if by("links_known") else None,
            "open_only_pct": M.pct(sum(by("open_only")), len(by("open_only"))) if by("open_only") else None,
            "latency_p50_s": M.percentile(lat, 0.5), "latency_p90_s": M.percentile(lat, 0.9),
            "llm_calls": len(all_g),
            "grounded_pct": M.pct(sum(1 - g["rate"] for g in all_g), len(all_g)) if all_g else None,
            "ungrounded_gt30_pct": M.pct(sum(g["rate"] > 0.3 for g in all_g), len(all_g)) if all_g else None,
            "numbers_grounded_pct": M.pct(sum(g["numbers_ok"] for g in all_g), len(all_g)) if all_g else None,
        },
        "failures": fails,
        "rows": rows,
    }


def suite_coding(args, today) -> dict:
    from evals import metrics as M
    from src.rag import indexer
    probs = [p for p in indexer.load_coding_index()["problems"]["programmers"] if p.get("problem_id")]
    probs.sort(key=lambda p: (-p.get("rate", 0), p["problem_id"]))      # 정답률 높은(쉬운) 문제부터
    graph, rows, picked = _graph(), [], []
    from src.coding import problems as P
    for p in probs:                                                      # SQL·읽기 실패 문제는 건너뛴다
        if len(picked) >= args.coding_n:
            break
        pr = P.load_problem("programmers", p["problem_id"], p.get("title", ""), p["url"])
        if pr.kind == "function" and not pr.error and pr.examples:
            picked.append(p)
    for p in picked:
        q = f"프로그래머스 {p['problem_id']}번 풀어줘"
        try:
            ans, dt, st = _run_graph(graph, q, today)
        except Exception as e:
            ans, dt, st = f"[예외] {type(e).__name__}", 0.0, {}
        v = st.get("verified")
        rows.append({"id": p["problem_id"], "title": p.get("title", ""), "verified": v, "attempts": st.get("attempt", 0),
                     "latency": dt, "last_failure": (st.get("last_failure") or "")[:300],
                     "stderr": [r.get("stderr", "")[:200] for r in (st.get("results") or []) if r.get("stderr")][:2],
                     "code": (st.get("code") or "")[:500]})
        print(f"  {v or '-':>5} {p['problem_id']} 시도 {st.get('attempt', 0)} {dt:5.0f}s  {p.get('title', '')[:30]}", flush=True)
    n = len(rows)
    lat = [r["latency"] for r in rows]
    return {
        "metrics": {
            "n": n,
            "verified_pass_pct": M.pct(sum(r["verified"] == "pass" for r in rows), n),
            "first_try_pass_pct": M.pct(sum(r["verified"] == "pass" and r["attempts"] == 1 for r in rows), n),
            "latency_p50_s": M.percentile(lat, 0.5), "latency_p90_s": M.percentile(lat, 0.9),
        },
        "failures": [r for r in rows if r["verified"] != "pass"],
    }


# ---------------------------------------------------------------- main
def main() -> int:
    args = parse_args()
    if args.compare:
        compare(*args.compare)
        return 0

    # config import 전에 환경을 정한다 (dotenv는 이미 있는 값을 덮어쓰지 않는다)
    if args.model:
        os.environ["GEN_MODEL"] = args.model
    os.environ["BOT_DATA_DIR"] = args.data_dir
    if args.trace:
        os.environ["LANGSMITH_PROJECT"] = "ailab-slack-bot-eval"
    else:
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "false"

    from src import config
    from src.common.text import kst_today
    today = kst_today()
    suites = {"fast": ["routing", "retrieval"], "all": ["routing", "retrieval", "answers", "coding"]}.get(args.suite, [args.suite])

    print(f"평가 시작: 모델={config.GEN_MODEL} 임베딩={config.EMBED_MODEL} 데이터={config.DATA_DIR.name} 기준일={today}")
    result = {"meta": {"model": config.GEN_MODEL, "embed": config.EMBED_MODEL, "data": config.DATA_DIR.name,
                       "today": today.isoformat(), "ts": datetime.now().isoformat(timespec="seconds")}, "suites": {}}
    for name in suites:
        print(f"\n[{name}]", flush=True)
        t0 = time.time()
        try:
            if name == "routing":
                body = suite_routing(today)
            elif name == "retrieval":
                body = suite_retrieval(args)
            elif name == "answers":
                body = suite_answers(args, today)
            else:
                body = suite_coding(args, today)
        except Exception as e:
            body = {"metrics": {}, "failures": [], "error": f"{type(e).__name__}: {e}"[:200]}
        body["seconds"] = round(time.time() - t0, 1)
        result["suites"][name] = body
        for k, v in body["metrics"].items():
            print(f"  {k:<28}{v}")
        if body.get("error"):
            print("  오류:", body["error"])
        for f in body["failures"][:12]:
            print("  ✗", json.dumps(f, ensure_ascii=False)[:230])

    RESULTS.mkdir(parents=True, exist_ok=True)
    out = Path(args.out) if args.out else RESULTS / f"{config.GEN_MODEL.replace(':', '-')}_{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n결과 저장: {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
