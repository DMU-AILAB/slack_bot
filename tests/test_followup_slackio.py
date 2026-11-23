from src import followup, slack_io

LAST = [{"id": "1", "title": "포항 MICE 해커톤", "url": "u1"}, {"id": "2", "title": "의료 AI 대회", "url": "u2"}]


def test_contest_followup_by_ordinal():
    ch, q = followup.resolve("두 번째 공고 시상 내역 알려줘", "contest", LAST)
    assert ch == "contest" and q.startswith("의료 AI 대회") and "시상" in q
    assert followup.resolve("첫 번째 공고 자격", "contest", LAST)[1].startswith("포항 MICE 해커톤")
    assert followup.resolve("다섯 번째 공고", "contest", LAST) is None      # 범위 밖
    assert followup.resolve("두 번째 공고", None, LAST) is None             # 이전 결과 없음


def test_coding_followup_that_problem():
    last = [{"id": "181936", "platform": "programmers", "title": "공배수", "url": "u"}]
    ch, q = followup.resolve("그 문제 힌트만 줘", "coding", last)
    assert ch == "coding" and "181936번" in q and "힌트" in q


def test_split_message_keeps_code_fences_balanced():
    text = "머리\n\n" + "```python\n" + "\n".join(f"x{i} = {i}" for i in range(400)) + "\n```\n\n끝"
    parts = slack_io.split_message(text, 500)
    assert len(parts) > 1 and all(len(p) <= 520 for p in parts)
    assert all(p.count("```") % 2 == 0 for p in parts)


def test_short_message_not_split():
    assert slack_io.split_message("안녕", 3500) == ["안녕"]
