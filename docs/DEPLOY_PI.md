# 라즈베리파이 4 (8GB) 배포 가이드

NAS로 쓰는 라즈베리파이 4 Model B(8GB, Debian 13, aarch64)에서 봇을 **CPU만으로** 상시 실행하는 방법입니다. 모델 서버(Ollama), 봇, 코딩 샌드박스(Docker)가 모두 파이 한 대에서 돕니다.

> **상태**: 파일은 준비됐지만 **파이에서 실제로 돌려 보지는 못했습니다.** 현재 확인된 파이는 2GB 모델이라 8GB 모델로 교체한 뒤 아래 순서대로 진행합니다. 속도 수치는 설치 후 `check_pi.sh`와 평가(`evals`)로 직접 재서 이 문서에 적으세요.

## 예상 자원 (추정, 실측 필요)
| 항목 | 값 |
|---|---|
| 메모리 | `gemma3:1b` 약 1GB + `bge-m3` 약 1.2GB + 봇·Chroma 1~2GB → 약 4GB. 8GB에서 여유 있음 (4GB 모델은 빠듯함) |
| 답변 속도 | 목록형(공모전·코딩)은 LLM 없이 1초 안팎. 소식 요약·상세 설명은 수십 초 예상 → `LLM_TIMEOUT_SEC=300` |
| 첫 인덱싱 | 임베딩 수천 건이 CPU에서 느림 → **노트북에서 먼저 만들어 복사** 권장 (아래 4) |
| 코딩 풀이 | 파이 CPU에서 1b 모델이 느림. 쓰지 않으려면 코딩 질문은 안내만 (`SANDBOX`와 무관, 기능 끄기는 후속 작업) |

## 0. 사전 준비
- 파이를 8GB 모델로 교체하고 같은 SD 카드/SSD로 부팅. IP `192.168.0.59` 유지(공유기 DHCP 예약 권장).
- 노트북이 같은 Wi-Fi(`204_WIFI`)에 있거나 Tailscale로 연결.
- SSH는 **키 인증**으로 쓰고 비밀번호 로그인은 끕니다 (`ssh-copy-id`, 이후 `/etc/ssh/sshd_config`의 `PasswordAuthentication no`). 방화벽(UFW)도 켭니다: `sudo ufw allow 22,80,139,445/tcp && sudo ufw enable`. Ollama(11434)는 `127.0.0.1`에만 열려 있어 외부에서 접근되지 않습니다.

## 1. 코드 보내기 (노트북에서)
```bash
bash deploy/sync_to_pi.sh                 # 기본: visionguide@192.168.0.59:/srv/nas/ailab-bot/app
```
`.env`, `data/`, 로그, 가상환경, NAS 문서(PDF)는 **보내지 않습니다**.

## 2. 설치 (파이에서)
```bash
ssh visionguide@192.168.0.59
cd /srv/nas/ailab-bot/app
bash deploy/install_pi.sh
```
패키지, 파이썬 환경, Ollama(+모델), Docker(+샌드박스 이미지), systemd 서비스를 설치합니다. 파이썬 3.13에서 `chromadb`, `scikit-learn` 등이 aarch64 휠로 설치되는지는 **이번에 처음 확인**하게 됩니다. 실패하면 오류 메시지를 알려 주세요.

## 3. .env 복사 (노트북에서, 비밀값이라 따로)
```bash
scp .env visionguide@192.168.0.59:/srv/nas/ailab-bot/app/.env
ssh visionguide@192.168.0.59 'chmod 600 /srv/nas/ailab-bot/app/.env && cat /srv/nas/ailab-bot/app/deploy/env.pi.example >> /srv/nas/ailab-bot/app/.env'
```
`env.pi.example`는 비밀값이 없는 파이용 조정값입니다(`NUM_CTX`, `LLM_TIMEOUT_SEC`, `BOT_DATA_DIR=/srv/nas/ailab-bot/data` 등). 같은 키가 `.env`에 이미 있으면 **아래 줄이 이깁니다**(중복 줄은 정리하세요). 데이터를 SSD(`/srv/nas`)에 두는 이유는 SD 카드 쓰기 마모를 줄이기 위해서입니다.

## 4. 첫 인덱스 (둘 중 하나)
- **권장**: 노트북에서 운영 설정으로 `python index.py`를 실행한 뒤 `data/`를 복사.
  ```bash
  rsync -av data/ visionguide@192.168.0.59:/srv/nas/ailab-bot/data/
  ```
  임베딩 모델(`bge-m3`)이 같아야 합니다. 복사 후 파이에서 `.venv/bin/python index.py`를 한 번 돌려 정상 인식·증분 갱신되는지 확인하세요.
- 파이에서 직접: `.venv/bin/python index.py` (오래 걸림. `tmux`나 `nohup`으로).

## 5. 점검과 시작
```bash
bash deploy/check_pi.sh                    # 모델·Docker·테스트·속도 점검 (비밀값 출력 없음)
sudo systemctl start ailab-bot
journalctl -u ailab-bot -f                 # "Bolt app is running" 확인
```
먼저 **테스트 채널로** 검증하려면 서비스 대신 `.venv/bin/python app.py --test`를 직접 실행하세요(운영 데이터와 분리됩니다). 운영 전환은 `--test` 없이 서비스로 시작하는 것입니다.

## 6. 운영
| 작업 | 명령 |
|---|---|
| 상태 | `systemctl status ailab-bot ollama` |
| 재시작 | `sudo systemctl restart ailab-bot` |
| 로그 | `journalctl -u ailab-bot -n 100 --no-pager` |
| 코드 갱신 | 노트북에서 `sync_to_pi.sh` → 파이에서 `sudo systemctl restart ailab-bot` |
| 메모리 | `free -m`, `ollama ps` |
| 재부팅 후 | 서비스가 자동 시작됨(`enable`). Ollama·Docker도 자동 |

## 7. 문제 해결
| 증상 | 확인 |
|---|---|
| 답이 매우 느리거나 시간 초과 | `LLM_TIMEOUT_SEC` 늘리기, `NUM_CTX=2048`, `ollama ps`로 모델이 올라와 있는지 |
| 메모리 부족으로 서비스 종료 | `dmesg \| grep -i oom`, `MemoryMax` 조정, 스왑/zram 확인 |
| 코딩 풀이가 "샌드박스를 쓸 수 없음" | `docker info`, 로그아웃 후 재로그인(`docker` 그룹 적용) |
| 슬랙에서 `not_in_channel` | 채널에서 `/invite @inso_bot` |
| 답변 끝에 "자료를 갱신하지 못했습니다" | 파이의 인터넷 연결, 시트 공유 설정, 봇 채널 멤버십 |

## 8. 주의
- LangSmith 추적은 켜 두면 질문·검색 결과가 LangSmith 클라우드로 전송됩니다(원하지 않으면 `.env`에서 `LANGSMITH_TRACING=false`).
- 단일 디스크라 중복성이 없습니다. `data/`는 다시 만들 수 있지만 `.env`는 따로 백업하세요.
- 속도가 부족하면 같은 공유기 안의 GPU PC를 모델 서버로 쓰고 `.env`의 `OLLAMA_HOST`만 바꾸면 됩니다(코드 수정 없음).
