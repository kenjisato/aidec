"""授業レポに schedule.yaml を配る。"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

from . import gitops
from .cli import KNOWN_ERRORS, error, setup_console
from .config import data_dir
from .data import Course, YearData, load_year
from .requests import Request, next_request_id, write_request
from .schedule import PlanEntry, WorkdeskPart, build_part, read_part, write_issued_copy, write_part


class IssueError(RuntimeError):
    pass


def new_facts(prev: WorkdeskPart | None, cur: WorkdeskPart, today: date) -> list[tuple[PlanEntry, list[str]]]:
    """前に配った版に無かった事実を、今日以降の回について集める。"""
    old = {e.n: set(e.facts) for e in prev.plan} if prev else {}
    out = []
    for e in cur.plan:
        added = [f for f in e.facts if f not in old.get(e.n, set())]
        if e.date >= today and added:
            out.append((e, added))
    return out


def _md(d: date) -> str:
    return f"{d.month}/{d.day}"


def _request_body(fresh: list[tuple[PlanEntry, list[str]]]) -> str:
    lines = [f"- {_md(e.date)}（第 {e.n} 回）: {'、'.join(added)}" for e, added in fresh]
    return ("次の回に事実が加わった。対応を決めて schedule.yaml の changes に書き、報告してほしい。\n\n"
            + "\n".join(lines) + "\n")


def _issue_course(yd: YearData, course: Course, root: Path, ghq: Path, today: date,
                  decide_days: int, dry_run: bool) -> None:
    cal = yd.calendar_for(course)
    part = build_part(course, cal, yd.events, f"{today.isoformat()} (workdesk {gitops.head_sha(root)})")
    issued_path = yd.dir / "issued" / f"{course.id}.yaml"
    prev = read_part(issued_path) if issued_path.exists() else None
    fresh = new_facts(prev, part, today)

    if dry_run:
        print(f"== {course.id}（{course.term} {course.slot.weekday}-{course.slot.period}、{len(part.plan)} 回）")
        for e in part.plan:
            print(f"  第 {e.n} 回 {_md(e.date)}" + (f"  {'、'.join(e.facts)}" if e.facts else ""))
        for e, added in fresh:
            print(f"  依頼にする: 第 {e.n} 回 {_md(e.date)} {'、'.join(added)}")
        return

    if course.repo is None:
        print(f"{course.id}: 授業レポが無いので配らない")
        return
    repo = ghq / course.repo
    if not repo.is_dir():
        raise IssueError(f"授業レポが見つからない: {repo}")
    rel = f"{yd.year}/schedule.yaml"
    if gitops.is_dirty(repo, rel):
        raise IssueError(f"{rel} に未コミットの変更がある。先にコミットするか戻す")
    upstream = gitops.has_upstream(repo)
    if upstream:
        gitops.pull_ff_only(repo)
        # 授業レポの未送信の仕事を一緒に push しない。schedule.yaml だけのもの（前回の送り損ねなど）は送ってよい
        others = sorted(gitops.unpushed_files(repo) - {rel})
        if others:
            raise IssueError(f"授業レポに push していないコミットがある（{', '.join(others[:5])}"
                             f"{' ほか' if len(others) > 5 else ''}）。先に送るか確かめてから配る")

    target = repo / rel
    current = read_part(target) if target.exists() else None      # changes が壊れていても配れるよう、上半分だけを読む
    if current is not None and current.same_content(part):
        print(f"{course.id}: 配った版から変わりなし")
        part = WorkdeskPart(part.course, current.issued, part.plan, part.makeup_days)
    else:
        write_part(target, part)
        gitops.commit_paths(repo, [rel], f"workdesk: {rel} を配る ({part.issued})")
        print(f"{course.id}: {rel} を配った")
    # 前の回に push が失敗したコミットも、ここで送る
    if upstream and gitops.is_ahead(repo):
        gitops.push(repo)

    write_issued_copy(issued_path, part)
    paths = [issued_path.relative_to(root).as_posix()]
    if fresh:
        req = Request(
            id=next_request_id(root / "requests", today, course.id),
            to=course.id,
            issued=today,
            decide_by=max(today, min(e.date for e, _ in fresh) - timedelta(days=decide_days)),
            status="open",
            dates=[e.date for e, _ in fresh],
            body=_request_body(fresh),
        )
        paths.append(write_request(root / "requests", req).relative_to(root).as_posix())
        print(f"{course.id}: 依頼 {req.id} を出した（期限 {req.decide_by.isoformat()}）")
    gitops.commit_paths(root, paths, f"issue: {course.id} に {rel} を配る")
    if gitops.has_upstream(root) and gitops.is_ahead(root):
        gitops.push(root)


def main(argv: list[str] | None = None) -> int:
    setup_console()
    ap = argparse.ArgumentParser(prog="issue", description="授業レポに schedule.yaml を配る")
    ap.add_argument("year", type=int)
    ap.add_argument("--course", action="append", help="配る授業の id。何度でも書ける。省くと全部")
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    ap.add_argument("--decide-days", type=int, default=7, help="依頼の期限を授業日の何日前にするか")
    ap.add_argument("--dry-run", action="store_true", help="何も書かず、作るものを表示する")
    ap.add_argument("--root", type=Path, default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    try:
        args.root = args.root or data_dir()
        # もう一方の機械で出した控えと依頼を先に取り込む。dry-run では手元を変えない
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
            _issue_course(yd, course, args.root, ghq, args.today, args.decide_days, args.dry_run)
        except (IssueError, *KNOWN_ERRORS) as e:
            error(f"{course.id}: {e}")
            failed = True
    return 1 if failed else 0
