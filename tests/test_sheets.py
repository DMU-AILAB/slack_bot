from datetime import date

from src.sources import sheets

CONTEST = """수집시간,공모전 제목,주소,시작일,마감일
2026-03-27 11:09,"의료 AI 해커톤 (~11/30)",https://linkareer.com/activity/365981,,
2026-11-10 12:40,데이터 분석 대회,https://linkareer.com/activity/111,2026-11-01,2026-12-05
2026-11-10 12:41,주소 없음,,,
"""
NEWS = """수집시간,기사 제목,주소
2026-03-29 4:08,오픈AI 발표,https://www.aitimes.kr/news/articleView.html?idxno=1
2026-10-30 9:00,구글 발표,https://www.aitimes.com/news/articleView.html?idxno=2
"""
CODING = """문제번호,제목,티어,참여 인원,정답률,완료여부,해시코드
181936,공배수,Lv. 0,"55,278",91%,완료,
6329,연습 문제,D2,1204,70.21%,,AV5abc
"""


def test_contest_rows_header_mapping_and_deadline_fallback():
    rows = sheets.parse_contest_rows(sheets.parse_csv_text(CONTEST))
    assert len(rows) == 2                                  # 주소 없는 행은 건너뜀
    assert rows[0].deadline == date(2026, 11, 30) and rows[0].deadline_source == "title"
    assert rows[0].start is None
    assert rows[1].deadline == date(2026, 12, 5) and rows[1].deadline_source == "sheet"
    assert rows[0].activity_id == "365981"


def test_news_rows_source_names():
    rows = sheets.parse_news_rows(sheets.parse_csv_text(NEWS))
    assert [r.source_name for r in rows] == ["인공지능신문", "AI TIMES"]
    assert rows[0].collected_at.hour == 4 and rows[0].collected_at.minute == 8


def test_coding_rows():
    rows = sheets.parse_coding_rows(sheets.parse_csv_text(CODING), "programmers")
    assert rows[0].participants == 55278 and rows[0].rate == 91.0 and rows[0].done
    assert rows[0].url.endswith("/lessons/181936")
    swea = sheets.parse_coding_rows(sheets.parse_csv_text(CODING), "swea")[1]
    assert swea.rate == 70.21 and not swea.done and "contestProbId=AV5abc" in swea.url
