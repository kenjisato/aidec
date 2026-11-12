import pytest

from conftest import make_repo, run_git, write
from aidec import gitops


def test_commit_only_given_paths(tmp_path, git_env):
    repo = make_repo(tmp_path / "r")
    write(repo / "a.txt", "a\n")
    write(repo / "b.txt", "b\n")
    run_git(repo, "add", "b.txt")
    assert gitops.commit_paths(repo, ["a.txt"], "add a")
    assert run_git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["a.txt"]
    assert "A  b.txt" in run_git(repo, "status", "--porcelain")      # b は stage されたまま
    assert not gitops.commit_paths(repo, ["a.txt"], "nothing")       # 変更が無ければ False


def test_is_dirty(tmp_path, git_env):
    repo = make_repo(tmp_path / "r")
    write(repo / "2027" / "schedule.yaml", "x\n")
    assert gitops.is_dirty(repo, "2027/schedule.yaml")               # 追跡されていない
    gitops.commit_paths(repo, ["2027/schedule.yaml"], "add")
    assert not gitops.is_dirty(repo, "2027/schedule.yaml")
    write(repo / "2027" / "schedule.yaml", "y\n")
    assert gitops.is_dirty(repo, "2027/schedule.yaml")


def test_upstream_pull_push(tmp_path, git_env):
    remote = tmp_path / "remote.git"
    a = make_repo(tmp_path / "a", remote)
    assert gitops.has_upstream(a)
    assert not gitops.has_upstream(make_repo(tmp_path / "solo"))
    run_git(tmp_path, "clone", "-q", str(remote), "b")
    b = tmp_path / "b"
    write(b / "x.txt", "x\n")
    gitops.commit_paths(b, ["x.txt"], "x")
    gitops.push(b)
    gitops.pull_ff_only(a)
    assert (a / "x.txt").exists()
    assert gitops.head_sha(a) == gitops.head_sha(b)


def test_pull_that_cannot_fast_forward_fails(tmp_path, git_env):
    remote = tmp_path / "remote.git"
    a = make_repo(tmp_path / "a", remote)
    run_git(tmp_path, "clone", "-q", str(remote), "b")
    b = tmp_path / "b"
    write(b / "x.txt", "from b\n"); gitops.commit_paths(b, ["x.txt"], "b"); gitops.push(b)
    write(a / "y.txt", "from a\n"); gitops.commit_paths(a, ["y.txt"], "a")
    with pytest.raises(gitops.GitError, match="pull --ff-only"):
        gitops.pull_ff_only(a)


def test_ghq_root_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AIDEC_GHQ_ROOT", str(tmp_path))
    assert gitops.ghq_root() == tmp_path


def test_is_ahead(tmp_path, git_env):
    a = make_repo(tmp_path / "a", tmp_path / "remote.git")
    assert not gitops.is_ahead(a)
    write(a / "x.txt", "x" + chr(10))
    gitops.commit_paths(a, ["x.txt"], "x")
    assert gitops.is_ahead(a)
    gitops.push(a)
    assert not gitops.is_ahead(a)
