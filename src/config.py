"""환경변수와 상수 (상세구현명세서 4장). 비밀값은 .env에서만 읽고 출력하지 않는다."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def env_int(name: str, default: int) -> int:
    try:
        return int(env(name, str(default)))
    except ValueError:
        return default


# 테스트 채널을 쓸 때 운영 데이터와 섞이지 않도록 BOT_DATA_DIR=data-test 처럼 분리한다.
_data = env("BOT_DATA_DIR")
DATA_DIR = (ROOT / _data if _data and not Path(_data).is_absolute() else Path(_data)) if _data else ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
CHROMA_DIR = DATA_DIR / "chroma"
STATE_FILE = DATA_DIR / "state.json"
CHECKPOINT_DB = DATA_DIR / "checkpoints.sqlite"
LOG_DIR = ROOT / "logs"


# --- 모델 ---
GEN_MODEL = env("GEN_MODEL", "gemma3:1b")
EMBED_MODEL = env("EMBED_MODEL", "bge-m3")
OLLAMA_HOST = env("OLLAMA_HOST", "http://localhost:11434")
NUM_CTX = env_int("NUM_CTX", 4096)               # 느린 CPU(라즈베리파이)에서는 2048~3072로 줄이면 빨라짐
GEN_TEMPERATURE = 0.2
GEN_NUM_PREDICT = env_int("GEN_NUM_PREDICT", 400)
GEN_NUM_PREDICT_CODE = env_int("GEN_NUM_PREDICT_CODE", 900)
LLM_TIMEOUT_SEC = env_int("LLM_TIMEOUT_SEC", 120)      # 느린 CPU에서는 300 정도로

# --- 검색·분할 ---
REFRESH_INTERVAL_MIN = env_int("REFRESH_INTERVAL_MIN", 60)
CHUNK_SIZE, CHUNK_OVERLAP = 500, 50
TOP_K_CONTEST, TOP_K_NEWS = 6, 6

# --- 소식 ---
NEWS_DEFAULT_DAYS = 7
NEWS_TOP_N, NEWS_MAX_N = 3, 5
CLUSTER_DISTANCE_THRESHOLD = 0.35
SUMMARY_ARTICLES_PER_CLUSTER = 4
SLACK_BACKFILL_DAYS = 14
NEWS_BODY_FETCH_MAX = 12

# --- 코딩 ---
MAX_REGEN = 3
RUN_TIMEOUT_SEC = 5
RUN_MEM_LIMIT_MB = 256
SANDBOX = env("SANDBOX", "docker")  # docker | local
SANDBOX_IMAGE = "python:3.12-slim"

# --- 공모전 ---
ENRICH_UNKNOWN_DEADLINE = (env("ENRICH_UNKNOWN_DEADLINE", "true") or "true").lower() == "true"
ENRICH_RECENT_DAYS = 45
ENRICH_MAX_PER_RUN = 30

# --- 외부 요청 ---
HTTP_TIMEOUT_SEC = 20
HTTP_DELAY_SEC = 1.0
HTTP_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 ailab-slack-bot"

# --- 수상작 분석 ---
SEARCH_PROVIDER = env("SEARCH_PROVIDER", "naver")
SEARCH_TOP_K = 8
SEARCH_MAX_QUERIES = 3
WINNERS_MAX_PAGES = 5
WINNERS_MIN_ENTRIES, WINNERS_MIN_SOURCES = 2, 2
SEARCH_CACHE_HOURS = 24

# --- 슬랙 ---
MAX_CHARS_PER_MESSAGE = 3500
PENDING_TTL_MIN = 10
CHECKPOINT_TTL_DAYS = 7
PROGRESS_MIN_INTERVAL_SEC = 1.0

# 내부 키 → 슬랙 채널 이름. 테스트 때는 환경변수로 바꾼다.
#   CHANNEL_NAME_ALL=봇-테스트            세 채널 모두 한 채널로 (파서는 형식이 맞는 메시지만 읽음)
#   CHANNEL_NAME_CONTEST / _NEWS / _CODING  채널별로 따로 지정
DEFAULT_CHANNEL_NAMES = {"contest": "2-공모전", "news": "인공지능-소식", "coding": "2026-코딩테스트"}
CHANNEL_NAMES = {
    k: env(f"CHANNEL_NAME_{k.upper()}") or env("CHANNEL_NAME_ALL") or v for k, v in DEFAULT_CHANNEL_NAMES.items()
}
TEST_CHANNEL_NAME = env("TEST_CHANNEL_NAME", "봇-테스트")

SHEET_URL_VARS = {
    "contest": "SHEET_CSV_CONTEST",
    "news_inai": "SHEET_CSV_NEWS_INAI",
    "news_aitimes": "SHEET_CSV_NEWS_AITIMES",
    "coding_programmers": "SHEET_CSV_CODING_PROGRAMMERS",
    "coding_swea": "SHEET_CSV_CODING_SWEA",
}


def sheet_url(key: str) -> str | None:
    return env(SHEET_URL_VARS[key])


def missing_env(names: list[str]) -> list[str]:
    """비어 있는 변수의 이름만 돌려준다(값은 다루지 않음)."""
    return [n for n in names if not env(n)]


APP_REQUIRED = [
    "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "LANGSMITH_API_KEY", "LANGSMITH_TRACING",
    "GEN_MODEL", "EMBED_MODEL", *SHEET_URL_VARS.values(), "SWEA_ID", "SWEA_PW",
]


def ensure_dirs() -> None:
    for d in (DATA_DIR, CACHE_DIR, CHROMA_DIR, LOG_DIR, CACHE_DIR / "problems",
              CACHE_DIR / "articles", CACHE_DIR / "contests", CACHE_DIR / "search"):
        d.mkdir(parents=True, exist_ok=True)
