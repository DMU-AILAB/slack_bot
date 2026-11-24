import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures():
    return FIX


@pytest.fixture
def slack_msgs():
    return json.loads((FIX / "slack_messages.json").read_text(encoding="utf-8"))


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    """data/ 를 건드리지 않도록 상태·캐시 경로를 임시 폴더로 바꾼다."""
    from src import config
    from src.rag import indexer
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(config, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(config, "CHROMA_DIR", tmp_path / "chroma")          # 운영 벡터스토어를 건드리지 않도록
    # 테스트가 실제 슬랙·시트·네트워크에 닿지 않게 한다(봇이 채널에 초대되면 결과가 달라지는 문제 방지).
    monkeypatch.setattr(indexer, "refresh_if_stale", lambda name: False)
    monkeypatch.setattr(indexer, "CODING_INDEX", tmp_path / "cache" / "coding_index.json")
    for sub in ("problems", "articles", "contests", "search"):
        (tmp_path / "cache" / sub).mkdir(parents=True)
    return tmp_path
