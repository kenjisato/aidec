import json
import subprocess
import time
from datetime import datetime, timezone

import pytest

from conftest import add_class, make_repo, run_git, write
from aidec import supervisor

NOW = datetime(2027, 11, 5, 9, 30, tzinfo=timezone.utc)


@pytest.fixture
def desk(tmp_path, git_env, year_dir, ghq, monkeypatch):
    """リモート付きのデータのレポ、授業レポの中身、設定ファイル。"""
    mon = add_class(year_dir, ghq, "macro-mon")          # 新しい置き方: classes/2027-mon3/
    root = make_repo(year_dir.parent, tmp_path / "remotes" / "desk.git")
    cfg = write(tmp_path / "config.yaml", f"data_dir: {root}\n")
    monkeypatch.setenv("AIDEC_CONFIG", str(cfg))
    monkeypatch.setattr(supervisor, "_detached_push", lambda repo: None)
    write(mon / "05" / "session.yaml", "session:\n  title: 財政政策と乗数効果\n")
    write(mon / "course-map.md", "- 第 5 回 財政政策\n")
    return root


MON = "github.com/example/macro-mon/classes/2027-mon3"


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
    assert str(ghq / MON / "05/session.yaml") in res["answer"]


def test_ask_without_hit_lists_course_maps(desk, ghq):
    res = supervisor.handle(req(verb="ask", text="ゲーム理論"), desk, NOW)
    assert res["status"] == "answered"
    assert str(ghq / MON / "course-map.md") in res["answer"]


def test_ask_reads_packet_yaml(desk, ghq):
    write(ghq / MON / "packet.yaml", "sessions: {dir: 's{nn}', map: plan/map.md}\n")
    write(ghq / MON / "s07" / "session.yaml", "session:\n  title: 景気循環\n")
    write(ghq / MON / "plan" / "map.md", "- 第 8 回 物価\n")
    answer = supervisor.handle(req(verb="ask", text="景気循環と物価"), desk, NOW)["answer"]
    assert str(ghq / MON / "s07/session.yaml") in answer
    assert str(ghq / MON / "plan/map.md") in answer


def test_ask_reads_course_root_team_yaml(desk, ghq):
    write(ghq / "github.com/example/macro-mon/team.yaml", "sessions: {dir: 's{nn}'}\n")   # packet.yaml が無い
    write(ghq / MON / "s07" / "session.yaml", "session:\n  title: 景気循環\n")
    answer = supervisor.handle(req(verb="ask", text="景気循環"), desk, NOW)["answer"]
    assert str(ghq / MON / "s07/session.yaml") in answer


def test_ask_reads_a_repo_not_moved_to_classes(desk, ghq):
    sem = ghq / "github.com" / "example" / "seminar-wed" / "2027"
    write(sem / "03" / "session.yaml", "session:\n  title: 計量の演習\n")
    res = supervisor.handle(req(verb="ask", text="計量"), desk, NOW)
    assert str(sem / "03" / "session.yaml") in res["answer"]


def test_ask_with_a_clone_but_no_map_says_so(desk, ghq):
    mon = ghq / MON
    (mon / "course-map.md").unlink()
    (mon / "05" / "session.yaml").unlink()
    res = supervisor.handle(req(verb="ask", text="ゲーム理論"), desk, NOW)
    assert "今の枝" in res["answer"] and "レポが無い" not in res["answer"]


@pytest.mark.parametrize("bad", [
    {"protocol": 2}, {"verb": "x"}, {"text": ""}, {"text": " \n"}, {"course": None},
    {"course": "../x"}, {"course": "a b"}, {"class": "../A"}])
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


def test_ask_with_a_japanese_sentence(desk):
    res = supervisor.handle(req(verb="ask", text="乗数効果を扱った回は？"), desk, NOW)
    assert "財政政策と乗数効果" in res["answer"]


def test_ask_skips_unknown_placeholder_in_team_yaml(desk, ghq):
    write(ghq / MON / "packet.yaml", "sessions: {dir: '{zz}'}\n")
    res = supervisor.handle(req(verb="ask", text="乗数効果"), desk, NOW)
    assert res["status"] == "answered"


def test_failed_commit_leaves_nothing_behind(desk):
    hook = desk / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    with pytest.raises(Exception):
        supervisor.handle(req(), desk, NOW)
    assert not list((desk / "inbox").glob("*.md"))
    assert run_git(desk, "status", "--porcelain") == ""


def test_main_failed_commit_exits_1(desk, capsys, monkeypatch):
    hook = desk / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(req())))
    assert supervisor.main([]) == 1
    assert capsys.readouterr().out == ""
