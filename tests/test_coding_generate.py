

def test_module_list_only_shown_after_blocked_import():
    from src.coding import generate as G
    from src.coding.problems import Problem
    p = Problem(platform="programmers", problem_id="1", title="t", url="u", statement="s", params=["a"], kind="function")
    assert "사용할 수 있는 모듈" not in G._rules(p)
    assert "사용할 수 있는 모듈" in G._rules(p, show_modules=True)
