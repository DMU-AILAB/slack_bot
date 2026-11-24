#!/usr/bin/env bash
# 라즈베리파이 4 (8GB, Debian 13, aarch64)에서 한 번 실행하는 설치 스크립트. 여러 번 실행해도 안전하다.
#   사용법:  bash deploy/install_pi.sh            (프로젝트 폴더 안에서, sudo 가능한 계정으로)
# 비밀값은 다루지 않는다. .env 는 따로 복사한다(docs/DEPLOY_PI.md).
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="$(id -un)"
GEN_MODEL="${GEN_MODEL:-gemma3:1b}"
EMBED_MODEL="${EMBED_MODEL:-bge-m3}"

echo "== 1/6 시스템 패키지 =="
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-dev build-essential git rsync curl docker.io

echo "== 2/6 파이썬 환경 ($APP_DIR/.venv) =="
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "== 3/6 Ollama =="
if ! command -v ollama >/dev/null; then
  curl -fsSL https://ollama.com/install.sh | sh
fi
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo cp "$APP_DIR/deploy/ollama-override.conf" /etc/systemd/system/ollama.service.d/override.conf
sudo systemctl daemon-reload
sudo systemctl enable --now ollama
sudo systemctl restart ollama
for i in $(seq 1 20); do curl -fs http://127.0.0.1:11434/api/tags >/dev/null && break || sleep 1; done

echo "== 4/6 모델 내려받기 ($GEN_MODEL, $EMBED_MODEL) =="
ollama pull "$GEN_MODEL"
ollama pull "$EMBED_MODEL"

echo "== 5/6 코딩 풀이 샌드박스 (Docker) =="
sudo systemctl enable --now docker
sudo usermod -aG docker "$RUN_USER" || true
sudo docker pull python:3.12-slim

echo "== 6/6 봇 서비스 등록 =="
sed -e "s|@USER@|$RUN_USER|g" -e "s|@APP_DIR@|$APP_DIR|g" "$APP_DIR/deploy/ailab-bot.service" \
  | sudo tee /etc/systemd/system/ailab-bot.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable ailab-bot

echo
echo "설치 완료. 아직 봇은 시작하지 않았습니다. 다음을 하세요:"
echo "  1) $APP_DIR/.env 를 만든다 (노트북에서 scp 로 복사. docs/DEPLOY_PI.md 참고)"
echo "  2) 새 로그인 세션에서 docker 그룹이 적용되도록 한 번 로그아웃/로그인"
echo "  3) bash $APP_DIR/deploy/check_pi.sh   # 점검"
echo "  4) sudo systemctl start ailab-bot && journalctl -u ailab-bot -f"
