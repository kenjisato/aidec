import json
import subprocess
import time
from datetime import datetime, timezone

import pytest

from conftest import make_repo, run_git, write
from aidec import supervisor

NOW = datetime(2027, 11, 5, 9, 30, tzinfo=timezone.utc)


@pytest.fixture
def desk(tmp_path, git_env, year_dir, ghq, monkeypatch):
    """リモート付きのデータのレポ、授業レポの中身、設定ファイル。"""
    root = make_repo(year_dir.parent, tmp_path / "remotes" / "desk.git")
    cfg = write(tmp_path / "config.yaml", f"data_dir: {root}\n")
    monkeypatch.setenv("AIDEC_CONFIG", str(cfg))
    mon = ghq / "github.com" / "example" / "macro-mon" / "2027"
    write(mon / "05" / "session.yaml", "session:\n  title: 財政政策と乗数効果\n")
    write(mon / "course-map.md", "- 第 5 回 財政政策\n")
    return root


def req(**kw):
    return {"protocol": 1, "verb": "raise", "course": "macro-mon", "root": "/x", "text": "補講日がほしい", **kw}


def test_raise_commits_only_the_inbox_file(desk):
    res = supervisor.handle(req(session=5), desk, NOW)
    assert res["status"] == "accepted" and res["protocol"] == 1
    ref = res["ref"]
    assert (desk / "inbox" / f"{ref}.md").is_file()
    assert run_git(desk, "show", "--name-only", "--format=", "HEAD").split() == [f"inbox/{ref}.md"]


def test_raise_without_reply_is_accepted(desk):
    res = supervisor.handle(req(no_reply=True), desk, NOW)
    assert res["status"] == "accepted" and res["ref"]


def test_ask_hits_title_and_map(desk, ghq):
    res = supervisor.handle(req(verb="ask", text="乗数効果"), desk, NOW)
    assert res["status"] == "answered"
    assert "macro-mon" in res["answer"] and "第 5 回" in res["answer"]
    assert str(ghq / "github.com/example/macro-mon/2027/05/session.yaml") in res["answer"]


def test_ask_without_hit_lists_course_maps(desk, ghq):
    res = supervisor.handle(req(verb="ask", text="ゲーム理論"), desk, NOW)
    assert res["status"] == "answered"
    assert str(ghq / "github.com/example/macro-mon/2027/course-map.md") in res["answer"]


@pytest.mark.parametrize("bad", [
    {"protocol": 2}, {"verb": "x"}, {"text": ""}, {"course": None}])
def test_bad_requests_are_declined(desk, bad):
    assert supervisor.handle(req(**bad), desk, NOW) == {"protocol": 1, "status": "declined"}


def _run(stdin, env_extra, timeout):
    import os
    return subprocess.run(["uv", "run", "aidec", "supervise"], input=stdin, capture_output=True,
                          text=True, encoding="utf-8", timeout=timeout, env={**os.environ, **env_extra})


def test_main_declines_garbage_with_exit_0(desk):
    p = _run("not json", {}, 30)
    assert p.returncode == 0 and json.loads(p.stdout) == {"protocol": 1, "status": "declined"}


def test_main_without_config_exits_1_with_empty_stdout(tmp_path):
    p = _run("{}", {"AIDEC_CONFIG": str(tmp_path / "none.yaml")}, 30)
    assert p.returncode == 1 and p.stdout == "" and "none.yaml" in p.stderr


def test_main_returns_quickly_even_if_remote_is_unreachable(desk):
    run_git(desk, "remote", "set-url", "origin", "https://127.0.0.1:9/none.git")
    t = time.monotonic()
    p = _run(json.dumps(req()), {}, 30)
    assert p.returncode == 0 and json.loads(p.stdout)["status"] == "accepted"
    assert time.monotonic() - t < 5
