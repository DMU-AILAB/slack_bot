from src import router


def test_explicit_channel_forms():
    assert router.parse("#2-공모전 이번 주 마감").channel == "contest"
    assert router.parse("<#C123ABC|인공지능-소식> 이슈 3가지").channel == "news"
    assert router.parse("#코딩테스트 오늘 문제").question == "오늘 문제"


def test_unsupported_channel():
    p = router.parse("#general 공지 알려줘")
    assert p.channel is None and p.unsupported == "general"


def test_keyword_inference_single_channel():
    assert router.parse("의학 데이터분석 공모전 나가고 싶은데 모집중인 것 있어?").channel == "contest"
    assert router.parse("RAG 관련 최근 소식").channel == "news"
    assert router.parse("181936번 풀이").channel == "coding"
    assert router.parse("답은 말고 힌트만 줘").channel == "coding"


def test_ambiguous_asks_back():
    p = router.parse("오늘 올라온 거 알려줘")
    assert p.channel is None and len(p.candidates) == 3
    p2 = router.parse("공모전 소식 알려줘")   # 공모전 + 소식
    assert p2.channel is None and set(p2.candidates) == {"contest", "news"}


def test_choice_from_reply():
    assert router.choice_from_reply("3", []) == "coding"
    assert router.choice_from_reply("공모전", []) == "contest"
    assert router.choice_from_reply("#인공지능-소식", []) == "news"
    assert router.choice_from_reply("글쎄", []) is None
