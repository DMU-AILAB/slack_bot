#!/usr/bin/env bash
# 노트북 → 파이로 코드만 동기화한다. .env, data, 로그, 가상환경, NAS 문서는 보내지 않는다.
#   사용법: bash deploy/sync_to_pi.sh [사용자@호스트] [원격경로]
set -euo pipefail
DEST="${1:-visionguide@192.168.0.59}"
RPATH="${2:-/srv/nas/ailab-bot/app}"
cd "$(dirname "$0")/.."
ssh "$DEST" "mkdir -p '$RPATH'"
rsync -av --delete \
  --exclude '.env' --exclude '.venv' --exclude 'data' --exclude 'data-test' --exclude 'logs' \
  --exclude '__pycache__' --exclude '.pytest_cache' --exclude '.git' --exclude 'evals/results' \
  --exclude 'NAS_*.pdf' --exclude '.webhooks*' --exclude '*.local' \
  ./ "$DEST:$RPATH/"
echo "동기화 완료 → $DEST:$RPATH  (.env 는 따로 복사하세요)"
