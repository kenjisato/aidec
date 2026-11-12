"""授業からの報告を見直す。ぶつかりが無ければ依頼を閉じ、報告を inbox/done/ に移し、changes を控える。"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from . import gitops
from .check import Problem, course_problems
from .cli import KNOWN_ERRORS, error, setup_console
from .config import data_dir
from .data import load_year
from .reports import Report, load_reports
from .requests import load_requests, parse_request, set_status
from .schedule import write_reviewed

# 授業の changes が原因のぶつかり。これがあれば閉じない
BLOCKING = {"bad_schedule", "not_issued", "closed_day", "not_class_day", "prep_timing"}


def load_request(path: Path):
    return parse_request(path.read_text(encoding="utf-8"), path.name)


def blocking(problems: list[Problem], dates: list[date]) -> list[Problem]:
    """閉じるのを止めるもの。決まっていない回は、この報告（依頼）の日のものだけを見る。"""
    return [p for p in problems if not p.soft and
            (p.kind in BLOCKING or (p.kind == "undecided" and p.date in dates))]


def main(argv: list[str] | None = None) -> int:
    setup_console()
    ap = argparse.ArgumentParser(prog="review", description="授業からの報告を見直す")
    ap.add_argument("year", type=int)
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    ap.add_argument("--dry-run", action="store_true", help="何も書かず、どうするかを表示する")
    ap.add_argument("--root", type=Path, default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    try:
        root = args.root or data_dir()
        if not args.dry_run and gitops.has_upstream(root):
            gitops.pull_ff_only(root)
        yd = load_year(root / str(args.year))
        ghq = gitops.ghq_root()
        reports = load_reports(root / "inbox")
        requests = {r.id: r for r in load_requests(root / "requests")}
    except KNOWN_ERRORS as e:
        error(str(e))
        return 1
    if not reports:
        print("未処理の報告は無い")
        return _push_if_ahead(root, args.dry_run)

    courses = {c.id: c for c in yd.courses}
    pulled: set[str] = set()
    paths: list[str] = []
    failed = False
    for rep in reports:
        try:
            done = _review_one(rep, courses, requests, yd, root, ghq, args, pulled)
        except KNOWN_ERRORS as e:
            error(f"{rep.id}: {e}")
            failed = True
            continue
        if done is None:
            failed = True
        else:
            paths += done
    if paths and not args.dry_run:
        try:
            gitops.commit_paths(root, paths, f"review: {len([p for p in paths if '/done/' in p])} 件の報告を見直す")
        except KNOWN_ERRORS as e:
            _restore(root, paths)
            error(f"見直しをコミットできなかったので、書き換えを戻した。workdesk の手元を確かめる（{e}）")
            return 1
    if _push_if_ahead(root, args.dry_run):
        return 1
    return 1 if failed else 0


def _restore(root: Path, paths: list[str]) -> None:
    """コミットできなかった見直しを、HEAD の状態に戻す。"""
    for rel in paths:
        tracked = gitops.git(root, "ls-tree", "--name-only", "HEAD", "--", rel).strip()   # HEAD にあるか
        if tracked:
            gitops.git(root, "restore", "--staged", "--worktree", "--source=HEAD", "--", rel)
        else:
            gitops.git(root, "reset", "-q", "--", rel)
            (root / rel).unlink(missing_ok=True)


def _push_if_ahead(root: Path, dry_run: bool) -> int:
    """前の回に送り損ねたものも含めて push する。"""
    if dry_run:
        return 0
    try:
        if gitops.has_upstream(root) and gitops.is_ahead(root):
            gitops.push(root)
    except KNOWN_ERRORS as e:
        error(f"workdesk を push できなかった。次の review でもう一度送る（{e}）")
        return 1
    return 0


def _review_one(rep: Report, courses, requests, yd, root: Path, ghq: Path, args, pulled: set[str]) -> list[str] | None:
    """見直して閉じたら、変えたファイル（root からの相対パス）を返す。閉じなければ None。"""
    course = courses.get(rep.frm)
    if course is None or course.repo is None:
        error(f"{rep.id}: {rep.frm} は courses.yaml に無い（または授業レポが無い）。報告はそのまま残す")
        return None
    req = None
    if rep.re is not None:
        req = requests.get(rep.re)
        if req is None:
            error(f"{rep.id}: 返事の先の依頼 {rep.re} が見つからない。報告はそのまま残す")
            return None
    repo = ghq / course.repo
    if not args.dry_run and course.id not in pulled and gitops.has_upstream(repo):
        gitops.pull_ff_only(repo)                      # 授業レポの今の版で見る
        pulled.add(course.id)
    problems, changes = course_problems(yd, course, ghq, pending=True)
    stop = blocking(problems, req.dates if req else rep.dates)
    if stop or changes is None:
        print(f"{rep.id}（{rep.frm}）: ぶつかりがあるので閉じない")
        for p in stop or problems:
            print("  " + p.line())
        return None
    req_path = root / "requests" / f"{req.id}.md" if req else None
    # 同じ依頼への二つ目の報告（他の機械から）なら、依頼はもう閉じている
    to_close = req_path is not None and load_request(req_path).status != "closed"
    what = f"依頼 {req.id} を閉じ" if to_close else "changes を控え"
    if args.dry_run:
        print(f"{rep.id}（{rep.frm}）: ぶつかりは無い。{what}る（dry-run）")
        return []
    sha = gitops.head_sha(repo)                        # 失敗しうるものを先に済ませ、そのあとで書き換える
    out = []
    if to_close:
        set_status(req_path, ("open", "reported"), "closed")
        out.append(f"requests/{req.id}.md")
    reviewed = yd.dir / "reviewed" / f"{course.id}.yaml"
    write_reviewed(reviewed, course.id, changes, sha, args.today)
    out.append(reviewed.relative_to(root).as_posix())
    src = root / "inbox" / f"{rep.id}.md"
    dst = root / "inbox" / "done" / f"{rep.id}.md"
    dst.parent.mkdir(exist_ok=True)
    src.rename(dst)
    out += [f"inbox/{rep.id}.md", f"inbox/done/{rep.id}.md"]
    print(f"{rep.id}（{rep.frm}）: ぶつかりは無い。{what}た")
    return out
