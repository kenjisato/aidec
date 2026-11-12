import os
import subprocess

import pytest

from conftest import run_git, write
from aidec import issue


def course_repo(ghq, name):
    return ghq / "github.com" / "example" / name


def run_issue(workdesk_root, *args):
    return issue.main(["2027", "--root", str(workdesk_root), *args])


def test_first_issue(workdesk_root, ghq):
    repo = course_repo(ghq, "macro-mon")
    write(repo / "notes.md", "未コミットのメモ\n")
    assert run_issue(workdesk_root, "--course", "macro-mon", "--today", "2027-09-01") == 0

    text = (repo / "2027" / "schedule.yaml").read_text(encoding="utf-8")
    sha = run_git(workdesk_root, "rev-parse", "--short", "HEAD^").strip()
    assert f"issued: 2027-09-01 (workdesk {sha})" in text
    # 授業レポでは schedule.yaml だけをコミットし、push している
    assert run_git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["2027/schedule.yaml"]
    assert "?? notes.md" in run_git(repo, "status", "--porcelain")
    assert run_git(repo, "rev-parse", "HEAD") == run_git(repo, "rev-parse", "origin/main")
    # 控えを workdesk でコミットしている
    files = run_git(workdesk_root, "show", "--name-only", "--format=", "HEAD").split()
    assert files == ["2027/issued/macro-mon.yaml"]


def test_all_courses_by_default(workdesk_root, ghq):
    assert run_issue(workdesk_root, "--today", "2027-09-01") == 0
    for name in ("macro-mon", "seminar-wed"):
        assert (course_repo(ghq, name) / "2027" / "schedule.yaml").exists()


def test_second_issue_with_nothing_new(workdesk_root, ghq):
    run_issue(workdesk_root, "--course", "macro-mon", "--today", "2027-09-01")
    repo = course_repo(ghq, "macro-mon")
    before = run_git(repo, "rev-parse", "HEAD")
    assert run_issue(workdesk_root, "--course", "macro-mon", "--today", "2027-09-02") == 0
    assert run_git(repo, "rev-parse", "HEAD") == before              # issued だけのコミットを作らない


def test_keeps_changes_written_by_course(workdesk_root, ghq):
    run_issue(workdesk_root, "--course", "macro-mon", "--today", "2027-09-01")
    repo = course_repo(ghq, "macro-mon")
    p = repo / "2027" / "schedule.yaml"
    mine = "changes:\n  - {n: 4, mode: zoom, reason: 出張}   # 学生に連絡済み\n"
    write(p, p.read_text(encoding="utf-8").replace("changes: []\n", mine))
    run_git(repo, "commit", "-q", "-am", "第 4 回は Zoom")
    with open(workdesk_root / "2027" / "events.yaml", "a", encoding="utf-8", newline="\n") as f:
        f.write("- {date: 2027-12-06, kind: side_job, title: 集中講義}\n")
    run_git(workdesk_root, "commit", "-q", "-am", "予定を足す")
    assert run_issue(workdesk_root, "--course", "macro-mon", "--today", "2027-09-10") == 0
    after = p.read_text(encoding="utf-8")
    assert after.endswith(mine)
    assert "facts: [集中講義（12/6）]" in after


def test_issues_even_when_changes_are_broken(workdesk_root, ghq):
    run_issue(workdesk_root, "--course", "macro-mon", "--today", "2027-09-01")
    repo = course_repo(ghq, "macro-mon")
    p = repo / "2027" / "schedule.yaml"
    write(p, p.read_text(encoding="utf-8").replace("changes: []\n", "changes:\n  - {n: 4, makup: x}\n"))
    run_git(repo, "commit", "-q", "-am", "書き間違い")
    with open(workdesk_root / "2027" / "events.yaml", "a", encoding="utf-8", newline="\n") as f:
        f.write("- {date: 2027-12-06, kind: side_job, title: 集中講義}\n")
    run_git(workdesk_root, "commit", "-q", "-am", "予定を足す")
    assert run_issue(workdesk_root, "--course", "macro-mon", "--today", "2027-09-10") == 0
    assert "facts: [集中講義（12/6）]" in p.read_text(encoding="utf-8")


def test_stops_when_course_repo_has_other_unpushed_commits(workdesk_root, ghq, capsys):
    repo = course_repo(ghq, "macro-mon")
    write(repo / "notes.md", "まだ送っていない仕事\n")
    run_git(repo, "add", "notes.md")
    run_git(repo, "commit", "-q", "-m", "未送信の仕事")
    remote_before = run_git(repo, "rev-parse", "origin/main")
    assert run_issue(workdesk_root, "--course", "macro-mon", "--today", "2027-09-01") == 1
    assert not (repo / "2027" / "schedule.yaml").exists()
    assert run_git(repo, "rev-parse", "origin/main") == remote_before
    assert "push していないコミット" in capsys.readouterr().err


def test_stops_on_uncommitted_schedule(workdesk_root, ghq, capsys):
    run_issue(workdesk_root, "--course", "macro-mon", "--today", "2027-09-01")
    p = course_repo(ghq, "macro-mon") / "2027" / "schedule.yaml"
    write(p, p.read_text(encoding="utf-8") + "# 書きかけ\n")
    assert run_issue(workdesk_root, "--today", "2027-09-02") == 1
    assert p.read_text(encoding="utf-8").endswith("# 書きかけ\n")
    err = capsys.readouterr().err
    assert "macro-mon" in err and "未コミットの変更" in err
    # 他の授業は続ける
    assert (course_repo(ghq, "seminar-wed") / "2027" / "schedule.yaml").exists()


def test_dry_run_writes_nothing(workdesk_root, ghq, capsys):
    assert run_issue(workdesk_root, "--dry-run", "--today", "2027-09-01") == 0
    assert not (course_repo(ghq, "macro-mon") / "2027").exists()
    out = capsys.readouterr().out
    assert "macro-mon" in out and "第 4 回 10/18" in out and "学会（○○）" in out


def test_missing_course_repo_is_reported(workdesk_root, ghq, capsys):
    repo = course_repo(ghq, "seminar-wed")
    repo.rename(repo.with_name("moved"))                              # Windows では .git を消しにくいので移す
    assert run_issue(workdesk_root, "--today", "2027-09-01") == 1
    assert "seminar-wed" in capsys.readouterr().err


def test_unknown_course_id(workdesk_root, ghq, capsys):
    assert run_issue(workdesk_root, "--course", "nope", "--today", "2027-09-01") == 1
    assert "nope" in capsys.readouterr().err


@pytest.fixture
def workdesk_with_remote(workdesk_root, tmp_path):
    remote = tmp_path / "remotes" / "workdesk.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    run_git(workdesk_root, "remote", "add", "origin", str(remote))
    run_git(workdesk_root, "push", "-q", "-u", "origin", "main")
    return workdesk_root


def fail_push(repo):
    """pre-push hook で push を必ず失敗させる。"""
    hook = repo / ".git" / "hooks" / "pre-push"
    write(hook, "#!/bin/sh" + chr(10) + "exit 1" + chr(10))
    os.chmod(hook, 0o755)
    return hook


def test_course_push_failure_is_retried(workdesk_root, ghq):
    repo = course_repo(ghq, "macro-mon")
    hook = fail_push(repo)
    assert run_issue(workdesk_root, "--course", "macro-mon", "--today", "2027-09-01") == 1
    hook.unlink()
    assert run_issue(workdesk_root, "--course", "macro-mon", "--today", "2027-09-01") == 0
    assert run_git(repo, "rev-parse", "HEAD") == run_git(repo, "rev-parse", "origin/main")


def test_workdesk_push_failure_is_retried(workdesk_with_remote, ghq):
    root = workdesk_with_remote
    hook = fail_push(root)
    assert run_issue(root, "--course", "macro-mon", "--today", "2027-09-01") == 1
    hook.unlink()
    assert run_issue(root, "--course", "macro-mon", "--today", "2027-09-01") == 0
    assert run_git(root, "rev-parse", "HEAD") == run_git(root, "rev-parse", "@{u}")


def test_pulls_workdesk_before_issuing(workdesk_with_remote, ghq, tmp_path):
    a = workdesk_with_remote
    b = tmp_path / "workdesk-b"                                     # もう一方の機械
    run_git(tmp_path, "clone", "-q", str(tmp_path / "remotes" / "workdesk.git"), str(b))
    assert issue.main(["2027", "--root", str(b), "--course", "macro-mon", "--today", "2027-09-01"]) == 0
    assert run_issue(a, "--course", "macro-mon", "--today", "2027-09-01") == 0
    assert run_git(a, "rev-parse", "HEAD") == run_git(a, "rev-parse", "@{u}")
