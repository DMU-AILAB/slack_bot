from datetime import date

from src.news.window import parse_window

MON, TUE, WED, SUN = date(2026, 11, 23), date(2026, 11, 24), date(2026, 11, 25), date(2026, 11, 29)


def test_this_week_widens_to_last_7_days_early_in_week():
    s, e, label = parse_window("이번 주 가장 중요한 이슈", MON)
    assert (e - s).days == 6 and e == MON and "7일" in label
    s, e, _ = parse_window("이번주 소식", TUE)
    assert (e - s).days == 6


def test_this_week_is_monday_to_today_from_wednesday():
    s, e, label = parse_window("이번 주 이슈", WED)
    assert s == MON and e == WED and label == "이번 주"
    assert parse_window("이번 주 이슈", SUN)[0] == MON


def test_other_windows_unchanged():
    assert parse_window("오늘 소식", MON)[:2] == (MON, MON)
    assert parse_window("최근 3일", WED)[0] == date(2026, 11, 23)
