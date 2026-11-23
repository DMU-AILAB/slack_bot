"""시드 스크립트와 슬랙 수집기(채널 찾기, 페이지네이션, 파싱)를 가짜 슬랙 클라이언트로 검증."""
import importlib
from datetime import date

import pytest

from scripts import seed_test_channel as seed
from src import config
from src.sources import slack_history as sh


class FakeSlack:
    """conversations_list/history(페이지 2개씩)와 chat_postMessage를 흉내 낸다."""

    def __init__(self, channels=("봇-테스트",), page=3):
        self.channels = {n: f"C{i}" for i, n in enumerate(channels, 1)}
        self.store: dict[str, list[dict]] = {cid: [] for cid in self.channels.values()}
        self.page, self.clock = page, 1_794_000_000

    def conversations_list(self, **kw):
        return {"channels": [{"id": i, "name": n} for n, i in self.channels.items()], "response_metadata": {}}

    def chat_postMessage(self, channel, text, blocks=None, **kw):
        self.clock += 1
        self.store[channel].append({"ts": f"{self.clock}.000100", "text": text, "blocks": blocks or []})

    def conversations_history(self, channel, oldest="0", limit=200, cursor=None):
        msgs = sorted((m for m in self.store[channel] if float(m["ts"]) > float(oldest)), key=lambda m: -float(m["ts"]))
        start = int(cursor or 0)
        chunk = msgs[start:start + self.page]
        more = start + self.page < len(msgs)
        return {"messages": chunk, "has_more": more, "response_metadata": {"next_cursor": str(start + self.page) if more else ""}}


TODAY = date(2026, 11, 21)


def test_refuses_production_channels():
    for name in config.DEFAULT_CHANNEL_NAMES.values():
        with pytest.raises(seed.SeedError):
            seed.seed(FakeSlack(channels=(name,)), name, TODAY)


def test_missing_channel_message():
    with pytest.raises(seed.SeedError, match="초대"):
        seed.seed(FakeSlack(), "없는채널", TODAY)


def test_dry_run_posts_nothing_and_needs_no_client():
    assert "programmers" in seed.seed(None, "봇-테스트", TODAY, dry_run=True)


def test_seed_is_idempotent_and_dates_are_today():
    c = FakeSlack()
    first = seed.seed(c, "봇-테스트", TODAY)
    assert set(first) >= {"programmers", "swea", "aitimes", "geeknews", "contest"}
    assert seed.seed(c, "봇-테스트", TODAY) == []                       # 두 번째는 모두 건너뜀
    texts = " ".join(sh.message_text(m) for m in c.store["C1"])
    assert "전송일 : *26/11/21*" in texts and "26/11/13" not in texts


def test_collect_notices_and_news_through_pagination():
    c = FakeSlack(page=2)
    seed.seed(c, "봇-테스트", TODAY)
    cid = sh.find_channel_id(c, "봇-테스트")
    assert cid == "C1" and sh.find_channel_id(c, "nope") is None
    notices, last = sh.collect_notices(c, cid, 0)
    assert {(n.platform, n.problem_id) for n in notices} == {("programmers", "181936"), ("swea", "6329")}
    assert all(n.sent_date == TODAY for n in notices)                    # 시스템·기타 메시지는 무시됨
    arts, _ = sh.collect_news(c, cid, 0)
    assert {a.source_name for a in arts} == {"GeekNews", "AI TIMES"}
    # 증분 수집: 마지막 ts 이후에는 새 메시지가 없다
    assert sh.collect_news(c, cid, last)[0] == []


def test_channel_name_overrides(monkeypatch):
    monkeypatch.setenv("CHANNEL_NAME_ALL", "봇-테스트")
    monkeypatch.setenv("CHANNEL_NAME_NEWS", "뉴스-테스트")
    monkeypatch.setenv("BOT_DATA_DIR", "data-test")
    try:
        importlib.reload(config)
        assert config.CHANNEL_NAMES == {"contest": "봇-테스트", "news": "뉴스-테스트", "coding": "봇-테스트"}
        assert config.DATA_DIR.name == "data-test" and config.CACHE_DIR.parent.name == "data-test"
    finally:
        monkeypatch.undo()
        importlib.reload(config)
    assert config.CHANNEL_NAMES["news"] == "인공지능-소식" and config.DATA_DIR.name == "data"
