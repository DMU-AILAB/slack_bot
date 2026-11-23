"""슬랙 봇 진입점 (Socket Mode, DM 전용).  python app.py [--test]

--test: 채널을 테스트 채널(TEST_CHANNEL_NAME, 기본 봇-테스트)로, 데이터 폴더를 data-test/ 로 바꿔서 실행한다.
"""
import sys

from src import testmode

TEST_MODE = testmode.apply(sys.argv)   # src.config를 import하기 전에 호출해야 한다

import logging
import sqlite3
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone

from langgraph.types import Command

from src import config, llm, slack_io
from src.common.logging_setup import setup_logging, short_q, user_hash
from src.common.text import kst_today
from src.graph import build_graph
from src.rag import indexer
from src.tracing import run_config, setup_tracing

log = logging.getLogger("app")
_sem = threading.Semaphore(1)       # Ollama는 한 번에 하나만 잘 돌아가므로 직렬화
_waiting = 0
_wait_lock = threading.Lock()
_seen: "OrderedDict[str, float]" = OrderedDict()   # 슬랙 재전송 이벤트 중복 방지


def _duplicate(key: str) -> bool:
    with _wait_lock:
        if key in _seen:
            return True
        _seen[key] = time.time()
        while len(_seen) > 500:
            _seen.popitem(last=False)
    return False


def prune_checkpoints() -> None:
    """체크포인트 DB가 TTL(7일) 동안 한 번도 쓰이지 않았다면 모든 스레드가 만료된 것이므로 삭제한다."""
    p = config.CHECKPOINT_DB
    if p.exists() and time.time() - p.stat().st_mtime > config.CHECKPOINT_TTL_DAYS * 86400:
        p.unlink()
        log.info("만료된 체크포인트 DB 삭제")


def handle(graph, client, channel: str, user: str, text: str, ts: str, thread_ts: str, ack_ts: str) -> None:
    thread_id = f"{channel}:{thread_ts}"
    uh = user_hash(user)
    cfg = run_config(None, None, uh, thread_id)
    progress = slack_io.Progress(client, channel, ack_ts)
    try:
        snap = graph.get_state(cfg)
        resume = False
        if snap.next:  # 되묻기로 멈춰 있는 스레드
            created = datetime.fromisoformat(snap.created_at) if snap.created_at else None
            age = (datetime.now(timezone.utc) - created).total_seconds() / 60 if created else 0
            if age > config.PENDING_TTL_MIN:
                slack_io.post_answer(client, channel, thread_ts, ack_ts, slack_io.MSG_EXPIRED)
                graph.update_state(cfg, {"answer": None}, as_node="format")  # 대기 종료
                return
            resume = True
        inp = Command(resume=text) if resume else {"question": text, "user_hash": uh, "today": kst_today().isoformat()}
        interrupt_text = None
        for update in graph.stream(inp, cfg, stream_mode="updates"):
            for node, val in update.items():
                if node == "__interrupt__":
                    interrupt_text = val[0].value["text"]
                else:
                    progress.update(node)
        if interrupt_text:
            slack_io.post_answer(client, channel, thread_ts, ack_ts, interrupt_text)
            return
        answer = graph.get_state(cfg).values.get("answer") or "답변을 만들지 못했습니다."
        slack_io.post_answer(client, channel, thread_ts, ack_ts, answer)
        log.info("처리 완료 user=%s q=%s", uh, short_q(text))
    except llm.LLMUnavailable:
        log.warning("Ollama 연결 실패 user=%s", uh)
        slack_io.post_answer(client, channel, thread_ts, ack_ts, slack_io.MSG_OLLAMA_DOWN)
    except Exception:
        log.exception("처리 실패 user=%s q=%s", uh, short_q(text))
        slack_io.post_answer(client, channel, thread_ts, ack_ts, slack_io.MSG_ERROR)


def main() -> int:
    config.ensure_dirs()
    setup_logging()
    missing = config.missing_env(config.APP_REQUIRED)
    if missing:  # 값은 출력하지 않고 이름만
        print("필수 환경변수가 없습니다: " + ", ".join(missing), file=sys.stderr)
        return 1
    setup_tracing(required=True)
    if not llm.ollama_alive():
        log.warning("Ollama에 연결할 수 없습니다. 질문이 들어오면 안내 문구로 답합니다.")

    prune_checkpoints()
    from langgraph.checkpoint.sqlite import SqliteSaver
    saver = SqliteSaver(sqlite3.connect(str(config.CHECKPOINT_DB), check_same_thread=False))
    graph = build_graph(saver)

    # 시작 시 따라잡기: 실패해도 봇은 시작한다
    try:
        for name, (ok, msg) in indexer.refresh_all(force=True).items():
            log.info("시작 갱신 %s: %s", name, msg)
    except Exception:
        log.exception("시작 시 갱신 실패 (기존 인덱스로 시작)")

    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler
    app = App(token=config.env("SLACK_BOT_TOKEN"))

    @app.event("message")
    def on_message(event, client):
        global _waiting
        if event.get("channel_type") != "im" or event.get("bot_id") or event.get("subtype"):
            return
        text = (event.get("text") or "").strip()
        if not text or _duplicate(event.get("client_msg_id") or event["ts"]):
            return
        channel, user, ts = event["channel"], event["user"], event["ts"]
        thread_ts = event.get("thread_ts") or ts
        with _wait_lock:
            _waiting += 1
            pos = _waiting
        first = slack_io.MSG_READING if pos == 1 else slack_io.MSG_QUEUED.format(n=pos - 1)
        ack = client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=first)
        try:
            with _sem:
                handle(graph, client, channel, user, text, ts, thread_ts, ack["ts"])
        finally:
            with _wait_lock:
                _waiting -= 1

    if TEST_MODE:
        banner = testmode.banner()
        log.warning(banner)
        print(banner)
    log.info("봇 시작 (모델 %s)", config.GEN_MODEL)
    SocketModeHandler(app, config.env("SLACK_APP_TOKEN")).start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
