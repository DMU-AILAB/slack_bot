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
    monkeypatch.setattr(indexer, "CODING_INDEX", tmp_path / "cache" / "coding_index.json")
    for sub in ("problems", "articles", "contests", "search"):
        (tmp_path / "cache" / sub).mkdir(parents=True)
    return tmp_path
