"""--test 옵션 처리. src.config를 import하기 전에 호출해야 한다(config가 import 시점에 환경변수를 읽음).

--test 를 주면 .env 내용과 관계없이 채널 이름을 테스트 채널로, 데이터 폴더를 data-test 로 바꾼다.
.env 파일은 수정하지 않으므로 옵션을 빼면 곧바로 운영 설정으로 돌아간다.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEST_CHANNEL = "봇-테스트"
TEST_DATA_DIR = "data-test"
CHANNEL_VARS = ("CHANNEL_NAME_ALL", "CHANNEL_NAME_CONTEST", "CHANNEL_NAME_NEWS", "CHANNEL_NAME_CODING")


def apply(argv: list[str]) -> bool:
    """argv에서 --test를 제거하고, 있었다면 테스트 환경으로 바꾼 뒤 True를 돌려준다."""
    if "--test" not in argv:
        return False
    while "--test" in argv:
        argv.remove("--test")
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")          # TEST_CHANNEL_NAME을 읽기 위해 먼저 로드(이미 있는 환경변수는 덮지 않음)
    channel = os.environ.get("TEST_CHANNEL_NAME") or DEFAULT_TEST_CHANNEL
    for k in CHANNEL_VARS:              # .env에 채널별 값이 있어도 테스트 채널이 이기도록 모두 명시한다
        os.environ[k] = channel
    os.environ["BOT_DATA_DIR"] = TEST_DATA_DIR
    return True


def banner() -> str:
    from src import config
    names = sorted(set(config.CHANNEL_NAMES.values()))
    return f"🧪 테스트 모드: 채널 {', '.join('#' + n for n in names)} · 데이터 {config.DATA_DIR.name}/"
