"""授業レポの class root に schedule.yaml を書く。"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from . import courserepo, gitops
from .cli import KNOWN_ERRORS, error, setup_console
from .config import data_dir
from .data import Course, YearData, load_year
from .schedule import build_dates, write_dates


class IssueError(RuntimeError):
    pass


def _issue_course(yd: YearData, course: Course, root: Path, ghq: Path, today: date, dry_run: bool) -> None:
    cal = yd.calendar_for(course)
    issued = f"{today.isoformat()} ({gitops.head_sha(root)})"
    repo = ghq / course.repo if course.repo else None
    croot = courserepo.class_root(repo, course.class_id) if repo else None
    dates = build_dates(course, cal, yd.events, yd.moves, issued,
                        course_id=courserepo.course_id(croot) if croot else None)
    issued_path = yd.dir / "issued" / f"{course.id}.yaml"

    if dry_run:
        print(f"== {course.id}")
        for e in dates.dates:
            print(f"  {e.n} " + ("cancelled" if e.cancelled else e.date.isoformat())
                  + (f"  {'、'.join(e.notes)}" if e.notes else ""))
        return

    if repo is None:
        print(f"{course.id}: no repo")
        return
    if not repo.is_dir():
        raise IssueError(f"授業レポが見つからない: {repo}")
    if croot is None:
        print(f"{course.id}: no class root")
        return
    # director は sessions.base の作業ツリーから日程を読む。別の枝には書かない
    base = courserepo.base_branch(courserepo.team(repo, croot)) or "main"
    if gitops.current_branch(repo) != base:
        print(f"{course.id}: not on {base}")
        return

    target = croot / "schedule.yaml"
    rel = target.relative_to(repo).as_posix()
    # 授業レポでは書くだけ。コミットは director がする
    if write_dates(target, dates):
        print(f"{course.id}: written {rel}")
    else:
        print(f"{course.id}: unchanged")

    write_dates(issued_path, dates)
    gitops.commit_paths(root, [issued_path.relative_to(root).as_posix()], f"issue: {course.id} の写し")
    if gitops.has_upstream(root) and gitops.is_ahead(root):
        gitops.push(root)


def main(argv: list[str] | None = None) -> int:
    setup_console()
    ap = argparse.ArgumentParser(prog="aidec issue", description="授業レポに schedule.yaml を書く")
    ap.add_argument("year", type=int)
    ap.add_argument("--course", action="append", help="配る授業の id。何度でも書ける。省くと全部")
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    ap.add_argument("--dry-run", action="store_true", help="何も書かず、作るものを表示する")
    ap.add_argument("--root", type=Path, default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    try:
        args.root = args.root or data_dir()
        # もう一方の機械で出した控えを先に取り込む。dry-run では手元を変えない
        if not args.dry_run and gitops.has_upstream(args.root):
            gitops.pull_ff_only(args.root)
        yd = load_year(args.root / str(args.year))
        ghq = gitops.ghq_root()
    except KNOWN_ERRORS as e:
        error(str(e))
        return 1
    ids = {c.id for c in yd.courses}
    unknown = [c for c in (args.course or []) if c not in ids]
    if unknown:
        error(f"courses.yaml に無い授業: {', '.join(unknown)}")
        return 1
    courses = [c for c in yd.courses if not args.course or c.id in args.course]

    failed = False
    for course in courses:
        try:
            _issue_course(yd, course, args.root, ghq, args.today, args.dry_run)
        except (IssueError, *KNOWN_ERRORS) as e:
            error(f"{course.id}: {e}")
            failed = True
    return 1 if failed else 0
