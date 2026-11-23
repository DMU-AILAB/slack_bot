from src.contest import winners as w


def test_verify_entries_drops_hallucinated_evidence():
    page = "올해 대상은 팀 알파의 '폐암 조기진단 AI'가 차지했다. 우수상은 팀 베타."
    entries = [
        {"award": "대상", "work": "폐암 조기진단 AI", "evidence": "대상은 팀 알파의 '폐암 조기진단 AI'가 차지했다"},
        {"award": "대상", "work": "지어낸 작품", "evidence": "이 문장은 본문에 존재하지 않는다 정말로"},
        {"award": "우수상", "work": "", "evidence": "우수상은 팀 베타."},
        {"award": "x", "work": "짧음", "evidence": "대상"},
    ]
    kept = w.verify_entries(entries, page)
    assert [e["work"] for e in kept] == ["폐암 조기진단 AI"]


def test_parse_features_needs_two_valid_refs_and_counts_in_code():
    text = "1. 의료 영상 분야 비중이 높다 [1][3]\n- 사용 기술이 다양하다 [2]\n- 근거 번호가 범위 밖이다 [9][10]\n• 대부분 팀 프로젝트다 [1][2][3]"
    feats = w.parse_features(text, 3)
    assert [r for _, r in feats] == [[1, 3], [1, 2, 3]]


def test_enough_and_research_rules():
    e = lambda u: {"work": "a", "url": u}
    assert not w.enough({"entries": [e("u1")]})
    assert not w.enough({"entries": [e("u1"), e("u1")]})          # 출처가 하나뿐
    assert w.enough({"entries": [e("u1"), e("u2")]})
    assert w.can_research({"queries": ["a", "b", "c"], "search_round": 1})
    assert not w.can_research({"queries": ["a", "b", "c"], "search_round": 2})
    assert not w.can_research({"queries": ["a", "b", "c"], "search_round": 1, "unavailable": True})


def test_compose_insufficient_and_unavailable():
    s = {"topic": "AI", "entries": [], "pages": [{"url": "https://x.kr/a", "title": "후기"}], "queries": ["q"]}
    assert "충분히 찾지 못했습니다" in w.compose(s)
    assert w.compose({"topic": "AI", "unavailable": True, "entries": []}) == w.UNAVAILABLE_MSG


def test_compose_full_answer_with_codes_counts():
    es = [{"award": "대상", "work": "알파", "summary": "폐암 진단", "tech": "", "evidence": "e", "url": "https://a.kr", "title": "t"},
          {"award": "우수상", "work": "베타", "summary": "당뇨 예측", "tech": "", "evidence": "e", "url": "https://b.kr", "title": "t"}]
    s = {"topic": "의료", "entries": es, "pages": [{}, {}], "features": [("의료 분야 중심", [1, 2])]}
    out = w.compose(s)
    assert "사례 2/2건" in out and "<https://a.kr|출처>" in out
    es[0]["urls"] = ["https://a.kr", "https://c.kr"]          # 여러 출처는 번호를 붙여 모두 보여 준다
    assert "<https://c.kr|출처2>" in w.compose({**s, "entries": es}) and "정확하지 않을 수" in out


def test_topic_of_strips_generic_words():
    assert w.topic_of("AI 공모전 대상 수상작들의 특징을 분석해줘") == "AI"


def test_regex_entries_and_template_echo_rejected():
    page = "올해 대상은 팀 알파의 '폐암 조기진단 AI'가 차지했다. 우수상은 베타팀의 “당뇨 예측 모델”이다."
    es = w.regex_entries(page)
    assert [(e["award"], e["work"]) for e in es] == [("대상", "폐암 조기진단 AI"), ("우수상", "당뇨 예측 모델")]
    assert len(w.verify_entries(es, page)) == 2
    # 모델이 스키마 설명을 그대로 베낀 출력은 근거 검증에서 걸러진다
    echo = [{"award": "대상 등 등급", "work": "작품 또는 팀 이름", "evidence": "자료에서 그대로 옮긴 40자 이내 문장"}]
    assert w.verify_entries(echo, page) == []


def test_same_work_in_two_pages_merges_sources(monkeypatch):
    monkeypatch.setattr(w.llm, "generate_json", lambda *a, **k: None)      # 모델은 못 뽑고 정규식만 동작
    pg = lambda u, t: {"url": u, "title": "t", "text": t, "focus": t}
    s = {"pages": [pg("https://a.kr", "올해 대상은 팀 알파의 '폐암 조기진단 AI'가 차지했다."),
                   pg("https://b.kr", "우수상은 팀 알파의 '폐암 조기진단 AI'에게 돌아갔고 최우수상은 팀 델타의 '응급실 혼잡도 예측'이었다.")]}
    out = w.step_extract(s)
    works = {e["work"]: e["urls"] for e in out["entries"]}
    assert works["폐암 조기진단 AI"] == ["https://a.kr", "https://b.kr"] and "응급실 혼잡도 예측" in works
    assert w.enough(out)
