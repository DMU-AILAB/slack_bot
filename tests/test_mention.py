import app


def test_strip_mention_basic():
    assert app.strip_mention("<@U0ABC123> 현재 모집 중인 공모전 알려줘") == "현재 모집 중인 공모전 알려줘"


def test_strip_mention_middle_and_label():
    assert app.strip_mention("안녕 <@U0ABC123|inso_bot>   이번 주 뉴스") == "안녕 이번 주 뉴스"


def test_strip_mention_only_mention_is_empty():
    assert app.strip_mention("<@U0ABC123>") == ""
