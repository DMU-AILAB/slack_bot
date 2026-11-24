

def test_block_pattern_ignores_otp_flag_false_and_catches_real_signals():
    from src.coding.swea_client import _BLOCK_PAT
    assert not _BLOCK_PAT.search("<script>var getOtpFlag = false;</script>")
    assert _BLOCK_PAT.search("<script>var getOtpFlag = true;</script>")
    assert _BLOCK_PAT.search('<div class="g-recaptcha"></div>')
    assert _BLOCK_PAT.search("보안문자를 입력해 주세요")


def _fake_session(monkeypatch, payload):
    from src.coding import swea_client as sc

    class Resp:
        text = "<html></html>"
        def json(self): return payload

    class Sess:
        headers = {}
        def get(self, *a, **k): return Resp()
        def post(self, *a, **k): return Resp()
    monkeypatch.setattr(sc.requests, "Session", lambda: Sess())
    monkeypatch.setattr(sc.config, "env", lambda k, *a, **kw: "x")
    monkeypatch.setattr(sc, "_login_failure", None)
    return sc


def test_login_success(monkeypatch):
    sc = _fake_session(monkeypatch, {"success": True, "message": "", "returnPath": "/x"})
    assert sc._login() is not None


def test_login_mfa_is_blocked_not_bypassed(monkeypatch):
    import pytest
    sc = _fake_session(monkeypatch, {"success": True, "message": "mfa", "returnPath": "/x"})
    with pytest.raises(sc.LoginBlocked, match="추가 인증"):
        sc._login()


def test_wrong_password_is_not_retried(monkeypatch):
    """비밀번호 오류는 한 번만 시도한다(5회 실패 시 계정 잠금)."""
    import pytest
    sc = _fake_session(monkeypatch, {"success": False, "message": "LoginIdPwdFail"})
    with pytest.raises(sc.LoginBlocked):
        sc._login()
    calls = []
    monkeypatch.setattr(sc.requests, "Session", lambda: calls.append(1))
    with pytest.raises(sc.LoginBlocked, match="SWEA_PW"):
        sc._login()
    assert calls == []
    monkeypatch.setattr(sc, "_login_failure", None)


def test_parse_problem_real_structure():
    from src.coding.swea_client import parse_problem
    html = """<div class="box3"><ul><li><span>시간</span><span>: 30초</span></li></ul></div>
    <div class="box4"><p class="txt">10개의 수를 입력 받아 홀수만 더하라.<br /><br /><strong>[입력]</strong><br />T가 주어진다.</p></div>
    <div class="box_type1"><div class="left"><div class="box5"><span class="title1">입력</span>
      3<br />3 17 1&nbsp;&nbsp;<br />&nbsp;<div class="down_area"><a>input.txt</a></div></div></div>
    <div class="right"><div class="box5"><span class="title1">출력</span>#1 200<br />#2 208<br />&nbsp;
      <div class="down_area"><a>output.txt</a></div></div></div></div>"""
    text, ex = parse_problem(html)
    assert "홀수만 더하라" in text and "[입력]" in text and "30초" in text
    assert ex == [{"input": "3\n3 17 1", "expected": "#1 200\n#2 208"}]
