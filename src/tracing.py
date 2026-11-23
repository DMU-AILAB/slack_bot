"""LangSmith 설정 (상세구현명세서 10장). 필수 요건이므로 없으면 변수 이름만 알리고 중단한다."""
import os

from src import config


def setup_tracing(required: bool = True) -> list[str]:
    """누락된 변수 이름 목록을 돌려준다. required이면 누락 시 SystemExit."""
    missing = config.missing_env(["LANGSMITH_API_KEY", "LANGSMITH_TRACING"])
    if missing and required:
        raise SystemExit("LangSmith 설정이 없습니다. .env에 다음 변수를 넣어 주세요: " + ", ".join(missing))
    if not missing:
        os.environ.setdefault("LANGSMITH_PROJECT", config.env("LANGSMITH_PROJECT", "ailab-slack-bot"))
        os.environ["LANGSMITH_TRACING"] = config.env("LANGSMITH_TRACING", "true")
    return missing


def run_config(channel: str | None, intent: str | None, user_hash: str, thread_id: str) -> dict:
    """요청 1건 = 추적 1건. 사용자 ID는 해시로만 남긴다."""
    return {
        "configurable": {"thread_id": thread_id},
        "run_name": f"{channel or 'unrouted'}:{intent or 'n/a'}",
        "tags": [channel or "unrouted"],
        "metadata": {"user": user_hash, "model": config.GEN_MODEL},
    }
