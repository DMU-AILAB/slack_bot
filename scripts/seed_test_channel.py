"""테스트 채널에 실제 형식의 슬랙 메시지를 올려, 봇의 슬랙 수집 경로를 운영 채널 없이 시험한다.

사용:  python scripts/seed_test_channel.py            # TEST_CHANNEL_NAME(기본 봇-테스트)에 게시
       python scripts/seed_test_channel.py --dry-run  # 올리지 않고 내용만 출력
       python scripts/seed_test_channel.py --keep-dates

안전장치
- 운영 채널(2-공모전, 인공지능-소식, 2026-코딩테스트)에는 절대 올리지 않는다.
- 이미 같은 내용이 있으면 건너뛴다(여러 번 실행해도 중복되지 않음).
- 코딩 알림의 전송일은 기본으로 오늘 날짜로 바꿔서 "오늘의 문제" 경로를 시험할 수 있게 한다.
필요한 권한: chat:write, channels:read/history, 비공개 채널이면 groups:read/history. 봇이 채널에 초대되어 있어야 한다.
"""
import argparse
import html
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.common.text import kst_today  # noqa: E402
from src.sources import slack_history as sh  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "slack_messages.json"
PRODUCTION_CHANNELS = set(config.DEFAULT_CHANNEL_NAMES.values())
_DATE = re.compile(r"전송일 : \*\d\d/\d\d/\d\d\*")


class SeedError(RuntimeError):
    pass


def build_messages(today: date, keep_dates: bool = False) -> list[dict]:
    """fixture의 메시지를 게시용으로 만든다(ts는 슬랙이 새로 붙임)."""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    stamp = f"전송일 : *{today:%y/%m/%d}*"
    out = []
    for name, m in data.items():
        m = json.loads(json.dumps(m))
        if not keep_dates:
            for b in m.get("blocks") or []:
                for el in b.get("elements") or []:
                    if isinstance(el.get("text"), str):   # 버튼 등은 text가 객체라 건너뜀
                        el["text"] = _DATE.sub(stamp, el["text"])
            m["text"] = _DATE.sub(stamp, m.get("text", ""))
        m.pop("ts", None)
        out.append({"name": name, **m})
    return out


def _post_args(m: dict) -> dict:
    # blocks가 있으면 text는 대체 문구다. 둘 다 없으면 슬랙이 거부하므로 text는 항상 채운다.
    text = m.get("text") or sh.flatten_blocks(m.get("blocks"))[0] or "(내용 없음)"
    args = {"text": text, "unfurl_links": False, "unfurl_media": False}
    if m.get("blocks"):
        args["blocks"] = m["blocks"]
    return args


def seed(client, channel_name: str, today: date | None = None, dry_run: bool = False,
         keep_dates: bool = False) -> list[str]:
    """게시한(또는 dry-run이면 게시할) 메시지 이름 목록을 돌려준다."""
    if channel_name in PRODUCTION_CHANNELS:
        raise SeedError(f"'{channel_name}'은 운영 채널입니다. 테스트 채널에만 올릴 수 있습니다.")
    msgs = build_messages(today or kst_today(), keep_dates)
    if dry_run:
        return [m["name"] for m in msgs]
    cid = sh.find_channel_id(client, channel_name)
    if not cid:
        raise SeedError(f"채널 '{channel_name}'을 찾지 못했습니다. 채널을 만들고 봇을 초대했는지 확인하세요.")
    existing = {sh.message_text(x).strip() for x in sh.fetch_history(client, cid, 0)}
    posted = []
    for m in msgs:
        args = _post_args(m)
        # 슬랙에서 읽은 텍스트(message_text)와 같은 방식(blocks 우선, &amp; 해제)으로 비교한다
        probe = html.unescape(sh.flatten_blocks(m.get("blocks"))[0] if m.get("blocks") else m.get("text", "")).strip()
        if probe and probe in existing:
            continue
        client.chat_postMessage(channel=cid, **args)
        posted.append(m["name"])
    return posted


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default=config.TEST_CHANNEL_NAME)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep-dates", action="store_true")
    a = ap.parse_args()
    client = None
    if not a.dry_run:
        token = config.env("SLACK_BOT_TOKEN")
        if not token:
            print("SLACK_BOT_TOKEN이 없습니다 (.env 확인).", file=sys.stderr)
            return 1
        from slack_sdk import WebClient
        client = WebClient(token=token)
    try:
        done = seed(client, a.channel, dry_run=a.dry_run, keep_dates=a.keep_dates)
    except SeedError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    print(("[dry-run] 게시 예정: " if a.dry_run else f"✅ '{a.channel}'에 게시: ") + (", ".join(done) or "없음(이미 모두 있음)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
