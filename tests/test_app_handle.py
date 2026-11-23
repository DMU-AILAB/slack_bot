"""app.handle()을 가짜 슬랙 클라이언트로 검증: 되묻기 → 재개, 지원 외 채널, 만료, Ollama 오류 문구."""
import pytest
from langgraph.checkpoint.memory import MemorySaver

import app
from src import config, llm, slack_io
from src.graph import build_graph


class FakeSlack:
    def __init__(self):
        self.updates, self.posts = [], []

    def chat_update(self, **kw):
        self.updates.append(kw)

    def chat_postMessage(self, **kw):
        self.posts.append(kw)


@pytest.fixture
def env(tmp_data):
    return build_graph(MemorySaver()), FakeSlack()


def run(graph, client, text, thread="100.1"):
    app.handle(graph, client, "D1", "U1", text, "100.2", thread, "100.3")


def test_unsupported_channel_replaces_ack_message(env):
    graph, c = env
    run(graph, c, "#general 공지 알려줘")
    last = c.updates[-1]
    assert last["ts"] == "100.3" and "지원하지 않습니다" in last["text"] and last["unfurl_links"] is False


def test_ambiguous_then_choice_resumes_same_thread(env):
    graph, c = env
    run(graph, c, "오늘 올라온 거 알려줘")
    assert c.updates[-1]["text"].startswith("어느 채널")
    run(graph, c, "3")
    assert "문제 목록을 아직 읽지 못했습니다" in c.updates[-1]["text"]


def test_expired_pending_asks_to_resend(env, monkeypatch):
    graph, c = env
    run(graph, c, "오늘 올라온 거 알려줘")
    monkeypatch.setattr(config, "PENDING_TTL_MIN", -1)
    run(graph, c, "3")
    assert c.updates[-1]["text"] == slack_io.MSG_EXPIRED


def test_ollama_down_message(env, monkeypatch):
    graph, c = env
    from src.graph import contest_flow

    def boom(*a, **k):
        raise llm.LLMUnavailable("ConnectError")
    monkeypatch.setattr(contest_flow, "answer", boom)
    monkeypatch.setattr("src.graph.indexer.refresh_if_stale", lambda n: True)
    run(graph, c, "#공모전 이번 주 마감", thread="200.1")
    assert c.updates[-1]["text"] == slack_io.MSG_OLLAMA_DOWN


def test_unexpected_error_hides_details(env, monkeypatch):
    graph, c = env
    from src.graph import contest_flow
    monkeypatch.setattr(contest_flow, "answer", lambda *a, **k: 1 / 0)
    monkeypatch.setattr("src.graph.indexer.refresh_if_stale", lambda n: True)
    run(graph, c, "#공모전 이번 주 마감", thread="300.1")
    assert c.updates[-1]["text"] == slack_io.MSG_ERROR and "ZeroDivision" not in c.updates[-1]["text"]
