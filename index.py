"""수집·인덱싱 CLI.  python index.py [--channel contest|news|coding] [--rebuild] [--test]

--test: 채널을 테스트 채널로, 데이터 폴더를 data-test/ 로 바꿔서 실행한다(운영 데이터는 건드리지 않음).
"""
import argparse
import sys

from src import testmode

TEST_MODE = testmode.apply(sys.argv)   # src.config를 import하기 전에 호출해야 한다

from src import config
from src.common.logging_setup import setup_logging
from src.rag import indexer


def main() -> int:
    ap = argparse.ArgumentParser(epilog="--test: 테스트 채널과 data-test/ 로 실행 (운영 데이터는 건드리지 않음)")
    ap.add_argument("--channel", choices=list(indexer.CHANNELS))
    ap.add_argument("--rebuild", action="store_true", help="벡터스토어와 상태를 지우고 처음부터")
    args = ap.parse_args()
    config.ensure_dirs()
    setup_logging()
    if TEST_MODE:
        print(testmode.banner())
    if args.rebuild:
        indexer.rebuild()
    names = [args.channel] if args.channel else list(indexer.CHANNELS)
    ok_all = True
    for n in names:
        ok, msg = indexer.refresh_channel(n)
        print(("✅ " if ok else "❌ ") + msg)
        ok_all &= ok
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
