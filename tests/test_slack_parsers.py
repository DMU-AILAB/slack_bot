from datetime import date

from src.sources import slack_history as sh


def test_geeknews_title_topic_id_utm_and_truncation(slack_msgs):
    a = sh.parse_news_message(slack_msgs["geeknews"])
    assert a.source_name == "GeekNews" and a.title == "새로운 LLM 추론 서버 공개"
    assert a.url == "https://news.hada.io/topic?id=37140" and a.topic_id == "37140"
    assert a.truncated and "처리량" in a.summary


def test_aitimes_from_blocks(slack_msgs):
    a = sh.parse_news_message(slack_msgs["aitimes"])
    assert a.source_name == "AI TIMES" and a.url.endswith("idxno=203456")
    assert a.summary.startswith("오픈AI가") and a.truncated


def test_other_and_system_messages_ignored(slack_msgs):
    assert sh.parse_news_message(slack_msgs["other"]) is None
    assert sh.parse_notice(sh.message_text(slack_msgs["exhausted"])) is None


def test_notice_from_blocks_when_text_empty(slack_msgs):
    n = sh.parse_notice(sh.message_text(slack_msgs["programmers"]))
    assert (n.platform, n.problem_id, n.title, n.level) == ("programmers", "181936", "공배수", "0")
    assert n.participants == 55278 and n.rate == 89.0 and n.sent_date == date(2026, 11, 13) and n.count == 56
    s = sh.parse_notice(sh.message_text(slack_msgs["swea"]))
    assert s.platform == "swea" and s.problem_id == "6329" and s.sent_date == date(2026, 11, 12)


def test_contest_message_button_url_and_poster(slack_msgs):
    c = sh.parse_contest_message(slack_msgs["contest"])
    assert c["url"] == "https://linkareer.com/activity/365981" and c["poster"].endswith("993668")
    assert c["title"] == "2026 포항 MICE 창업 해커톤"
