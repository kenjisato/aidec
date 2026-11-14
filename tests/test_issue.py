import os
import subprocess

import pytest

from conftest import COURSES_2027, run_git, write
from aidec import issue

CLASSES = {"macro-mon": ("macro-2027", "2027-mon3"), "seminar-wed": ("seminar-2027", "2027-wed2")}


def course_repo(ghq, name):
    return ghq / "github.com" / "example" / name


def run_issue(workdesk_root, *args):
    return issue.main(["2027", "--root", str(workdesk_root), *args])


@pytest.fixture(autouse=True)
def classes(workdesk_root, ghq):
    """courses.yaml に class: を付け、授業レポに classes/<id>/ を置く（コミット済み）。"""
    text = COURSES_2027
    for name, (_, cls) in CLASSES.items():
        text = text.replace(f"  repo: github.com/example/{name}\n", f"  repo: github.com/example/{name}\n  class: {cls}\n")
    write(workdesk_root / "2027" / "courses.yaml", text)
    run_git(workdesk_root, "commit", "-q", "-am", "class を付ける")
    for name, (cid, cls) in CLASSES.items():
        repo = course_repo(ghq, name)
        write(repo / "course.yaml", f"id: {cid}\ntitle: t\n")
        write(repo / "classes" / cls / "class.yaml",
              f"classes:\n  - id: {cls}\n    destinations: [{{to: manual}}]\n")
        run_git(repo, "add", "-A")
        run_git(repo, "commit", "-q", "-m", "classes/")
        run_git(repo, "push", "-q")


def sched(ghq, name):
    return course_repo(ghq, name) / "classes" / CLASSES[name][1] / "schedule.yaml"


def test_first_issue(workdesk_root, ghq, capsys):
    repo = course_repo(ghq, "macro-mon")
    before = run_git(repo, "rev-parse", "HEAD")
    assert run_issue(workdesk_root, "--course", "macro-mon", "--today", "2027-09-01") == 0

    text = sched(ghq, "macro-mon").read_text(encoding="utf-8")
    sha = run_git(workdesk_root, "rev-parse", "--short", "HEAD^").strip()
    assert f"issued: 2027-09-01 ({sha})" in text
    assert "course: macro-2027" in text and "class: 2027-mon3" in text
    assert "workdesk" not in text and "aidec" not in text
    # 授業レポではコミットも push もしない。作業ツリーに書くだけ
    assert run_git(repo, "rev-parse", "HEAD") == before
    assert run_git(repo, "rev-parse", "origin/main") == before
    assert "?? classes/2027-mon3/schedule.yaml" in run_git(repo, "status", "--porcelain")
    assert "macro-mon: written classes/2027-mon3/schedule.yaml" in capsys.readouterr().out
    # 控えを workdesk でコミットしている
    files = run_git(workdesk_root, "show", "--name-only", "--format=", "HEAD").split()
    assert files == ["2027/issued/macro-mon.yaml"]


def test_all_courses_by_default(workdesk_root, ghq):
    assert run_issue(workdesk_root, "--today", "2027-09-01") == 0
    for name in CLASSES:
        assert sched(ghq, name).exists()


def test_second_issue_with_nothing_new(workdesk_root, ghq, capsys):
    run_issue(workdesk_root, "--course", "macro-mon", "--today", "2027-09-01")
    p = sched(ghq, "macro-mon")
    first = p.read_text(encoding="utf-8")
    capsys.readouterr()
    assert run_issue(workdesk_root, "--course", "macro-mon", "--today", "2027-09-02") == 0
    assert p.read_text(encoding="utf-8") == first                  # issued も書き換えない
    assert capsys.readouterr().out.strip() == "macro-mon: unchanged"


def test_overwrites_uncommitted_schedule(workdesk_root, ghq):
    run_issue(workdesk_root, "--course", "macro-mon", "--today", "2027-09-01")
    with open(workdesk_root / "2027" / "events.yaml", "a", encoding="utf-8", newline="\n") as f:
        f.write("- {date: 2027-12-06, kind: side_job, title: 集中講義}\n")
    run_git(workdesk_root, "commit", "-q", "-am", "予定を足す")
    # 前に書いたものを director がまだコミットしていなくても止めない
    assert run_issue(workdesk_root, "--course", "macro-mon", "--today", "2027-09-10") == 0
    assert "集中講義" in sched(ghq, "macro-mon").read_text(encoding="utf-8")


def test_skips_unreadable_schedule(workdesk_root, ghq, capsys):
    old = "course: macro-mon\nplan: [old format]\n"
    path = sched(ghq, "macro-mon")
    path.write_bytes(old.encode("utf-8"))
    head = run_git(workdesk_root, "rev-parse", "HEAD")
    assert run_issue(workdesk_root, "--today", "2027-09-01") == 0
    assert path.read_bytes() == old.encode("utf-8")
    out = capsys.readouterr().out
    assert "macro-mon: unreadable schedule.yaml" in out
    assert "seminar-wed: written" in out                     # 他の授業は続ける
    assert not (workdesk_root / "2027" / "issued" / "macro-mon.yaml").exists()
    assert run_git(workdesk_root, "rev-parse", "HEAD") != head   # seminar-wed の控え


def test_wrong_branch_writes_nothing(workdesk_root, ghq, capsys):
    run_git(course_repo(ghq, "macro-mon"), "checkout", "-q", "-b", "work")
    assert run_issue(workdesk_root, "--today", "2027-09-01") == 0
    assert not sched(ghq, "macro-mon").exists()
    assert sched(ghq, "seminar-wed").exists()
    assert "macro-mon: not on main" in capsys.readouterr().out


def test_base_branch_from_team_yaml(workdesk_root, ghq, capsys):
    repo = course_repo(ghq, "macro-mon")
    write(repo / "team.yaml", "sessions:\n  base: develop\n")
    assert run_issue(workdesk_root, "--course", "macro-mon", "--today", "2027-09-01") == 0
    assert "macro-mon: not on develop" in capsys.readouterr().out
    run_git(repo, "checkout", "-q", "-b", "develop")
    assert run_issue(workdesk_root, "--course", "macro-mon", "--today", "2027-09-01") == 0
    assert sched(ghq, "macro-mon").exists()


def test_skips_course_without_class_root(workdesk_root, ghq, capsys):
    repo = course_repo(ghq, "macro-mon")
    old = repo / "2027" / "schedule.yaml"
    write(old, "course: macro-mon\n")
    run_git(repo, "rm", "-q", "-r", "classes")
    assert run_issue(workdesk_root, "--today", "2027-09-01") == 0
    assert "macro-mon: no class root" in capsys.readouterr().out
    assert old.read_text(encoding="utf-8") == "course: macro-mon\n"   # 旧いものには触らない
    assert not (workdesk_root / "2027" / "issued" / "macro-mon.yaml").exists()
    assert sched(ghq, "seminar-wed").exists()                         # ほかの授業は配る


def test_dry_run_writes_nothing(workdesk_root, ghq, capsys):
    assert run_issue(workdesk_root, "--dry-run", "--today", "2027-09-01") == 0
    assert not sched(ghq, "macro-mon").exists()
    assert not (workdesk_root / "2027" / "issued").exists()
    out = capsys.readouterr().out
    assert "macro-mon" in out and "2027-10-18" in out and "学会（○○）" in out


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
