from datetime import date, datetime

from src.common.text import KST, date_int, norm_text, norm_url, parse_date, parse_dt, title_deadline, week_bounds


def test_norm_text_removes_zero_width_and_spaces():
    assert norm_text("AI​ 공모전​  안내 ") == "AI 공모전 안내"


def test_norm_url_unescape_utm_and_keep_idxno():
    u = "https://News.Hada.io/topic?id=37140&amp;utm_source=slack&amp;utm_medium=bot#x"
    assert norm_url(u) == "https://news.hada.io/topic?id=37140"
    assert norm_url("https://www.aitimes.kr/news/articleView.html?idxno=77&utm_campaign=a/") == \
        "https://www.aitimes.kr/news/articleView.html?idxno=77"


def test_title_deadline_same_year_and_next_year():
    assert title_deadline("해커톤 (~3/30)", datetime(2026, 3, 27, tzinfo=KST)) == date(2026, 3, 30)
    assert title_deadline("공모전 (~1/10)", datetime(2026, 12, 20, tzinfo=KST)) == date(2027, 1, 10)
    assert title_deadline("마감 표기 없음", datetime(2026, 3, 27, tzinfo=KST)) is None


def test_parse_dt_single_digit_hour_and_dates():
    assert parse_dt("2026-03-29 4:08") == datetime(2026, 3, 29, 4, 8, tzinfo=KST)
    assert parse_date("2026. 11. 20") == date(2026, 11, 20)
    assert parse_date("") is None
    assert date_int(date(2026, 11, 20)) == 20261120 and date_int(None) == 0


def test_week_bounds():
    assert week_bounds(date(2026, 11, 21)) == (date(2026, 11, 16), date(2026, 11, 22))
