"""Chroma 필터(모집 중/마감 임박/신규)가 실제 벡터스토어에서 동작하는지 확인. 임베딩은 결정적 가짜를 쓴다."""
from datetime import date, datetime

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from src.common.text import KST
from src.contest import flow
from src.rag import store
from src.rag.indexer import contest_docs
from src.sources.sheets import ContestRow

TODAY = date(2026, 11, 21)


def row(aid, title, deadline, collected=datetime(2026, 11, 18, 12, 40, tzinfo=KST), src="sheet"):
    return ContestRow(aid, title, f"https://linkareer.com/activity/{aid}", collected, None, deadline, src if deadline else "none")


@pytest.fixture
def seeded(tmp_data, monkeypatch):
    from src import config
    monkeypatch.setattr(config, "CHROMA_DIR", tmp_data / "chroma")
    monkeypatch.setattr(store, "HASH_FILE", tmp_data / "cache" / "index_hash.json")
    monkeypatch.setattr(store, "embeddings", lambda: DeterministicFakeEmbedding(size=32))
    store.get_store.cache_clear()
    rows = [
        row("1", "의료 데이터 해커톤", date(2026, 11, 22)),                       # 내일 마감
        row("2", "AI 서비스 기획 공모전", date(2026, 12, 20)),                    # 모집 중
        row("3", "지난 AI 경진대회", date(2026, 11, 1)),                          # 마감됨
        row("4", "마감일 미상 최근 공고", None),                                  # 확인 필요
        row("5", "마감일 미상 오래된 공고", None, collected=datetime(2026, 3, 1, tzinfo=KST)),  # 45일 초과
    ]
    docs = [d for r in rows for d in contest_docs(r, None)]
    store.upsert_changed("contest", docs)
    yield
    store.get_store.cache_clear()


def test_open_filter_excludes_closed_and_old_unknown(seeded):
    text, last = flow.answer("AI 공모전 알려줘", TODAY)
    ids = {x["id"] for x in last}
    assert {"1", "2", "4"} <= ids and not ({"3", "5"} & ids)
    assert "마감일 확인 필요" in text and "마감됨" not in text


def test_include_closed_when_asked(seeded):
    _, last = flow.answer("마감된 공모전 보여줘", TODAY)
    assert "3" in {x["id"] for x in last}


def test_deadline_soon_window(seeded):
    text, last = flow.answer("이번 주에 마감되는 공모전 알려줘", TODAY)     # 11/21 ~ 11/22
    assert [x["id"] for x in last] == ["1"] and "D-1" in text


def test_new_in_last_week_and_followup_detail(seeded):
    _, last = flow.answer("이번 주에 새로 올라온 공모전은?", TODAY)
    assert {x["id"] for x in last} == {"1", "2", "4"}   # 11/18 수집분, 마감된 3번은 기본적으로 제외
    text, _ = flow.answer("의료 데이터 해커톤 시상 내역 알려줘", TODAY)
    assert "의료 데이터 해커톤" in text and "시상" in text or "찾지 못했습니다" in text


def test_plain_section_strips_title_and_label():
    from src.contest.flow import _plain_section
    assert _plain_section("2026 AI 공모전\n시상 내역: 최우수상 300만원\n우수상 50만원") == "최우수상 300만원\n우수상 50만원"
    assert _plain_section("제목만") == "제목만"
