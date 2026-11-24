# 품질 평가 (evals)

답변과 모델을 바꿀 때 "좋아졌는지"를 숫자로 보기 위한 골든셋과 실행기입니다. 정답 문장을 비교하지 않고 **규칙으로 채점**합니다.

## 실행

```bash
python evals/run_eval.py                          # 라우팅 + 검색 (모델 호출 없음, 1분 이내)
python evals/run_eval.py --suite answers          # 실제 답변 (LLM 사용, 약 3분)
python evals/run_eval.py --suite coding --coding-n 8
python evals/run_eval.py --suite all --model gemma3:4b      # 모델 바꿔 전체 평가
python evals/run_eval.py --compare evals/results/a.json evals/results/b.json
```

- 기본은 `data-test/` 인덱스를 읽기만 합니다. 운영 인덱스는 `--data-dir data`.
- 기본은 LangSmith 추적을 **끕니다**(평가 호출이 운영 추적에 섞이지 않게). 추적하려면 `--trace`(프로젝트 `ailab-slack-bot-eval`).
- 결과는 `evals/results/*.json`(git 제외). 수치는 아래 표나 README에 옮겨 적으세요.

## 평가 항목

| 스위트 | 내용 | 주요 지표 | 모델 필요 |
|---|---|---|---|
| `routing` | `evals/golden/routing.jsonl` 49문항: 질문 → 채널, 공모전 의도 | `channel_ok_pct`, `misroute_pct`(확신하고 틀림), `intent_ok_pct` | 아니오 |
| `retrieval` | 인덱스에서 표본 추출: 제목을 대충 기억하고 묻기(공모전), 제목 앞부분으로 기사 찾기(소식) | `contest_title_lookup_pct`, `contest_recall@5_pct`, `news_recall@6_pct` | 임베딩만 |
| `answers` | `evals/golden/answers.jsonl` 18문항을 그래프 전체로 실행 | `pass_pct`, `links_known_pct`, `open_only_pct`, `grounded_pct`, `numbers_grounded_pct`, 지연 | 예 |
| `coding` | 프로그래머스 함수형 문제(정답률 높은 순, SQL 제외) 풀이 | `verified_pass_pct`, `first_try_pass_pct`, 지연 | 예 |

### 채점 규칙 (`evals/metrics.py`)
- **링크 실존**: 답변의 모든 URL이 인덱스에 있는 주소여야 합니다(모델이 만든 링크 탐지).
- **마감일**: "모집 중" 답변에 마감된 공고가 있으면 실패, "이번 주 마감"은 기간 안이어야 합니다.
- **근거 충실도(grounding)**: LLM 호출마다 입력 `<자료>`와 출력을 비교해, 출력의 내용어 중 자료에서 찾을 수 없는 비율을 잽니다. 숫자는 정확히 일치해야 합니다. 조사·어미 변화로 오탐이 있어 **절대 점수가 아니라 모델·프롬프트 간 상대 비교용**입니다.
- 한계: 요약이 *의미상* 맞는지(예: 서로 다른 기사를 한 이슈로 묶음)는 이 채점으로 잡히지 않습니다. 사람이 `results`의 `answer`를 읽어 확인합니다.

## 기준선 (gemma3:1b + bge-m3, CPU 노트북, 2026-11-23)

| 지표 | 값 | 해석 |
|---|---|---|
| 라우팅 채널 정확도 | 95.9% (확신 오분류 4.1%) | 틀린 2건은 `참가`, `발표` 같은 단어 하나로 채널을 단정한 경우 |
| 공모전 의도 분류 | 100% | |
| 공모전 제목 조회 | 87.5% | 실패는 `B.D.A.I`, `물류데이터·AI`처럼 기호가 낀 제목 |
| 공모전 검색 recall@5 | 100% | 쉬운 과제(제목 앞부분)라 하한선으로만 해석 |
| 소식 검색 recall@6 | 100% | 위와 같음 |
| 답변 구조 검사 통과 | 100% (18/18) | 링크 실존·마감일·개수 |
| 근거 충실도 | 85.8%, 근거 밖 30% 초과 4.5% | 소식 이슈 요약에서 근거 밖 표현이 20~33% |
| 지연 (p50 / p90) | 10초 / 17초 | 공모전 목록은 LLM 없이 0.4초 |
| 코딩 검증 통과 (8문제 × 2회) | 75%, 62.5% | 프롬프트 개선 후. 개선 전 25%, 37.5%. 8문제라 ±15%p 변동은 정상 범위 |

## 이 평가로 찾아 고친 결함
1. **SQL 문제를 Python으로 풀려고 3회 시도**: 프로그래머스 SQL 문제의 분류값은 `database`인데 `sql`만 찾고 있었음 → 수정.
2. **상세 질문의 자기모순 답변**: 근거가 한 단어(`기타`)뿐일 때 모델이 "찾지 못했습니다"와 "기타로 기재"를 함께 씀 → 짧은 근거는 원문을 그대로 보여 주고, 모순 응답은 버림.
3. **풀이 프롬프트가 불필요한 `import math`를 유도**: "사용할 수 있는 모듈: math, …" 안내를 첫 시도부터 보여 주면 1b가 곱셈에 `math.pow`, 몫에 `math.gcd`를 씀. 안내를 빼고 *금지된 import 오류가 난 뒤에만* 알려 주도록 변경 → 같은 8문제 검증 통과 25~38% → 63~75% (샌드박스 import 제한은 그대로).
4. **SWEA 로그인 오탐/방식 불일치** (평가 이전에 발견, 같은 계열).

평가 기준의 한계: 코딩 평가는 쉬운 문제(정답률 높은 순) 8개이고, 같은 모델도 실행마다 결과가 달라 단일 실행 비교는 신뢰하기 어렵습니다. 변경의 효과는 **같은 문제를 2회 이상 돌려** 방향이 같은지 보고 판단했습니다.

## 알려진 약점 (아직 고치지 않음)
- 소식 이슈 군집이 서로 다른 기사를 묶는 경우가 있음(예: "LLM 추론 서버 공개"와 "오픈AI 새 추론 모델"). 군집 임계값 조정에는 사람이 라벨링한 기사 묶음이 필요합니다.
- "이번 주"가 월요일에는 하루치입니다(월~오늘).
- 1b 모델은 소식 요약에 근거에 없는 표현을 덧붙입니다(예: "창작자들의 편의성을 높였습니다").
- 공모전 한 줄 요약에 긴 문장이 잘려 `…`으로 끝납니다.

## 골든셋 늘리는 법
`evals/golden/*.jsonl`에 한 줄씩 추가합니다. 마음에 안 들었던 실제 질문이 가장 좋은 항목입니다.
- routing: `{"q": "...", "channel": "contest|news|coding|ask|unsupported", "intent": "...", "ok_ask": true}`
- answers: `min_items`, `empty_ok`, `open_only`, `deadline_within_days`, `contains_any`, `not_contains`, `max_numbered`
