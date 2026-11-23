import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from src.graph import build_graph


@pytest.fixture
def graph(tmp_data):
    return build_graph(MemorySaver())


def cfg(i="t1"):
    return {"configurable": {"thread_id": i}}


def test_unsupported_channel_answers_immediately(graph):
    out = graph.invoke({"question": "#general 공지 알려줘", "today": "2026-11-14"}, cfg())
    assert "지원하지 않습니다" in out["answer"] and "공모전" in out["answer"]


def test_ambiguous_interrupts_then_resumes_with_choice(graph):
    c = cfg("amb")
    out = graph.invoke({"question": "오늘 올라온 거 알려줘", "today": "2026-11-14"}, c)
    assert out["__interrupt__"][0].value["text"].startswith("어느 채널")
    assert graph.get_state(c).next == ("ask",)
    done = graph.invoke(Command(resume="3"), c)      # 코딩테스트 선택 → 문제 목록이 비어 있어 안내 문구
    assert "문제 목록을 아직 읽지 못했습니다" in done["answer"]
    assert done["channel"] == "coding" and not graph.get_state(c).next


def test_bad_reply_asks_again_then_gives_up(graph):
    c = cfg("bad")
    graph.invoke({"question": "오늘 올라온 거 알려줘", "today": "2026-11-14"}, c)
    again = graph.invoke(Command(resume="글쎄"), c)
    assert "번호(1~3)" in again["__interrupt__"][0].value["text"]
    done = graph.invoke(Command(resume="음"), c)
    assert "취소" in done["answer"]


def test_volatile_state_reset_between_requests(graph):
    c = cfg("reset")
    graph.invoke({"question": "#general a", "today": "2026-11-14"}, c)
    out = graph.invoke({"question": "오늘 올라온 거", "today": "2026-11-14"}, c)
    assert "__interrupt__" in out        # 이전 요청의 answer가 남아 있지 않아 새로 되묻는다
