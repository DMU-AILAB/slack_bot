"""Apps Script의 TEST_MODE가 운영 데이터를 건드리지 않는지 Node 하네스(모의 Apps Script 전역)로 검증한다."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node가 필요합니다")
HARNESS = Path(__file__).parent / "appscript" / "harness.js"


@pytest.fixture(scope="module")
def r():
    p = subprocess.run(["node", str(HARNESS)], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def hooks(x):
    return {p["url"] for p in x["posts"]}


# ---------------------------------------------------------------- 공모전
def test_contest_normal_mode_unchanged(r):
    x = r["contest_normal"]
    assert hooks(x) == {"https://hooks.test/PROD"} and len(x["posts"]) == 2      # 1, 2번만 (TRAIN은 단어 경계로 제외)
    assert len(x["appended"]) == 2 and "sentIdsArray" in x["propSets"]
    by_title = {row[1]: row for row in x["appended"]}
    assert by_title["의료 AI 해커톤"][4] == "2026-11-30"          # API의 recruitCloseAt(ms) → KST 날짜
    assert by_title["데이터 경진대회 (~12/31)"][4] == "2026-12-31"  # API 필드가 없으면 제목의 (~12/31)로 보완


def test_contest_test_mode_isolated(r):
    x = r["contest_test"]
    assert hooks(x) == {"https://hooks.test/TEST"}                                  # 테스트 웹훅으로만
    assert x["posts"] and all("[TEST]" in p["text"] for p in x["posts"])
    assert x["appended"] == [] and x["propSets"] == []                              # 시트·기록 변경 없음
    assert len(x["posts"]) == 2                                                     # 이미 보낸 ID여도 다시 보냄(중복 무시)


def test_contest_test_mode_without_test_webhook_sends_nothing(r):
    x = r["contest_test_no_webhook"]
    assert x["posts"] == [] and any("SLACK_WEBHOOK_URL_TEST" in l for l in x["logs"])


# ---------------------------------------------------------------- 뉴스
def test_news_normal_vs_test(r):
    n, t = r["news_normal"], r["news_test"]
    assert hooks(n) == {"https://hooks.test/PROD"} and len(n["posts"]) == 5 and len(n["appended"]) == 5
    assert "sentArticleIds" in n["propSets"]
    assert hooks(t) == {"https://hooks.test/TEST"} and len(t["posts"]) == 3        # 이미 보낸 기사여도 최신 3건
    assert all("[TEST]" in p["text"] for p in t["posts"]) and t["appended"] == [] and t["propSets"] == []


# ---------------------------------------------------------------- 코딩테스트
def test_programmers_weekday_rules_and_done_marking(r):
    assert r["prog_sat_normal"]["posts"] == []                                      # 토요일 정상 모드는 발송 안 함
    t = r["prog_sat_test"]                                                          # 테스트 모드는 요일 무시, 완료 표시 없음
    assert hooks(t) == {"https://hooks.test/TEST"} and len(t["posts"]) == 1 and t["setValues"] == []
    assert "[TEST]" in t["posts"][0]["text"] and "181937번" in t["posts"][0]["text"]
    n = r["prog_tue_normal"]                                                        # 화요일 정상 모드
    assert hooks(n) == {"https://hooks.test/PROD"} and n["setValues"] == [[3, 6, "완료"]]


def test_swea_weekday_rules(r):
    assert r["swea_tue_normal"]["posts"] == []                                      # SWEA는 월·목
    m = r["swea_mon_normal"]
    assert len(m["posts"]) == 1 and "contestProbId=AV5def" in m["posts"][0]["text"] and m["setValues"] == [[3, 6, "완료"]]
    t = r["swea_sat_test"]
    assert hooks(t) == {"https://hooks.test/TEST"} and t["setValues"] == []


# ---------------------------------------------------------------- 편집기에서 고르는 test… 함수
def test_test_functions_enable_test_mode_without_property(r):
    for key in ("contest_wrapper", "news_wrapper", "prog_wrapper_sat", "swea_wrapper_sat"):
        x = r[key]
        assert x["posts"], key
        assert hooks(x) == {"https://hooks.test/TEST"}, key                        # 운영 웹훅으로는 가지 않음
        assert x["appended"] == [] and x["setValues"] == [] and x["propSets"] == [], key   # 운영 데이터 변경 없음
        assert all("[TEST]" in p["text"] for p in x["posts"]), key


def test_test_function_missing_test_webhook_sends_nothing(r):
    # 운영 웹훅만 있고 테스트 웹훅이 없으면 운영 채널로 새어 나가지 않는다(prog_after_wrapper는 테스트 웹훅 없음)
    x = r["prog_after_wrapper_tue_normal"]
    assert x["posts"] == [] and any("SLACK_WEBHOOK_URL_TEST" in l for l in x["logs"])


# ---------------------------------------------------------------- 뉴스 트리거 설정 함수
def test_setup_news_triggers_replaces_only_own_clock_triggers(r):
    x = r["news_setup_triggers"]
    assert sorted(x["deleted"]) == ["fetchAITimesAndSendToSlack/CLOCK", "sendAiTimesNews/CLOCK"]     # 다른 함수·다른 유형은 그대로
    assert len(x["created"]) == 15 and {c["fn"] for c in x["created"]} == {"sendAiTimesNews"}
    assert {c["hour"] for c in x["created"]} == {9, 13, 18}
    assert {c["day"] for c in x["created"]} == {"MON", "TUE", "WED", "THU", "FRI"}                   # 평일만, 주말 없음
    assert len({(c["day"], c["hour"]) for c in x["created"]}) == 15                                   # 중복 없음
    assert any("15개 생성" in l for l in x["logs"])


# ---------------------------------------------------------------- 새 기사가 많을 때: 슬랙은 최신 10건, 나머지는 시트에만
def test_news_overflow_posts_newest_ten_and_records_rest_in_sheet(r):
    x = r["news_overflow"]
    posted = [p["text"] for p in x["posts"]]
    assert len(posted) == 10 and hooks(x) == {"https://hooks.test/PROD"}
    assert all(any(f"기사 {i}>" in t for t in posted) for i in range(1, 11))          # 최신 10건(기사 1~10)
    assert not any(f"기사 {i}>" in t for t in posted for i in (11, 12, 13, 14))          # 나머지는 슬랙에 없음
    titles = [row[1] for row in x["appended"]]
    assert len(titles) == 14 and set(titles) == {f"기사 {i}" for i in range(1, 15)}     # 시트에는 14건 모두
    assert titles[:4] == ["기사 14", "기사 13", "기사 12", "기사 11"]                    # 시트에만 기록한 것이 먼저(오래된 순)
    assert any("슬랙 10건, 시트에만 기록 4건" in l for l in x["logs"])


def test_news_overflow_not_reposted_next_run(r):
    x = r["news_overflow_second_run"]                                                   # 14건 모두 이미 기록된 상태
    assert x["posts"] == [] and x["appended"] == [] and any("새 기사 없음" in l for l in x["logs"])


def test_news_rows_have_only_three_columns_collected_time_basis(r):
    for key in ("news_normal", "news_overflow"):
        assert r[key]["appended"] and all(len(row) == 3 for row in r[key]["appended"]), key   # 수집시간, 제목, 주소만
