from datetime import date

from src.contest import query as cq
from src.sources import web

TODAY = date(2026, 11, 21)  # 토요일


def test_intents():
    assert cq.analyze("이번 주에 마감되는 공모전 알려줘", TODAY).intent == "deadline_soon"
    assert cq.analyze("이번 주에 마감되는 공모전 알려줘", TODAY).until == date(2026, 11, 22)
    assert cq.analyze("3일 이내 마감 공모전", TODAY).window_days == 3
    assert cq.analyze("이번 주에 새로 올라온 공모전은?", TODAY).intent == "new"
    assert cq.analyze("AI 공모전 대상 수상작들의 특징을 분석해줘", TODAY).intent == "winners"
    q = cq.analyze("의학 데이터분석 공모전에 나가고 싶은데, 지금 모집 중인 게 있어?", TODAY)
    assert q.intent == "search" and "의학" in q.topic and "공모전" not in q.topic
    assert cq.analyze("지난 마감된 공모전 보여줘", TODAY).include_closed


def test_aspect_detection():
    assert cq.detect_aspect("OO 공모전 시상 내역 알려줘") == "prize"
    assert cq.detect_aspect("대학생 개인 참가 자격") == "eligibility"
    assert cq.detect_aspect("의료 AI 공모전 있어?") == "any"


def test_find_title_requires_real_overlap():
    titles = {"1": "2026 포항 MICE 창업 해커톤", "2": "의료 데이터 분석 경진대회"}
    assert cq.find_title("포항 MICE 창업 해커톤 시상 내역 알려줘", titles) == "1"
    assert cq.find_title("대학생 개인으로 참가할 수 있는 AI 공모전 있어?", titles) is None
    assert cq.find_title("의료 데이터 분석 경진대회 참가 자격", titles) == "2"


def test_linkareer_detail_parser(fixtures):
    d = web.parse_linkareer_detail((fixtures / "linkareer_detail.html").read_text(encoding="utf-8"), "365981")
    assert d["host"] == "포항시" and d["start"] == "2026-11-20" and d["deadline"] == "2026-11-30"
    assert "총상금" in d["sections"]["prize"] and "누구나" in d["sections"]["eligibility"]
    assert web.parse_linkareer_detail("<html></html>", "1") is None


def test_split_sections_headings():
    text = "공모 개요입니다\n■ 참가 대상\n- 대학생\n■ 시상 내역\n- 대상 100만원\n■ 심사 기준\n- 창의성"
    s = web.split_sections(text)
    assert "대학생" in s["eligibility"] and "100만원" in s["prize"] and "창의성" in s["criteria"]


def test_ssrf_guard():
    assert not web.is_safe_url("http://localhost:8080/x")
    assert not web.is_safe_url("http://127.0.0.1/")
    assert not web.is_safe_url("http://192.168.0.10/")
    assert not web.is_safe_url("file:///etc/passwd")
