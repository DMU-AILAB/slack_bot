"""--test 옵션: .env/환경변수의 운영 설정을 덮어쓰고, 옵션이 없으면 아무것도 바꾸지 않는다."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CODE = r"""
import json, sys
argv = sys.argv[1:]
from src import testmode
applied = testmode.apply(argv)
from src import config
print(json.dumps({"applied": applied, "argv": argv, "channels": config.CHANNEL_NAMES,
                  "data": config.DATA_DIR.name, "banner": testmode.banner() if applied else ""}))
"""


def run(args, env_extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CHANNEL_NAME", "BOT_DATA", "TEST_CHANNEL"))}
    env.update(env_extra or {})
    p = subprocess.run([sys.executable, "-c", CODE, *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])


def test_without_flag_nothing_changes():
    r = run(["--channel", "news"])
    assert r["applied"] is False and r["argv"] == ["--channel", "news"]
    assert r["channels"] == {"contest": "2-공모전", "news": "인공지능-소식", "coding": "2026-코딩테스트"} and r["data"] == "data"


def test_flag_switches_channels_and_data_dir_and_is_removed_from_argv():
    r = run(["--test", "--channel", "news"])
    assert r["applied"] and r["argv"] == ["--channel", "news"]            # 다른 인자는 그대로 argparse에 전달됨
    assert set(r["channels"].values()) == {"봇-테스트"} and r["data"] == "data-test"
    assert "봇-테스트" in r["banner"] and "data-test" in r["banner"]


def test_flag_beats_per_channel_overrides_from_environment():
    r = run(["--test"], {"CHANNEL_NAME_NEWS": "운영-뉴스", "CHANNEL_NAME_ALL": "다른채널", "BOT_DATA_DIR": "data"})
    assert set(r["channels"].values()) == {"봇-테스트"} and r["data"] == "data-test"


def test_custom_test_channel_name():
    r = run(["--test"], {"TEST_CHANNEL_NAME": "내-테스트"})
    assert set(r["channels"].values()) == {"내-테스트"}
