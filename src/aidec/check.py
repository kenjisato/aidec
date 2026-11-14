"""機械で判定できるぶつかりを出す。"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from classdays.calendar import WEEKDAYS, Calendar

from . import courserepo, gitops
from .cli import KNOWN_ERRORS, error, setup_console
from .config import data_dir
from .data import Course, YearData, load_year
from .schedule import Dates, ScheduleError, build_dates, read_changes, read_dates, sessions


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


def _undecided(course_id: str, computed: Dates, decided: set[int]) -> list[Problem]:
    """計算した日に事実（出張・休講など）がある回で、decided（moves・changes に書いた回）に無いもの。"""
    return [Problem(course_id, "undecided", e.date,
                    f"第 {e.n} 回（{_md(e.date)}）: {'、'.join(e.notes)} への対応が無い")
            for e in computed.dates if e.notes and e.n not in decided]


def check_course(course_id: str, cal: Calendar, computed: Dates, expected: Dates, current: Dates,
                 decided: set[int]) -> list[Problem]:
    """(1) 配った日付が今の学事暦・moves から作り直したものと違う。
    (2) 移した日が授業日でも補講日でもない。計算した日の事実は undecided が受け持つ。
    decided は moves か schedule-changes.yaml に書かれた回。事実のある回で、そのどちらにも無いものを出す。
    """
    out = []
    if not expected.same_content(current):
        out.append(Problem(course_id, "stale", None, "配った schedule.yaml が今の学事暦・moves・予定と違う。issue を走らせる"))
    out += _undecided(course_id, computed, decided)
    planned = {e.n: e.date for e in computed.dates}
    for e in current.dates:
        if e.date is None or e.date == planned.get(e.n):
            continue
        if cal.is_closed(e.date):
            out.append(Problem(course_id, "closed_day", e.date,
                               f"第 {e.n} 回の日 {_md(e.date)} は休講日・試験期間に当たる"))
        elif not _is_class_or_makeup_day(cal, e.date):
            out.append(Problem(course_id, "not_class_day", e.date,
                               f"第 {e.n} 回の日 {_md(e.date)} は授業日でも補講日でもない"))
    return out


def check_calendar(cal: Calendar) -> list[Problem]:
    """学事暦の補講日が、決まった曜日（makeup_weekday）に当たっているか。"""
    if cal.makeup_weekday is None:
        return []
    return [Problem(None, "makeup_weekday", d,
                    f"calendar-{cal.university}.yaml の補講日 {_md(d)}（{WEEKDAYS[d.weekday()]}）"
                    f"が {cal.makeup_weekday} でない")
            for d in cal.makeup_days if WEEKDAYS[d.weekday()] != cal.makeup_weekday]


def check_research_days(course_id: str, prep_on: tuple[str, ...], computed: Dates, current: Dates,
                        research_days: tuple[str, ...]) -> list[Problem]:
    """研究日はなるべく空けておきたい曜日なので、当たっていても soft で知らせるだけにする。"""
    out = []
    hit = [d for d in prep_on if d in research_days]
    if hit:
        out.append(Problem(course_id, "research_day", None,
                           f"準備の曜日（prep_on）に研究日 {', '.join(hit)} が入っている", soft=True))
    planned = {e.n: e.date for e in computed.dates}
    for e in current.dates:
        if e.date is not None and e.date != planned.get(e.n) and WEEKDAYS[e.date.weekday()] in research_days:
            out.append(Problem(course_id, "research_day", e.date,
                               f"第 {e.n} 回を移した日 {_md(e.date)} は研究日に当たる", soft=True))
    return out


def course_problems(yd: YearData, course: Course, ghq: Path) -> list[Problem]:
    """一つの授業のぶつかり。moves が学事暦の日程に合わないときは ScheduleError で止める。"""
    cal = yd.calendar_for(course)
    repo = ghq / course.repo
    croot = courserepo.class_root(repo, course.class_id)
    computed = build_dates(course, cal, yd.events, [], "")
    moved = {m.n for m in yd.moves if m.course == course.id}
    if croot is None:
        # まだ classes/ に移っていない授業。配れないのは注意だけにし、事実への対応は moves で見る
        where = f"classes/{course.class_id}/class.yaml" if course.class_id else "courses.yaml の class:"
        return ([Problem(course.id, "not_issued", None, f"class root が無い（{where}）", soft=True)]
                + _undecided(course.id, computed, moved)
                + check_research_days(course.id, course.prep_on, computed, computed, yd.research_days))
    path = croot / "schedule.yaml"
    if not path.exists():
        return [Problem(course.id, "not_issued", None, f"{path} がまだ無い")]
    try:
        current = read_dates(path)
        sessions(computed, current, [])
    except ScheduleError as e:
        return [Problem(course.id, "bad_schedule", None, str(e))]
    expected = build_dates(course, cal, yd.events, yd.moves, current.issued,
                           course_id=courserepo.course_id(repo))
    out: list[Problem] = []
    changes, ss = [], []
    try:
        changes = read_changes(croot / "schedule-changes.yaml")
        ss = sessions(computed, current, changes)
    except ScheduleError as e:
        # 読めない changes は注意だけ。事実への対応は読めた分（読めなければ moves だけ）で見る
        out.append(Problem(course.id, "bad_changes", None, " ".join(str(e).split()), soft=True))
    out += check_course(course.id, cal, computed, expected, current, moved | {c.n for c in changes})
    out += check_research_days(course.id, course.prep_on, computed, current, yd.research_days)
    # (3) 上げた休講の相談が、まだ schedule.yaml に返ってきていない（待っている状態なので注意）
    out += [Problem(course.id, "pending_cancel", s.change.date,
                    f"第 {s.n} 回（{_md(s.change.date)}）の休講が schedule.yaml にまだ返っていない", soft=True)
            for s in ss if s.pending]
    return out


def run_check(root: Path, year: int, ghq: Path) -> list[Problem]:
    yd = load_year(root / str(year))
    out: list[Problem] = []
    for cal in yd.calendars.values():
        out += check_calendar(cal)
    for course in yd.courses:
        if course.repo is not None:
            out += course_problems(yd, course, ghq)
    return out


def main(argv: list[str] | None = None) -> int:
    setup_console()
    ap = argparse.ArgumentParser(prog="aidec check", description="機械で判定できるぶつかりを出す")
    ap.add_argument("year", type=int)
    ap.add_argument("--root", type=Path, default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    try:
        args.root = args.root or data_dir()
        problems = run_check(args.root, args.year, gitops.ghq_root())
    except KNOWN_ERRORS as e:
        error(str(e))
        return 1
    for p in sorted(problems, key=lambda p: (p.course or "", p.date or date.min, p.kind)):
        print(p.line())
    if not any(not p.soft for p in problems):
        print("ぶつかりは無い")
    return 1 if any(not p.soft for p in problems) else 0
