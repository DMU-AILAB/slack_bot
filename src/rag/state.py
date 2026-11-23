"""data/state.json: 마지막 갱신·수집 시각 (상세구현명세서 5.3)."""
import json
from datetime import datetime

from src import config
from src.common.text import KST, kst_now


def load() -> dict:
    try:
        return json.loads(config.STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"refresh": {}, "slack": {}}


def save(state: dict) -> None:
    config.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def mark_refreshed(channel: str) -> None:
    s = load()
    s.setdefault("refresh", {})[channel] = kst_now().isoformat()
    s["last_refresh"] = s["refresh"][channel]
    save(s)


def last_refresh(channel: str) -> datetime | None:
    v = load().get("refresh", {}).get(channel)
    return datetime.fromisoformat(v).astimezone(KST) if v else None


def is_stale(channel: str, minutes: int = config.REFRESH_INTERVAL_MIN) -> bool:
    t = last_refresh(channel)
    return t is None or (kst_now() - t).total_seconds() > minutes * 60


def slack_last_ts(key: str) -> str | None:
    return load().get("slack", {}).get(key)


def set_slack_last_ts(key: str, ts: str) -> None:
    s = load()
    s.setdefault("slack", {})[key] = ts
    save(s)
