#!/usr/bin/env bash
# Apps Script 5개 프로젝트에 clasp로 코드를 올린다.
# 사용: ./deploy.sh [프로젝트...]   (생략하면 전체)   예: ./deploy.sh contest swea
# 환경: DRY=1 이면 파일 준비만 하고 push 하지 않는다.
# 각 projects/<이름>/.clasp.json(스크립트 ID, 커밋 금지)이 있어야 한다.
set -euo pipefail
cd "$(dirname "$0")"

declare -A SRC=(
  [contest]="contest_linkareer.gs"
  [swea]="coding_swea.gs"
  [programmers]="coding_programmers.gs"
  [aitimes_com]="news_aitimes_rss.gs"
  [aitimes_kr]="news_aitimes_rss.gs"
)
declare -A SITE=([aitimes_com]="com" [aitimes_kr]="kr")

targets=("$@"); [ ${#targets[@]} -eq 0 ] && targets=(contest swea programmers aitimes_com aitimes_kr)

for n in "${targets[@]}"; do
  d="projects/$n"
  [ -f "$d/.clasp.json" ] || { echo "❌ $d/.clasp.json 없음"; exit 1; }
  rm -f "$d"/*.gs
  cp "${SRC[$n]}" "$d/"
  [ -n "${SITE[$n]:-}" ] && printf 'var DEFAULT_SITE = "%s";\n' "${SITE[$n]}" > "$d/site.gs"
  echo "== $n: $(ls "$d" | tr '\n' ' ')"
  if [ "${DRY:-0}" != "1" ]; then (cd "$d" && clasp push --force); fi
done
