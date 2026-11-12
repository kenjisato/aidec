"""git と ghq を呼ぶ。"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        raise GitError(f"git {' '.join(args)} が失敗した（{repo}）: {p.stderr.strip()}")
    return p.stdout


def head_sha(repo: Path) -> str:
    return git(repo, "rev-parse", "--short", "HEAD").strip()


def has_upstream(repo: Path) -> bool:
    try:
        git(repo, "rev-parse", "--abbrev-ref", "@{u}")
        return True
    except GitError:
        return False


def is_ahead(repo: Path) -> bool:
    """upstream にまだ push していないコミットがあるか。"""
    return int(git(repo, "rev-list", "--count", "@{u}..HEAD").strip()) > 0


def unpushed_files(repo: Path) -> set[str]:
    """upstream にまだ push していないコミットが触れたファイル。"""
    out = git(repo, "log", "@{u}..HEAD", "--name-only", "--format=")
    return {line.strip() for line in out.splitlines() if line.strip()}


def pull_ff_only(repo: Path) -> None:
    git(repo, "pull", "--ff-only", "-q")


def is_dirty(repo: Path, rel: str) -> bool:
    """rel に未コミットの変更があるか（追跡されていないファイルも含む）。"""
    return bool(git(repo, "status", "--porcelain", "--", rel).strip())


def commit_paths(repo: Path, rels: list[str], message: str) -> bool:
    """rels だけをコミットする。変更が無ければ何もせず False を返す。"""
    git(repo, "add", "--", *rels)
    if not git(repo, "diff", "--cached", "--name-only", "--", *rels).strip():
        return False
    git(repo, "commit", "-q", "-m", message, "--", *rels)
    return True


def push(repo: Path) -> None:
    git(repo, "push", "-q")


def ghq_root() -> Path:
    env = os.environ.get("WORKDESK_GHQ_ROOT")
    if env:
        return Path(env)
    p = subprocess.run(["ghq", "root"], capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0 or not p.stdout.strip():
        raise GitError(f"ghq root が失敗した: {p.stderr.strip()}")
    return Path(p.stdout.strip())
