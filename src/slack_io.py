"""슬랙 답변 포맷, 메시지 분할, ack/update, 진행 상황 (상세구현명세서 7.1)."""
import logging
import time

from src import config

log = logging.getLogger(__name__)

MSG_READING = "읽는 중…"
MSG_QUEUED = "읽는 중… ({n}번째 대기)"
MSG_OLLAMA_DOWN = "모델 서버에 연결하지 못했습니다. Ollama가 켜져 있는지 확인해 주세요."
MSG_TIMEOUT = "답변이 너무 오래 걸려 중단했습니다."
MSG_ERROR = "처리 중 오류가 났습니다. 잠시 뒤 다시 시도해 주세요."
MSG_EXPIRED = "이전 질문의 답변 대기 시간이 지났습니다. 질문을 다시 보내 주세요."

# 그래프 노드 이름 → 진행 문구 (사용자 질문이나 자료 내용은 넣지 않는다)
PROGRESS_LABELS = {
    "parse": "질문을 읽는 중…",
    "contest_prepare": "공모전 자료를 확인하는 중…",
    "contest_answer": "공모전 답변을 정리하는 중…",
    "news_answer": "기사를 모아 정리하는 중…",
    "c_resolve": "대상 문제를 찾는 중…",
    "c_fetch": "문제 페이지를 읽는 중…",
    "c_generate": "풀이를 생성하는 중…",
    "c_run": "예시로 실행해 검증하는 중…",
    "w_queries": "검색어를 만드는 중…",
    "w_search": "웹에서 검색하는 중…",
    "w_select": "읽을 페이지를 고르는 중…",
    "w_read": "페이지를 읽는 중…",
    "w_extract": "수상 항목을 추출하는 중…",
    "w_synth": "공통 특징을 정리하는 중…",
}


def split_message(text: str, limit: int = config.MAX_CHARS_PER_MESSAGE) -> list[str]:
    """문단 단위로 묶어 limit 이하로 나눈다. 코드블록이 잘리면 닫고 다음 조각에서 다시 연다."""
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for para in text.split("\n\n"):
        piece = para if not cur else "\n\n" + para
        if len(cur) + len(piece) <= limit:
            cur += piece
            continue
        if cur:
            chunks.append(cur)
        while len(para) > limit:  # 한 문단이 너무 길면 줄 단위로 자름
            cut = para.rfind("\n", 0, limit)
            cut = cut if cut > 0 else limit
            chunks.append(para[:cut])
            para = para[cut:].lstrip("\n")
        cur = para
    if cur:
        chunks.append(cur)
    fixed, reopen = [], False
    for c in chunks:
        if reopen:
            c = "```\n" + c
        reopen = c.count("```") % 2 == 1
        fixed.append(c + ("\n```" if reopen else ""))
    return fixed


def post_answer(client, channel: str, thread_ts: str, ack_ts: str, text: str) -> None:
    """첫 조각은 '읽는 중…' 메시지를 교체하고, 나머지는 같은 스레드에 이어서 보낸다."""
    parts = split_message(text)
    opts = dict(unfurl_links=False, unfurl_media=False)
    client.chat_update(channel=channel, ts=ack_ts, text=parts[0], **opts)
    for p in parts[1:]:
        client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=p, **opts)


class Progress:
    """같은 메시지를 갱신해 진행 상황을 보인다. 슬랙 호출 제한 때문에 최소 간격을 둔다."""

    def __init__(self, client, channel: str, ack_ts: str):
        self.client, self.channel, self.ack_ts = client, channel, ack_ts
        self.last_sent, self.last_text = 0.0, MSG_READING

    def update(self, node: str, extra: str = "") -> None:
        label = PROGRESS_LABELS.get(node)
        if not label:
            return
        text = label + (f" {extra}" if extra else "")
        now = time.time()
        if text == self.last_text or now - self.last_sent < config.PROGRESS_MIN_INTERVAL_SEC:
            return
        try:
            self.client.chat_update(channel=self.channel, ts=self.ack_ts, text=text)
            self.last_sent, self.last_text = now, text
        except Exception:  # 진행 표시 실패가 답변을 막으면 안 된다
            log.debug("진행 상황 갱신 실패", exc_info=True)
