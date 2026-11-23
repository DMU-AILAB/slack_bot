"""Chroma 벡터스토어 래퍼 (상세구현명세서 5.2, 6.5). 코사인 거리, 문서 ID로 upsert."""
import hashlib
import json
import logging
from functools import lru_cache

from src import config

log = logging.getLogger(__name__)
HASH_FILE = config.CACHE_DIR / "index_hash.json"


@lru_cache(maxsize=1)
def embeddings():
    from langchain_ollama import OllamaEmbeddings
    return OllamaEmbeddings(model=config.EMBED_MODEL, base_url=config.OLLAMA_HOST)


@lru_cache(maxsize=4)
def get_store(name: str):
    from langchain_chroma import Chroma
    config.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    return Chroma(collection_name=name, embedding_function=embeddings(),
                  persist_directory=str(config.CHROMA_DIR),
                  collection_metadata={"hnsw:space": "cosine"})


def clean_meta(meta: dict) -> dict:
    """Chroma는 str/int/float/bool만 허용한다. None은 빈 값으로."""
    out = {}
    for k, v in meta.items():
        if v is None:
            out[k] = 0 if k.endswith("_ts") or k.endswith("_epoch") else ""
        elif isinstance(v, (str, int, float, bool)):
            out[k] = v
        else:
            out[k] = str(v)
    return out


def _hashes() -> dict:
    try:
        return json.loads(HASH_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def upsert_changed(name: str, docs: list[tuple[str, str, dict]], batch: int = 32) -> tuple[int, int]:
    """(id, text, meta) 목록 중 내용이 바뀐 것만 임베딩해서 upsert한다. (바뀐 수, 전체 수) 반환."""
    hashes = _hashes()
    changed = []
    for did, text, meta in docs:
        h = hashlib.sha1((text + json.dumps(meta, sort_keys=True, default=str)).encode()).hexdigest()
        if hashes.get(f"{name}:{did}") != h:
            changed.append((did, text, meta, h))
    if changed:
        store = get_store(name)
        for i in range(0, len(changed), batch):
            part = changed[i:i + batch]
            store.add_texts(texts=[t for _, t, _, _ in part], metadatas=[clean_meta(m) for _, _, m, _ in part],
                            ids=[d for d, _, _, _ in part])
            for d, _, _, h in part:
                hashes[f"{name}:{d}"] = h
        HASH_FILE.parent.mkdir(parents=True, exist_ok=True)
        HASH_FILE.write_text(json.dumps(hashes), encoding="utf-8")
    return len(changed), len(docs)


def reset_all() -> None:
    import shutil
    shutil.rmtree(config.CHROMA_DIR, ignore_errors=True)
    HASH_FILE.unlink(missing_ok=True)
    get_store.cache_clear()
