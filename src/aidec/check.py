"""機械で判定できるぶつかりを出す。"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from classdays.calendar import WEEKDAYS, Calendar

from . import gitops
from .cli import KNOWN_ERRORS, error, setup_console
from .config import data_dir
from .data import Course, YearData, load_year
from .reports import load_reports
from .requests import Request, load_requests
from .schedule import (Change, ScheduleError, WorkdeskPart, build_part, effective_sessions, load_schedule,
                       read_reviewed)


@dataclass(frozen=True)
class Problem:
    course: str | None
    kind: str
    date: date | None
    message: str
    soft: bool = False          # 知らせるだけで、失敗にはしない

    def line(self) -> str:
        note = "（注意）" if self.soft else ""
        return f"[{self.kind}] {note}{self.course or '-'}: {self.message}"


def _md(d: date) -> str:
    return f"{d.month}/{d.day}"


def _is_class_or_makeup_day(cal: Calendar, d: date) -> bool:
    if d in cal.makeup_days:
        return True
    return cal.term_of(d) is not None and cal.weekday_of(d) in WEEKDAYS[:5]


def check_course(course_id: str, cal: Calendar, computed: WorkdeskPart, current: WorkdeskPart,
                 changes: list[Change]) -> list[Problem]:
    out = []
    if not computed.same_content(current):
        out.append(Problem(course_id, "stale", None, "配った schedule.yaml が今の学事暦・予定と違う。issue を走らせる"))
    decided = {c.n for c in changes}
    for e in computed.plan:
        if e.facts and e.n not in decided:
            out.append(Problem(course_id, "undecided", e.date,
                               f"第 {e.n} 回（{_md(e.date)}）: {'、'.join(e.facts)} への対応が changes に無い"))
    planned = {e.n: e.date for e in computed.plan}
    for c in changes:
        held = c.makeup if c.cancel else planned.get(c.n)
        if held is not None and c.release is not None and c.release > held:
            out.append(Problem(course_id, "prep_timing", c.release,
                               f"第 {c.n} 回の公開日 {_md(c.release)} が授業日 {_md(held)} より後"))
        if held is not None and c.prep_from is not None and c.prep_from >= held:
            out.append(Problem(course_id, "prep_timing", c.prep_from,
                               f"第 {c.n} 回の準備を始める日 {_md(c.prep_from)} が授業日 {_md(held)} より前でない"))
        if c.makeup is None:
            continue
        if cal.is_closed(c.makeup):
            out.append(Problem(course_id, "closed_day", c.makeup,
                               f"第 {c.n} 回の補講日 {_md(c.makeup)} は休講日・試験期間に当たる"))
        elif not _is_class_or_makeup_day(cal, c.makeup):
            out.append(Problem(course_id, "not_class_day", c.makeup,
                               f"第 {c.n} 回の補講日 {_md(c.makeup)} は授業日でも補講日でもない"))
    return out


def check_calendar(cal: Calendar) -> list[Problem]:
    """学事暦の補講日が、決まった曜日（makeup_weekday）に当たっているか。"""
    if cal.makeup_weekday is None:
        return []
    return [Problem(None, "makeup_weekday", d,
                    f"calendar-{cal.university}.yaml の補講日 {_md(d)}（{WEEKDAYS[d.weekday()]}）"
                    f"が {cal.makeup_weekday} でない")
            for d in cal.makeup_days if WEEKDAYS[d.weekday()] != cal.makeup_weekday]


def check_research_days(course_id: str, prep_on: tuple[str, ...], changes: list[Change],
                        research_days: tuple[str, ...]) -> list[Problem]:
    """研究日はなるべく空けておきたい曜日なので、当たっていても soft で知らせるだけにする。"""
    out = []
    hit = [d for d in prep_on if d in research_days]
    if hit:
        out.append(Problem(course_id, "research_day", None,
                           f"準備の曜日（prep_on）に研究日 {', '.join(hit)} が入っている", soft=True))
    for c in changes:
        if c.makeup is not None and WEEKDAYS[c.makeup.weekday()] in research_days:
            out.append(Problem(course_id, "research_day", c.makeup,
                               f"第 {c.n} 回の補講日 {_md(c.makeup)} は研究日に当たる", soft=True))
    return out


def check_reported(course_id: str, changes: list[Change], reviewed: list[Change] | None,
                   pending: bool) -> list[Problem]:
    """見直した控えと今の changes が違うのに、その授業からの報告が無いもの。"""
    before = {c.n: c for c in (reviewed or [])}
    now = {c.n: c for c in changes}
    diff = sorted(n for n in before.keys() | now.keys() if before.get(n) != now.get(n))
    which = "・".join(f"第 {n} 回" for n in diff)
    if pending:
        return [Problem(course_id, "unreviewed", None,
                        f"報告が届いている{f'（{which} の変更）' if diff else ''}。workdesk-review で見直す", soft=True)]
    if not diff:
        return []
    return [Problem(course_id, "unreported", None,
                    f"{which} の changes が見直した版と違うのに、報告が無い。授業レポで workdesk-report を使う")]


def check_requests(reqs: list[Request], today: date) -> list[Problem]:
    return [Problem(r.to, "overdue", r.decide_by, f"依頼 {r.id} の期限 {_md(r.decide_by)} を過ぎた")
            for r in reqs if r.status == "open" and r.decide_by < today]


def course_problems(yd: YearData, course: Course, ghq: Path, pending: bool) -> tuple[list[Problem], list[Change] | None]:
    """一つの授業のぶつかりと、読めたなら今の changes。"""
    cal = yd.calendar_for(course)
    path = ghq / course.repo / str(yd.year) / "schedule.yaml"
    if not path.exists():
        return [Problem(course.id, "not_issued", None, f"{path} がまだ無い")], None
    try:
        current, changes = load_schedule(path)
        effective_sessions(current.plan, changes)
    except ScheduleError as e:
        return [Problem(course.id, "bad_schedule", None, str(e))], None
    computed = build_part(course, cal, yd.events, current.issued)
    out = check_course(course.id, cal, computed, current, changes)
    out += check_research_days(course.id, course.prep_on, changes, yd.research_days)
    try:
        reviewed = read_reviewed(yd.dir / "reviewed" / f"{course.id}.yaml")
    except ScheduleError as e:
        return out + [Problem(course.id, "bad_schedule", None, str(e))], changes
    return out + check_reported(course.id, changes, reviewed, pending), changes


def run_check(root: Path, year: int, ghq: Path, today: date) -> list[Problem]:
    yd = load_year(root / str(year))
    out: list[Problem] = []
    pending = {r.frm for r in load_reports(root / "inbox")}
    for cal in yd.calendars.values():
        out += check_calendar(cal)
    for course in yd.courses:
        if course.repo is not None:
            out += course_problems(yd, course, ghq, course.id in pending)[0]
    out += check_requests(load_requests(root / "requests"), today)
    return out


def main(argv: list[str] | None = None) -> int:
    setup_console()
    ap = argparse.ArgumentParser(prog="check", description="機械で判定できるぶつかりを出す")
    ap.add_argument("year", type=int)
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    ap.add_argument("--root", type=Path, default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    try:
        args.root = args.root or data_dir()
        problems = run_check(args.root, args.year, gitops.ghq_root(), args.today)
    except KNOWN_ERRORS as e:
        error(str(e))
        return 1
    for p in sorted(problems, key=lambda p: (p.course or "", p.date or date.min, p.kind)):
        print(p.line())
    if not any(not p.soft for p in problems):
        print("ぶつかりは無い")
    return 1 if any(not p.soft for p in problems) else 0
