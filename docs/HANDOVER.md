# 인수인계 문서 — AILAB 슬랙 채널 도우미 봇

- 작성 기준일: 2026-11-23
- 이 문서의 목적: 이 프로젝트를 처음 맡는 사람이 **무엇이 어디서 돌아가고, 어떻게 설치·운영·수정하고, 무엇이 아직 검증되지 않았는지**를 한 번에 파악하도록 합니다.
- 이 문서에는 비밀값(토큰, 웹훅 주소, 시트 URL, 계정 정보)을 적지 않습니다. **저장소가 공개(PUBLIC)이므로 이 저장소 어디에도 비밀값을 올리면 안 됩니다.** 값은 "어디서 발급받고 어디에 넣는지"만 적었습니다.

## 문서 지도

| 문서 | 내용 | 언제 보나 |
|---|---|---|
| `README.md` | 무엇을 하는 봇인지, 기능, 모델 선택 근거, 실행 방법, 알려진 한계 | 처음 소개할 때 |
| `CONTEXT.md` | 어떤 데이터를 어떻게 다루는지(대상 자료, 분할·메타데이터, 갱신, 보안, 범위 밖) | 데이터 관련 판단이 필요할 때 |
| `상세구현명세서.md` | 어떻게 만드는지(형식, 설정, 처리 흐름, 프롬프트, 테스트, 오류 처리). **15장에 구현 현황과 명세와 다르게 구현한 점** | 코드를 고칠 때 |
| `docs/HANDOVER.md` (이 문서) | 인수인계: 계정·설치·운영·문제 해결·다음 할 일 | 인수받는 날부터 |

내용이 서로 다르면 `README.md`, `CONTEXT.md`가 우선이고 `상세구현명세서.md`를 고칩니다(명세서 맨 앞 규칙).

---

## 1. 한눈에 보기

### 1.1 무엇인가
동아리 슬랙의 `#2-공모전`, `#인공지능-소식`, `#2026-코딩테스트` 채널 자료를 근거로, **봇과의 DM 질문에 출처 링크와 함께 답하는 봇**입니다. 모든 모델은 로컬(Ollama)에서 돌고 상용 LLM API는 쓰지 않습니다.

### 1.2 구성 요소는 두 개이고, 서로 다른 곳에서 돕니다

| 구성 요소 | 어디서 도나 | 하는 일 | 설정은 어디에 |
|---|---|---|---|
| **수집 스크립트** (`app_script/`) | **구글 서버**(Google Apps Script, 트리거) | 링커리어·AI타임스·인공지능신문·문제 목록을 가져와 **슬랙 채널에 알림을 올리고 구글 시트에 기록** | 각 Apps Script 프로젝트의 **스크립트 속성** |
| **봇** (`app.py`, `index.py`, `src/`) | **내 PC(WSL2)** | 시트와 슬랙 채널 기록을 읽어 인덱싱하고, DM 질문에 답함 | **`.env`** |

> 두 구성 요소는 **서로의 설정을 읽지 못합니다.** Apps Script는 구글 서버에서 돌기 때문에 내 PC의 `.env`를 볼 수 없고, 웹훅 주소는 스크립트 속성에만 있습니다.

### 1.3 데이터 흐름

```
 [링커리어 API] [AI타임스/인공지능신문 RSS] [시트의 문제 목록]
          │  Apps Script (구글 서버, 시간 기반 트리거)
          ▼
   구글 시트(기록) ──────────────┐            슬랙 채널(웹훅으로 알림)
          │                      │                    │
          │ CSV 게시 URL         │                    │ conversations.history
          ▼                      ▼                    ▼
   ┌──────────────── 봇 (내 PC, WSL2) ────────────────────┐
   │ index.py  →  Chroma(data/chroma) + 캐시(data/cache)   │
   │ app.py (Socket Mode, DM 전용, LangGraph)              │
   │    ├─ Ollama: gemma3(생성) / bge-m3(임베딩)           │
   │    ├─ Docker: 코딩테스트 풀이 격리 실행·검증          │
   │    └─ (선택) 웹 검색: 수상작 분석                      │
   └───────────────────────────────────────────────────────┘
          ▲                                  │
   사용자 DM 질문                      스레드로 답변(+LangSmith 추적)
```

### 1.4 요청 한 건의 흐름 (`src/graph.py`)
`parse`(채널 결정) → 지원 외 채널이면 안내 / 애매하면 `ask`(되묻기, `interrupt`로 일시 정지) → `contest` | `news` | `coding` | 수상작 분석(`w_*`) → `format`.
- 채널은 `#채널명`, 문장 속 키워드, 후속 질문("두 번째 공고…")의 순서로 정합니다(규칙 기반이라 LLM 호출 없음).
- 같은 스레드 = 같은 `thread_id`(`채널ID:thread_ts`). 되묻기와 후속 질문 상태는 `data/checkpoints.sqlite`에 저장됩니다.
- 답변은 먼저 "읽는 중…" 메시지를 보내고 단계마다 갱신한 뒤 최종 답변으로 교체합니다.
- Ollama는 한 번에 하나만 돌리므로 질문은 직렬 처리합니다(대기 중이면 "n번째 대기" 표시).

---

## 2. 인수 체크리스트 — 넘겨받아야 하는 계정과 권한

이 항목들을 **하나씩 확인하고 칸을 채우세요.** 값 자체는 이 문서에 쓰지 말고 안전한 곳(비밀번호 관리자 등)으로 직접 전달하세요.

| # | 항목 | 어디에 쓰이나 | 없으면 | 인수 확인 |
|---|---|---|---|---|
| 1 | **동아리 구글 계정** (시트와 Apps Script 소유) | 시트 5개 + Apps Script 프로젝트 5개 | 수집·알림이 멈추고 봇 데이터가 갱신되지 않음 | ☐ |
| 2 | **슬랙 워크스페이스 관리 권한** (앱 설정 가능한 권한) | 봇 앱, 웹훅, 채널 초대 | 봇 토큰 재발급·권한 변경 불가 | ☐ |
| 3 | **슬랙 봇 앱** (Bot 토큰 `xoxb-`, App 토큰 `xapp-`) | `app.py` 실행 | 봇이 시작하지 않음 | ☐ |
| 4 | **슬랙 웹훅 주소** (채널별, Apps Script가 사용) | 수집 알림 게시 | 알림이 채널에 올라가지 않음 | ☐ |
| 5 | **LangSmith 계정과 API 키** | 추적(과제 필수 요건) | 봇이 시작하지 않음 | ☐ |
| 6 | **SWEA 읽기 전용 계정** | SWEA 문제 본문 읽기 | SWEA 풀이 불가(안내 문구로 응답) | ☐ |
| 7 | **시트 CSV 게시 URL 5개** | 봇이 시트를 읽음 | 봇이 시작하지 않음 | ☐ |
| 8 | **GitHub 저장소 쓰기 권한** | 코드 반영 | 코드 수정 불가 | ☐ |
| 9 | (선택) **Naver 검색 API 키** 또는 SearXNG | 수상작 분석 | 수상작 질문만 "웹 검색을 쓸 수 없어…"로 답함 | ☐ |
| 10 | 봇을 돌릴 **PC** (WSL2, 최종 실측은 GPU 8GB급) | 봇·Ollama·Docker | 봇이 답하지 못함(상시 실행 아님) | ☐ |

담당자 기록: 전임 담당 ____________ / 후임 담당 ____________ / 인수일 ____________

---

## 3. 처음부터 설치하기 (WSL2, Ubuntu 기준)

### 3.1 준비물 설치
```bash
sudo apt install python3.12-venv           # 필요 시
git clone https://github.com/DMU-AILAB/slack_bot.git && cd slack_bot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt  # 시간이 걸립니다(LangChain, Chroma, scikit-learn 등)

# Ollama (https://ollama.com 설치 후)
ollama pull gemma3:1b      # 개발용. 최종은 gemma3:4b
ollama pull bge-m3         # 임베딩

# 코드 실행 검증용 Docker 이미지 (Docker 데몬이 WSL에서 동작해야 함)
docker pull python:3.12-slim
```
- 개발 PC에 GPU가 없으면 `gemma3:1b`(CPU)로 파이프라인만 확인하고, `gemma3:4b` 실측은 GPU PC에서 합니다(7장).

### 3.2 슬랙 앱 설정 (관리자)
1. 앱 만들기 → **Socket Mode 켜기**, 앱 수준 토큰 발급(스코프 `connections:write`) → `SLACK_APP_TOKEN`(`xapp-`).
2. **Bot Token Scopes**: `chat:write`, `im:history`, `im:read`, `channels:read`, `channels:history`. 채널이 비공개면 `groups:read`, `groups:history`도 추가. 스코프를 바꾸면 **앱을 다시 설치**해야 합니다 → `SLACK_BOT_TOKEN`(`xoxb-`).
3. **Event Subscriptions**: `message.im`.
4. **App Home**: Messages Tab 켜기, 사용자가 메시지를 보낼 수 있게 허용.
5. 봇을 `#2-공모전`, `#인공지능-소식`, `#2026-코딩테스트`에 **초대**합니다(채널 ID는 코드에 없고 시작할 때 이름으로 조회).
6. 수집 알림용 **Incoming Webhook**(채널별)은 Apps Script가 쓰며, 3.4에서 스크립트 속성에 넣습니다.

### 3.3 구글 시트 CSV URL 만들기
각 시트 파일의 해당 탭을 **파일 → 공유 → 웹에 게시 → (탭 선택) → CSV**로 게시하고 URL을 복사합니다. 5개입니다.

| `.env` 변수 | 시트 파일 | 탭 |
|---|---|---|
| `SHEET_CSV_CONTEST` | `2-공모전` | `시트1` |
| `SHEET_CSV_NEWS_INAI` | `인공지능-소식 (인공지능신문)` | `전송기록` |
| `SHEET_CSV_NEWS_AITIMES` | `인공지능-소식 (AI TIEMS)` (파일 이름의 오타 `TIEMS`는 그대로) | `전송기록` |
| `SHEET_CSV_CODING_PROGRAMMERS` | `코딩-테스트 (Programmers)` | `Programmers` |
| `SHEET_CSV_CODING_SWEA` | `코딩-테스트 (SWEA)` | `SWEA` |

- **이 URL을 아는 사람은 시트를 읽을 수 있습니다.** 토큰처럼 취급하고 `.env`에만 둡니다.
- **`동아리 인원관리` 등 개인정보 시트는 절대 게시하지 않습니다.** 위 5개 파일에는 개인정보가 없습니다. `코딩-테스트 (사용X)` 파일은 쓰지 않는 옛 파일입니다.

### 3.4 `.env` 작성
```bash
cp .env.example .env && chmod 600 .env
```
- **필수 13개 + 권장 1개**(`USER_HASH_SALT`)를 채웁니다. 변수별 설명은 `.env.example`에 있습니다.
- **주석(`#`)으로 막힌 `CHANNEL_NAME_*`, `BOT_DATA_DIR`은 켜지 마세요.** 켜 두면 운영 실행도 테스트 채널을 봅니다(테스트는 `--test` 옵션, 5.3).
- 빠진 변수 이름만 확인(값은 출력하지 않음):
  ```bash
  .venv/bin/python -c "from src import config; print(config.missing_env(config.APP_REQUIRED))"   # [] 이면 준비 완료
  ```
- 새 환경변수를 코드에 추가하면 **`.env.example`도 함께 고칩니다.**

### 3.5 첫 실행
```bash
.venv/bin/python index.py      # 시트·슬랙을 읽어 인덱싱 (처음에는 몇 분)
.venv/bin/python app.py        # 봇 시작 (Socket Mode). 슬랙에서 봇에게 DM을 보냅니다
```
- 먼저 **테스트 채널로 시험**하는 것을 권장합니다(5.3).
- `app.py`는 시작할 때 모든 채널 데이터를 한 번 갱신하고, 이후 질문이 올 때 마지막 갱신 후 60분이 지났으면 해당 채널만 다시 갱신합니다(주기 타이머 없음).

---

## 4. 수집 스크립트(Apps Script) 운영

### 4.1 프로젝트 5개

| 프로젝트 폴더(`app_script/projects/`) | 연결된 시트 | 코드 파일 | 진입 함수 | 일정 |
|---|---|---|---|---|
| `contest` | `2-공모전` | `contest_linkareer.gs` | `fetchAndSendContestToSlack` | 트리거 기반(수집 기록상 매일 12:40경). **편집기에서 확인** |
| `programmers` | `코딩-테스트 (Programmers)` | `coding_programmers.gs` | `sendDailyProgrammers` | **화·금**에만 발송(함수가 요일 검사) |
| `swea` | `코딩-테스트 (SWEA)` | `coding_swea.gs` | `sendDailySWEA` | **월·목**에만 발송(함수가 요일 검사) |
| `aitimes_kr` | `인공지능-소식 (인공지능신문)` | `news_aitimes_rss.gs` (+`site.gs`) | `sendAiTimesNews` | **평일 09·13·18시**(아래 4.4) |
| `aitimes_com` | `인공지능-소식 (AI TIEMS)` | `news_aitimes_rss.gs` (+`site.gs`) | `sendAiTimesNews` | **평일 09·13·18시**(아래 4.4) |

- 뉴스 두 프로젝트는 **같은 코드**이고, `deploy.sh`가 프로젝트마다 `site.gs`(`DEFAULT_SITE = "kr"|"com"`)를 만들어 구분합니다.
- 프로그래머스·SWEA는 시트의 `완료여부`가 `완료`가 아닌 **첫 행**이 다음 문제이고, **전송에 성공한 뒤에만 `완료`로 표시**합니다. 수동으로 운영 함수를 실행하면 문제가 소진되므로 **시험은 반드시 `test…` 함수로** 하세요.

### 4.2 스크립트 속성 (각 프로젝트의 프로젝트 설정 → 스크립트 속성)

| 속성 | 용도 |
|---|---|
| `SLACK_WEBHOOK_URL` | 운영 채널 웹훅 (코드에 직접 쓰지 않음) |
| `SLACK_WEBHOOK_URL_TEST` | 테스트 채널 웹훅 (`test…` 함수가 사용) |
| `TEST_MODE` | `true`이면 **트리거 실행까지** 테스트 모드가 됩니다. 평소에는 설정하지 말고 `test…` 함수를 쓰세요 |
| `AITIMES_SITE` | (선택) 뉴스 사이트 지정. 보통 `site.gs`로 충분 |

### 4.3 코드 배포 (clasp, 로컬 → 구글)
Apps Script 코드는 **이 저장소의 `app_script/*.gs`가 원본**입니다. 편집기에서 직접 고치면 다음 배포 때 사라지거나 충돌합니다.

```bash
npm install -g @google/clasp
clasp login                 # 동아리 계정으로 로그인(브라우저 승인). 토큰은 ~/.clasprc.json — 커밋 금지
# Apps Script API 사용 설정: https://script.google.com/home/usersettings 에서 켜기
```
1. 프로젝트별 **스크립트 ID**를 편집기의 *프로젝트 설정 → 스크립트 ID*에서 복사해 `app_script/projects/<이름>/.clasp.json`에 `{"scriptId":"…","rootDir":"."}` 형식으로 만듭니다(**`.gitignore`로 제외되어 저장소에 없음**, 5개 모두 필요).
2. 배포: `cd app_script && ./deploy.sh [프로젝트…]` (인자를 생략하면 5개 전체). `DRY=1 ./deploy.sh`는 올리지 않고 파일만 준비합니다.
3. **배포 전 점검(권장)**: 프로젝트 폴더에서 `clasp pull`로 편집기 코드를 받아 마지막 배포본과 비교하세요. 편집기에서 직접 고친 내용이 있으면 덮어쓰게 됩니다.
4. 스크립트 속성은 코드와 별개라 배포해도 유지됩니다.
5. `clasp run`은 GCP 프로젝트 연결이 필요해서 쓰지 않았습니다. 실행 확인은 편집기에서 함수를 실행하고 **실행 로그**를 봅니다.

### 4.4 트리거 — ⚠ 인수 시 반드시 확인
- 트리거는 **편집기(왼쪽 시계 아이콘)에서만** 설정됩니다. `clasp`로 바꿀 수 없습니다.
- 뉴스 프로젝트는 편집기에서 **`setupNewsTriggers()`를 한 번 실행**하면 평일(월~금) 09·13·18시 트리거 15개를 만듭니다(기존 `sendAiTimesNews`, `fetchAITimesAndSendToSlack` 시간 트리거는 삭제, 재실행해도 중복 없음). 시각·요일은 스크립트 상단 `TRIGGER_HOURS`, `TRIGGER_WEEKDAYS`. **작성 시점(2026-11-23)에 이 함수가 실행되었는지는 확인하지 못했습니다.** `logTriggers()`로 현재 트리거 현황을 확인하세요.
- 구글은 지정 시각 전후 약 15분 안에 실행합니다.

### 4.5 뉴스 수집 정책 (중요)
- RSS의 새 기사를 **모두 시트에 기록**하고, **슬랙에는 최신 10건(`MAX_SLACK_POSTS`)만** 올립니다. 넘치는 기사(주말에 쌓인 기사 등)는 시트에만 기록되고 슬랙에 올라오지 않습니다.
- 시트 열은 `수집시간 | 기사 제목 | 주소` 3개입니다. **기준 시각은 수집시간**이며 발행일은 기록하지 않습니다(월요일 아침 실행분에는 주말 기사가 월요일 시각으로 들어감).
- AI타임스 RSS는 **최신 50건(약 3일치)** 만 유지합니다. **3일 넘게 수집이 멈추면 그 사이 기사는 복구할 수 없습니다.** 2026-10-30~11-21 기사는 이 때문에 영구히 빠졌습니다.
- 과거 `AI TIEMS` 수집이 몇 주씩 비었던 것은 옛 HTML 스크래핑이 조용히 실패했기 때문으로 **추정**합니다(확정 못 함). 지금은 RSS이며 실패하면 로그를 남깁니다.

### 4.6 시험(`test…` 함수)
편집기 함수 목록에서 고르면 운영 데이터를 건드리지 않고 1회 실행됩니다.
`testFetchAndSendContestToSlack`, `testSendAiTimesNews`, `testSendDailyProgrammers`, `testSendDailySWEA`
- 사전 조건: 스크립트 속성 `SLACK_WEBHOOK_URL_TEST`. 없으면 운영 채널로 새지 않고 로그만 남깁니다.
- 동작: 테스트 웹훅으로만 보내고, 시트·중복 방지 기록·`완료` 표시를 바꾸지 않으며, 제목에 `🧪 [TEST]`가 붙습니다. 프로그래머스·SWEA는 요일과 무관하게 보냅니다.

### 4.7 외부 의존성 (바뀌면 깨지는 곳)
| 대상 | 의존 | 깨졌을 때 신호 |
|---|---|---|
| 링커리어 목록 API | GraphQL **persisted query 해시**가 URL에 고정 | 로그에 `❌ API 오류` — 브라우저 개발자 도구에서 새 요청 URL을 받아 `LINKAREER_API_URL` 교체 |
| 링커리어 응답 필드 | `recruitCloseAt`(마감일, ms), `organizationName` (**시작일 필드는 없음**) | `debugShowFields()` 실행 후 로그 확인 |
| AI타임스 RSS | `…/rss/allArticle.xml`, `S1N24.xml` (인공지능신문은 `S1N4.xml`) | 로그에 `RSS 실패` |
| 프로그래머스 문제 페이지 | HTML 구조(`.guide-section-description .markdown`) | 봇이 "문제 본문을 찾지 못했습니다"로 답함 |

---

## 5. 봇 운영

### 5.1 자주 쓰는 명령
```bash
.venv/bin/python app.py                       # 봇 실행(운영)
.venv/bin/python index.py                     # 전체 증분 갱신
.venv/bin/python index.py --channel news      # contest | news | coding 중 하나만
.venv/bin/python index.py --rebuild           # 벡터스토어와 상태를 지우고 처음부터(인덱스가 꼬였을 때)
.venv/bin/python -m pytest tests -q           # 테스트 88개
ollama ps                                     # 적재된 모델과 메모리 확인
```
- **봇은 상시 실행이 아닙니다.** 직접 실행해 두었을 때만 답합니다(꺼져 있는 동안 온 DM은 처리하지 않음). 상시 실행은 향후 계획입니다(8장).
- 봇은 **DM 전용**입니다. 채널 메시지·멘션에는 반응하지 않고, 채널에 직접 글을 쓰지도 않습니다.

### 5.2 파일과 데이터 위치 (모두 `.gitignore`로 제외)
| 경로 | 내용 |
|---|---|
| `.env` | 비밀값 (권한 600 권장) |
| `data/chroma/` | 벡터스토어(`contest`, `news` 컬렉션) |
| `data/cache/` | 문제 본문, 기사 본문, 공모전 상세, 검색 결과, 코딩 인덱스, 인덱싱 해시 |
| `data/state.json` | 채널별 마지막 갱신 시각, 슬랙 마지막 `ts` |
| `data/checkpoints.sqlite` | 스레드별 대화 상태(되묻기·후속 질문) |
| `logs/bot.log` | 회전 로그(1MB × 3). 질문은 앞 200자, 사용자는 해시로, 비밀값은 마스킹 |
| `data-test/` | `--test` 실행 때의 별도 데이터 |

### 5.3 테스트 채널로 시험하기 (운영 채널을 건드리지 않음)
```bash
python scripts/seed_test_channel.py          # 테스트 채널(기본 "봇-테스트")에 실제 형식 메시지 게시. --dry-run, --keep-dates
python index.py --test                       # 테스트 채널에서 수집해 data-test/ 에 인덱싱
python app.py --test                         # 테스트 설정으로 봇 실행 후 DM으로 질문
```
- `--test`는 세 채널을 모두 테스트 채널로, 데이터 폴더를 `data-test/`로 바꿉니다. `.env`는 건드리지 않고, 옵션을 빼면 운영 설정입니다. 시작할 때 `🧪 테스트 모드` 안내가 출력됩니다.
- 시드 스크립트는 **운영 채널에 게시하지 않도록 막혀 있고**, 여러 번 실행해도 중복되지 않습니다.
- 테스트 채널이 비공개면 슬랙 스코프 `groups:read`, `groups:history`와 봇 초대가 필요합니다.

### 5.4 튜닝 지점 (`src/config.py`)
| 상수 | 기본 | 의미 |
|---|---|---|
| `GEN_MODEL`(`.env`) | `gemma3:1b` | 생성 모델. 최종은 `gemma3:4b`. **모델 이름은 이 한 곳에서만 바꿉니다** |
| `NUM_CTX` | 4096 | 컨텍스트. 8192로 올리면 VRAM 여유가 줄어듭니다 |
| `REFRESH_INTERVAL_MIN` | 60 | 질문 시 갱신 기준(분) |
| `CLUSTER_DISTANCE_THRESHOLD` | 0.35 | 기사 군집 거리. **실데이터로 튜닝 필요**(7장) |
| `NEWS_DEFAULT_DAYS`, `NEWS_TOP_N` | 7, 3 | "최근" 기본 기간, 이슈 개수 |
| `MAX_REGEN` | 3 | 풀이 검증 실패 시 재생성 횟수 |
| `RUN_TIMEOUT_SEC`, `RUN_MEM_LIMIT_MB` | 5, 256 | 풀이 실행 1회 제한 |
| `ENRICH_*` | 45일, 30건 | 마감일이 빈 최근 공고의 상세 페이지를 읽는 범위 |
| `WINNERS_*`, `SEARCH_*` | | 수상작 분석의 페이지·검색 상한과 최소 근거 수 |

---

## 6. 코드 지도

```
app.py                  Slack Bolt(Socket Mode) 진입점. DM 처리, 직렬화, 진행 표시, 오류 문구
index.py                수집·인덱싱 CLI (--channel, --rebuild, --test)
src/
  config.py             환경변수와 상수(채널 이름 오버라이드, BOT_DATA_DIR 포함)
  testmode.py           --test 옵션 처리(config import 전에 호출)
  graph.py              LangGraph 정의(노드, 분기, 되묻기 interrupt)
  router.py             채널 파싱·추정(규칙 기반)      followup.py  후속 질문 해석
  llm.py                Ollama 호출 헬퍼(공통 시스템 규칙, JSON 복구)
  slack_io.py           메시지 분할, 진행 상황 갱신, 고정 문구
  tracing.py            LangSmith 설정(실행 config)
  common/               text.py(정규화·날짜·KST), logging_setup.py(마스킹 로그)
  sources/              sheets.py(CSV 로더) slack_history.py(blocks 파서·수집)
                        web.py(캐시·지연·robots·SSRF 차단·링커리어 상세) search.py(웹 검색 provider)
  rag/                  store.py(Chroma) indexer.py(수집→문서→저장) state.py(갱신 시각)
  contest/              query.py(질의 분석) flow.py(검색·답변 조립) winners.py(수상작 분석)
  news/                 window.py(기간·개수) cluster.py(군집·점수) flow.py(이슈 요약·주제 검색)
  coding/               resolve.py(대상 문제) problems.py(본문·예시) swea_client.py(SWEA 로그인)
                        generate.py(풀이·힌트) sandbox.py(Docker 격리 실행) flow.py(단계·응답 조립)
scripts/seed_test_channel.py   테스트 채널 시드
app_script/             Apps Script 원본(*.gs), deploy.sh, projects/<이름>/(스크립트 ID는 로컬에만)
tests/                  단위·통합 테스트(+ Apps Script를 Node로 모의하는 appscript/harness.js)
```

설계상 지켜야 할 원칙(고칠 때 깨지 않게):
1. **목록·링크·날짜는 코드가 조립하고, LLM은 문장 생성에만 씁니다.** 작은 모델이 흔들려도 링크가 틀리지 않게 하려는 설계입니다.
2. **모델이 만든 URL은 후처리에서 제거**합니다. 링크는 인덱스·시트·실제로 읽은 검색 결과 URL만 허용합니다.
3. **자료 안의 문장은 지시가 아니라 정보**로만 취급합니다(프롬프트 주입 방어). 풀이 코드는 **Docker 안에서만** 실행합니다.
4. **상태(LangGraph)에 비밀값을 넣지 않습니다.** SWEA 계정은 `swea_client.py` 안에서만 읽고 추적 대상 밖에 둡니다.
5. 마감일을 알 수 없는 공고를 모집 중이라고 **단정하지 않습니다**("마감일 확인 필요").

---

## 7. 현재 상태 — 완료된 것, 검증하지 못한 것, 알려진 한계

### 7.1 구현·검증된 것 (테스트 88개 통과)
- 시트 로더, blocks 기반 슬랙 파서(웹훅 메시지는 `text`가 비어 있을 수 있어 `blocks`를 먼저 읽음), 링커리어 상세 파서(실제 페이지로 확인)
- 공모전: 모집 중 검색·마감 임박·신규·개별 상세 — **실제 시트 행 20건과 실제 링커리어 상세 18건**으로 동작 확인
- 소식: 이슈 요약·주제 검색 — 실제 기사 10건으로 동작 확인
- 코딩: 프로그래머스 181936번 실제 페이지로 읽기→풀이→Docker 검증→재생성 확인. 샌드박스(무한 루프, 금지 import, `open` 차단) 확인
- 수상작 분석: 가짜 검색 결과 + 실제 `gemma3:1b`로 추출·근거 검증·출처 병합 확인
- 그래프: 되묻기 일시 정지·재개, 만료, 후속 질문, 오류 문구를 가짜 슬랙 클라이언트로 확인
- Apps Script: 정상 모드와 `TEST_MODE`/`test…` 함수의 부작용 차이, 트리거 설정 함수를 Node 하네스로 확인

### 7.2 ⚠ 검증하지 못한 것 (인수 후 가장 먼저 해볼 것)
| 항목 | 이유 | 확인 방법 |
|---|---|---|
| **슬랙 Socket Mode 실연결, DM 응답** | 작업 중 토큰이 없었음 | `.env` 작성 → 5.3의 테스트 채널 순서 |
| **SWEA 로그인·문제 읽기** | 계정 없음. 폼을 동적으로 찾는 최선의 구현이며 샘플 입출력 파싱은 추정 | 계정으로 직접 실행, 약관(자동 접근 허용 여부) 확인. 캡차·추가 인증이 나오면 우회하지 않고 멈춤 |
| **웹 검색(Naver/SearXNG) 실호출** | 키 없음, 가짜 결과로만 검증 | 키 발급 후 실제 공모전 5개로 수상 항목 추출률 확인 |
| **LangSmith 추적 캡처** | 키 없음 | 채널별 추적 1건씩 캡처(공모전, 소식 이슈, 코딩 검증, 가능하면 재생성) |
| **`gemma3:4b` 실행·VRAM·속도** | 개발 PC에 GPU 없음 | GPU PC(WSL2)에서 `ollama ps`로 8GB 이하 확인, 응답 시간 측정, README 3장 비교표 |
| **뉴스 트리거(`setupNewsTriggers`) 실행 여부** | 사용자 계정에서만 가능 | `logTriggers()` |
| 시트 CSV URL 로딩 | URL 없음(실제 행은 도구로 읽어 같은 파서에 넣어 검증) | `index.py` 실행 로그 |

### 7.3 알려진 한계
- 봇은 직접 실행한 동안에만 답합니다(상시 실행 아님).
- 작은 모델(`gemma3:1b`)은 코딩테스트 풀이를 자주 틀립니다. 틀리면 **`검증 실패`로 정직하게 표시**하고 정답을 보장하지 않습니다. 예시 통과도 숨겨진 테스트 통과를 보장하지 않습니다.
- "중요한 이슈"는 기사 수·매체 수·최신성 기준이며 객관적 중요도가 아닙니다. 군집 임계값·점수 가중치는 **실데이터로 튜닝하지 않았습니다**(검증 데이터의 기사가 10건뿐).
- 공모전은 수집 스크립트가 제목에 AI/인공지능/데이터가 있는 공고만 모읍니다. 시작일은 링커리어 API에 없어서 상세 페이지(최근 45일분)에서 채웁니다.
- 수상작 분석은 웹 검색 결과를 정리한 것이라 공식 결과와 다를 수 있고, 이미지·PDF 포스터는 읽지 못합니다.
- 시트에만 기록된 기사(슬랙에 올리지 않은 것)는 슬랙 요약이 없어서, 봇이 질문 시 본문을 읽어 보완합니다.
- GeekNews는 외부 앱이 올리는 글이라 형식이 바뀌면 파서를 고쳐야 하고, 읽지 못한 메시지는 건너뛰고 로그에 남깁니다.

---

## 8. 다음 할 일 (우선순위)

1. **슬랙 실연결 검증** — `.env` 작성 → 테스트 채널로 시험(5.3) → 운영 전환.
2. **뉴스 트리거 확인** — `setupNewsTriggers()` 실행 여부, 평일 09·13·18시에 시트에 새 행이 쌓이는지.
3. **GPU PC 실측(M6)** — `gemma3:4b` 전환, `ollama ps`, 응답 시간, 1b/4b 비교표, LangSmith 캡처.
4. **SWEA 확인** — 로그인과 샘플 파싱, 약관.
5. **수상작 분석 키 설정과 품질 측정** — Naver 키(또는 SearXNG). 과제의 "상용 API 금지"가 LLM API만 뜻하는지 확인(포함이면 SearXNG 자체 호스팅을 기본으로 변경).
6. **군집 임계값·점수 가중치 튜닝** — 기사가 충분히 쌓인 뒤 실데이터로.
7. **상시 실행** — WSL2 systemd 서비스(`Restart=on-failure`) + Windows 로그온 때 WSL 시작. 현재 상시 실행 PC는 미정.
8. (보류) **코딩 전용 모델** — `CODE_MODEL` 설정 분리 후 `qwen2.5-coder` 등과 예시 통과율·응답 시간·VRAM 비교. 모델이 3개가 되면 VRAM 8GB 초과 여부를 실측해야 합니다.
9. **알려진 개선점** — 체크포인트 삭제는 "7일간 DB가 한 번도 쓰이지 않았을 때 파일 전체 삭제"로 단순하게 구현되어 있습니다.

---

## 9. 문제 해결

| 증상 | 가능한 원인 | 조치 |
|---|---|---|
| `app.py`가 바로 종료되며 "필수 환경변수가 없습니다" | `.env` 누락·오타 | 출력된 변수 이름을 `.env`에 채움(3.4의 확인 명령) |
| 슬랙 DM에 답이 없음 | 봇 프로세스가 꺼져 있음(상시 실행 아님), Socket Mode·`message.im` 구독·Messages Tab 설정 누락 | `app.py` 실행 확인 → 3.2 설정 재확인 |
| "모델 서버에 연결하지 못했습니다" | Ollama가 꺼짐 | `ollama serve` 또는 `curl localhost:11434/api/tags` |
| 시작 로그에 "슬랙 채널 '…'를 찾지 못함" | 봇 미초대, 비공개 채널인데 `groups:*` 스코프 없음 | 채널에 봇 초대, 스코프 추가 후 앱 재설치 |
| 공모전 답변이 "마감일 확인 필요"뿐 | Apps Script 미실행, 시트 마감일 비어 있음 | 링커리어 스크립트 로그·`debugShowFields()` 확인. 봇은 최근 45일분 상세 페이지로 보완 |
| 소식에 최신 기사가 없음 | 뉴스 트리거 미설정·실패, RSS 변경 | 답변 끝의 "매체별 마지막 기사" 날짜 확인 → 트리거와 실행 로그 |
| Apps Script 로그에 `❌ API 오류` | 링커리어 persisted query 해시 만료 | 4.7 참고(URL 교체) |
| Apps Script 로그에 `RSS 실패` | RSS 경로 변경 | 후보 경로(`SITES`)를 새 경로로 수정 후 배포 |
| "문제 본문을 찾지 못했습니다" | 프로그래머스 HTML 구조 변경 | `src/coding/problems.py`의 `parse_programmers` 수정, `tests/fixtures/programmers_181936.html` 갱신 |
| SWEA "추가 인증이 요구되어…" | 캡차·2차 인증 | **우회하지 않습니다.** 수동 확인 |
| 코드 검증이 항상 "검증 불가"/Docker 오류 | Docker 데몬 정지, 이미지 없음 | `docker info`, `docker pull python:3.12-slim`. 임시로 `SANDBOX=local`(보안 경계가 아님) |
| 수상작 질문에 "웹 검색을 쓸 수 없어…" | 검색 키 없음, 한도 초과 | Naver 키 확인(`SEARCH_PROVIDER`) |
| 되묻기 후 답을 보냈는데 "대기 시간이 지났습니다" | 10분(`PENDING_TTL_MIN`) 경과 | 질문을 다시 보냄 |
| 검색 결과가 이상하거나 인덱스 오류 | 인덱스 손상·모델 변경 | `python index.py --rebuild` |
| 운영 봇이 테스트 채널을 봄 | `.env`에 `CHANNEL_NAME_*`/`BOT_DATA_DIR`을 켜 둠 | 해당 줄을 주석 처리하고 테스트는 `--test` 사용 |

로그: `logs/bot.log`. 처리 실패 시 사용자에게는 짧은 문구만 보이고 스택은 로그에만 남습니다.

---

## 10. 보안 규칙 (공개 저장소 주의)

- **올리면 안 되는 것**: `.env`, 슬랙 토큰(`xoxb-`, `xapp-`), **웹훅 주소**, 시트 CSV URL, LangSmith·Naver 키, SWEA 계정, `.clasp.json`(스크립트 ID), `~/.clasprc.json`, 개인정보 시트.
- 웹훅 주소를 아는 사람은 누구나 채널에 글을 쓸 수 있습니다. **실수로 올렸다면 파일을 지우는 것으로는 부족하고(git 기록에 남음) 해당 값을 재발급**해야 합니다.
- 커밋 전에 `git status`와 `git add -n .`로 올라갈 파일을 확인하세요. `.gitignore`가 `.env`, `data/`, `data-test/`, `logs/`, `.clasp.json`을 제외합니다.
- 테스트 fixture에 실제 외부 페이지를 쓸 때는 **제3자 이메일·연락처를 지웁니다**(이미 한 번 정리함).
- SWEA는 실제로 쓰지 않는 전용 계정만 쓰고, 이용약관을 확인합니다. 캡차·2차 인증은 우회하지 않습니다.
- 로그에는 시트 URL·토큰이 마스킹되어 남지만, 로그 파일을 공유할 때는 한 번 더 확인하세요.

---

## 부록 A. 변경 이력 요약 (주요 결정)

| 결정 | 이유 |
|---|---|
| 뉴스 시트의 기준 시각은 **수집시간**(발행일 미기록) | 단순함 우선. 월요일 아침 실행분의 주말 기사가 월요일로 분류되는 오차는 감수 |
| 슬랙에는 최신 10건만, 나머지는 시트에만 | 채널 소음 방지 + 봇 데이터 누락 방지. 하루 약 16건이 올라오는데 예전 상한(10건/일 1회)으로는 기사를 놓침 |
| 뉴스 트리거를 평일 09·13·18시로 | 출근·점심·퇴근 시간. 주말 기사는 월요일 첫 실행에 시트로만 들어옴 |
| 풀이 검증은 Docker 격리 | 문제 페이지의 글이 프롬프트에 들어가므로 격리가 필수. 로컬 실행은 1차 방어일 뿐 |
| 코딩 전용 모델은 보류 | 모델이 3개가 되어 VRAM·로딩 지연 부담. 벤치마크 후 결정 |
| 라우팅·질의 분석은 규칙 기반 | 소형 모델에서 구조화 출력이 불안정하고 호출이 줄어듦 |
| 수상작 분석은 근거 문장 문자열 검증 | 소형 모델이 수상작을 지어내는 것을 차단. 모델이 스키마를 베끼는 문제가 실제로 확인되어 few-shot과 정규식 보조 추출 추가 |
| 공모전 상세 페이지는 마감일이 빈 최근 45일분도 읽음 | 마감일이 비어 있으면 상세를 읽을 기회가 없어지는 순환을 막기 위함 |

## 부록 B. 이 문서를 최신으로 유지하기
- 설정·환경변수를 바꾸면 `.env.example`과 3.4를, 트리거·일정을 바꾸면 4장을, 새 검증 결과가 나오면 7장을 고칩니다.
- 큰 변경은 `상세구현명세서.md` 15장에도 기록합니다.
