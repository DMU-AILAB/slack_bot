

def test_sql_problem_detected_by_database_category():
    """분류값이 'database'이고 SELECT가 본문에 없어도 SQL로 인식한다 (프로그래머스 131112 구조)."""
    from src.coding.problems import parse_programmers
    html = ('<html><title>코딩테스트 연습 - 공장 | 프로그래머스</title>'
            '<div data-challenge-info="{&quot;challenge_category&quot;:&quot;database&quot;}"></div>'
            '<div class="guide-section-description"><div class="markdown"><p>FOOD_FACTORY 테이블입니다.</p>'
            '<table><thead><tr><th>Column name</th><th>Type</th></tr></thead>'
            '<tbody><tr><td>FACTORY_ID</td><td>VARCHAR(10)</td></tr></tbody></table></div></div></html>')
    assert parse_programmers(html)[4] == "sql"
