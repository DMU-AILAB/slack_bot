import json
from datetime import date
from pathlib import Path

from evals import metrics as M

GOLD = Path(__file__).resolve().parent.parent / "evals" / "golden"
TODAY = date(2026, 11, 23)
KNOWN = {"https://linkareer.com/activity/1", "https://linkareer.com/activity/2"}


def test_golden_files_are_well_formed():
    routing = [json.loads(l) for l in (GOLD / "routing.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(routing) >= 40
    assert {r["channel"] for r in routing} <= {"contest", "news", "coding", "ask", "unsupported"}
    answers = [json.loads(l) for l in (GOLD / "answers.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    ids = [a["id"] for a in answers]
    assert len(ids) == len(set(ids))
    assert all(("q" in a) or a.get("dynamic") for a in answers)


def test_score_route_variants():
    item = {"channel": "news", "ok_ask": True}
    assert M.score_route(item, "news", None)["exact"]
    s = M.score_route(item, "ask", None)
    assert s["ok"] and not s["exact"] and not s["misroute"]
    s = M.score_route(item, "contest", None)
    assert not s["ok"] and s["misroute"]
    assert M.score_route({"channel": "contest", "intent": "new"}, "contest", "search")["intent_ok"] is False


def test_check_answer_flags_invented_links_and_stale_deadlines():
    ans = ("*A공모전*  ·  마감 2026-11-30 (D-7)\n<https://linkareer.com/activity/1|링커리어 상세>\n"
           "*B공모전*  ·  마감 2026-11-01 (마감됨)\n<https://evil.example/x|링커리어 상세>")
    c = M.check_answer({"min_items": 2, "open_only": True}, ans, KNOWN, TODAY)
    assert c["links_known"] is False and c["open_only"] is False and c["min_items"] is True


def test_check_answer_empty_ok_and_deadline_window():
    empty = "해당 기간에 마감되는 공모전을 자료에서 찾지 못했습니다."
    assert M.passed(M.check_answer({"min_items": 3, "empty_ok": True}, empty, KNOWN, TODAY))
    assert not M.passed(M.check_answer({"min_items": 3}, empty, KNOWN, TODAY))
    ans = "*A*  ·  마감 2026-12-20 (D-27)\n<https://linkareer.com/activity/2|링커리어 상세>"
    assert M.check_answer({"deadline_within_days": 7}, ans, KNOWN, TODAY)["deadline_within"] is False


def test_numbered_limit_and_error_detection():
    ans = "1. a\n2. b\n3. c\n4. d"
    assert M.check_answer({"max_numbered": 3, "empty_ok": True}, ans, KNOWN, TODAY)["max_numbered"] is False
    assert M.check_answer({"empty_ok": True}, "처리 중 오류가 났습니다. 잠시 뒤 다시 시도해 주세요.", KNOWN, TODAY)["no_error"] is False


def test_shorten_title_drops_brackets():
    assert M.shorten_title("[삼성] 2026 AI 해커톤 대회 참가자 모집", 3) == "2026 AI 해커톤"
    assert "삼성" not in M.shorten_title("[삼성] 2026 AI 해커톤 대회")


def test_grounding_numbers_and_invented_entities():
    ev = "이탈리아 배터리 저장용량 12.84GWh 돌파, 엔비디아 젠슨 황의 악수 거래"
    ok = M.grounding("저장용량은 12.84GWh로 늘었다", ev)
    assert ok["numbers_ok"] and "12.84gwh로" not in ok["ungrounded"]
    bad = M.grounding("저장용량이 13.5GWh로 늘었고 일론 머스크가 주장했다", ev)
    assert not bad["numbers_ok"] and any("머스크" in t for t in bad["ungrounded"])
    assert M.grounding("젠슨 황의 악수 거래", ev)["rate"] == 0.0
