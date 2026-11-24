#!/usr/bin/env bash
# 설치 점검. 비밀값은 출력하지 않는다(변수 이름만).
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ok(){ echo "✅ $1"; }; ng(){ echo "❌ $1"; BAD=1; }
uname -m | grep -q aarch64 && ok "aarch64" || ng "aarch64 아님"
free -m | awk '/Mem/{print "   RAM(MB) 총 "$2", 가용 "$7}'
curl -fs http://127.0.0.1:11434/api/tags >/dev/null && ok "Ollama 응답" || ng "Ollama 응답 없음"
for m in gemma3:1b bge-m3; do ollama list 2>/dev/null | grep -q "^$m" && ok "모델 $m" || ng "모델 $m 없음"; done
[ -f "$APP_DIR/.env" ] && ok ".env 있음 (권한 $(stat -c %a "$APP_DIR/.env"))" || ng ".env 없음"
docker info >/dev/null 2>&1 && ok "Docker 사용 가능" || ng "Docker 사용 불가(그룹 적용을 위해 재로그인 필요할 수 있음)"
"$APP_DIR/.venv/bin/python" -c "import chromadb, langchain_ollama, slack_bolt, sklearn; print('✅ 패키지 import')" 2>&1 | tail -1
cd "$APP_DIR" && .venv/bin/python -m pytest -q 2>&1 | tail -1
echo "-- 임베딩·생성 속도 --"
/usr/bin/time -f "   임베딩 %es" curl -fs http://127.0.0.1:11434/api/embeddings -d '{"model":"bge-m3","prompt":"공모전 마감 안내"}' >/dev/null
/usr/bin/time -f "   생성(짧은 답) %es" curl -fs http://127.0.0.1:11434/api/generate -d '{"model":"gemma3:1b","prompt":"안녕이라고만 답해.","stream":false,"options":{"num_predict":20}}' >/dev/null
[ -z "$BAD" ] && echo "모두 정상" || echo "위 ❌ 항목을 먼저 해결하세요"
