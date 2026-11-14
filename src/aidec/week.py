"""週ごとの一覧。授業の各回、出張・締め切り、prep の期間を並べる。"""
from __future__ import annotations

import argparse
import unicodedata
from datetime import date, timedelta
from pathlib import Path

from classdays.calendar import WEEKDAYS

from . import courserepo, gitops, inbox
from .cli import KNOWN_ERRORS, error, setup_console
from .config import data_dir
from .data import Course, YearData, load_year
from .schedule import ScheduleError, Session, build_dates, read_changes, read_dates, sessions

NOT_ISSUED = "（未配布）"
BAD_SCHEDULE = "（schedule.yaml を読めない）"
BAD_CHANGES = "（schedule-changes.yaml を読めない）"
_TAGS = {NOT_ISSUED: " (not issued)", BAD_SCHEDULE: " (unreadable schedule.yaml)",
         BAD_CHANGES: " (unreadable schedule-changes.yaml)", "": ""}

_JP_WD = "月火水木金土日"


def _md(d: date) -> str:
    return f"{d.month}/{d.day}"


def _md_wd(d: date) -> str:
    return f"{_md(d)}（{_JP_WD[d.weekday()]}）"


def _sessions(yd: YearData, course: Course, ghq: Path) -> tuple[list[Session], str]:
    """各回と印。class root の schedule.yaml・schedule-changes.yaml から作る。

    schedule.yaml が無ければ学事暦と moves から作って「未配布」、読めなければ同じく作って印を付ける。
    schedule-changes.yaml が読めなければ、それを入れずに作って印を付ける。
    """
    cal = yd.calendar_for(course)
    computed = build_dates(course, cal, yd.events, [], "")
    repo = ghq / course.repo if course.repo else None
    croot = courserepo.class_root(repo, course.class_id) if repo else None
    path = croot / "schedule.yaml" if croot else None
    note = NOT_ISSUED
    if path is not None and path.exists():
        try:
            current = read_dates(path)
            base = sessions(computed, current, [])
        except ScheduleError:
            note = BAD_SCHEDULE
        else:
            try:
                return sessions(computed, current, read_changes(croot / "schedule-changes.yaml")), ""
            except ScheduleError:
                return base, BAD_CHANGES
    return sessions(computed, build_dates(course, cal, yd.events, yd.moves, ""), []), note


def _placed(s: Session) -> date | None:
    """一覧に置く日。授業の日、無ければ休講は計算した日、未決の休講は取りやめる日。"""
    if s.pending:
        return s.change.date
    return s.date or s.planned


def prep_days(sessions: list[Session], prep_on: tuple[str, ...]) -> list[tuple[date, int]]:
    """準備を促す日（prep_on の曜日）と、準備する回の番号の組。

    授業日の 6 日前から前日まで（前の回の翌日より前には広げない）。回は授業の日の順に並べ、
    日の無い回（休講・未決）は数えない。第 1 回の前は出さない。prep_from は見ない。
    """
    held = sorted((s.date, s.n) for s in sessions if s.date is not None)
    out = []
    for i, (d1, n1) in enumerate(held):
        if i == 0:
            continue
        d = max(held[i - 1][0] + timedelta(days=1), d1 - timedelta(days=6))
        while d < d1:
            if WEEKDAYS[d.weekday()] in prep_on:
                out.append((d, n1))
            d += timedelta(days=1)
    return sorted(out)


def _overlaps(a: date, b: date, ws: date, we: date) -> bool:
    return a <= we and b >= ws


def week_report(yd: YearData, ghq: Path, start: date, weeks: int) -> str:
    by_course = {c.id: _sessions(yd, c, ghq) for c in yd.courses}
    first = start - timedelta(days=start.weekday())
    blocks = []
    for w in range(weeks):
        ws = first + timedelta(weeks=w)
        we = ws + timedelta(days=6)
        items: list[tuple[date, int, str]] = []
        for course in yd.courses:
            ss, note = by_course[course.id]
            for s in ss:
                d = _placed(s)
                if d is None or not ws <= d <= we:
                    continue
                if s.pending:
                    text = f"第 {s.n} 回 休講（未決）"
                elif s.cancelled:
                    text = f"第 {s.n} 回 休講"
                elif s.date is None:
                    text = f"第 {s.n} 回 日付なし"
                else:
                    text = f"第 {s.n} 回" + (f" {s.mode}" if s.mode else "")
                    if s.change and s.change.prep_from and s.mode == "ondemand":
                        text += f"（prep_from {_md(s.change.prep_from)}）"
                if s.notes:
                    text += " ／ " + "、".join(s.notes)
                items.append((d, 0, f"{_md_wd(d)} {course.id} {text}{note}"))
            for d, n in prep_days(ss, course.prep_on):
                if ws <= d <= we:
                    items.append((d, 4, f"{_md_wd(d)} {course.id} 第 {n} 回の準備"))
        for e in yd.events:
            if _overlaps(e.date, e.end, ws, we):
                if e.kind == "deadline":
                    items.append((e.date, 1, f"{_md(e.date)} 締め切り: {e.title}"))
                else:
                    span = _md(e.date) if e.end == e.date else f"{_md(e.date)}〜{_md(e.end)}"
                    items.append((max(e.date, ws), 1, f"{span} {e.title}"))
            prep = e.prep_span()
            if prep and _overlaps(prep[0], prep[1], ws, we):
                d = max(prep[0], ws)
                items.append((d, 2, f"{_md(d)} 準備を軽くしたい期間（{_md(e.date)} {e.title}の前 {e.prep_weeks} 週）"))
        items.sort(key=lambda x: (x[0], x[1]))
        lines = [f"## {ws.isoformat()} の週（{_md(ws)}〜{_md(we)}）"]
        lines += [f"- {text}" for _, _, text in items] or ["- 予定なし"]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


_EN_WD = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _width(s: str) -> int:
    """表示の幅。全角（W・F）は 2 桁、曖昧な幅（A）は多くの端末の既定どおり 1 桁と数える。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _day_entries(yd: YearData, ghq: Path, first: date,
                 last: date) -> dict[date, list[tuple[int, str, str]]]:
    """日ごとの (並び順, 名前, 中身)。並び順は 授業 0、準備 1、予定 2、繁忙期 3。"""
    days: dict[date, list[tuple[int, str, str]]] = {}

    def add(d: date, order: int, name: str, detail: str) -> None:
        if first <= d <= last:
            days.setdefault(d, []).append((order, name, detail))

    for course in yd.courses:
        ss, note = _sessions(yd, course, ghq)
        tag = _TAGS[note]
        for s in ss:
            if s.pending:
                text = f"Day {s.n} cancel pending"
            elif s.cancelled:
                text = f"Day {s.n} cancelled"
            elif s.date is None:
                text = f"Day {s.n} no date"
            else:
                text = f"Day {s.n}" + (f" ({s.mode})" if s.mode else "")
            text += tag
            if s.date and s.change and s.change.prep_from and s.mode == "ondemand":
                text += f" · prep_from {_md(s.change.prep_from)}"
            text += "".join(f" · {f}" for f in s.notes)
            d = _placed(s)
            if d is not None:
                add(d, 0, course.name, text)
        for d, n in prep_days(ss, course.prep_on):
            add(d, 1, course.name, f"Prep for Day {n}")
    for e in yd.events:
        span = _md(e.date) if e.end == e.date else f"{_md(e.date)}–{_md(e.end)}"
        d = e.date
        while d <= e.end:
            add(d, 2, e.title, e.note or f"{e.kind} {span}")
            d += timedelta(days=1)
        prep = e.prep_span()
        if prep:
            d = prep[0]
            while d <= prep[1]:
                add(d, 3, "busy", f"before {e.title} ({_md(e.date)})")
                d += timedelta(days=1)
    for entries in days.values():
        entries.sort(key=lambda x: x[0])
    return days


def day_table(yd: YearData, ghq: Path, start: date, days: int) -> str:
    """start から days 日分を、何も無い日も含めて 1 日 1 行以上の表にする。"""
    last = start + timedelta(days=days - 1)
    entries = _day_entries(yd, ghq, start, last)
    w = max((_width(name) for es in entries.values() for _, name, _ in es), default=0)
    lines = []
    d = start
    while d <= last:
        head = f"{d.month:02d}-{d.day:02d} {_EN_WD[d.weekday()]}"
        es = entries.get(d, [])
        if not es:
            lines.append(f"{head} |")
        for i, (_, name, detail) in enumerate(es):
            left = head if i == 0 else " " * len(head)
            lines.append(f"{left} | {name}{' ' * (w - _width(name))} | {detail}".rstrip())
        d += timedelta(days=1)
    return "\n".join(lines) + "\n"


def inbox_section(root: Path) -> str:
    """授業から上がってきた相談（inbox/）。無ければ空。"""
    items, bad = inbox.load(root)
    if not items and not bad:
        return ""
    lines = ["", "## 上がってきた相談"]
    for it in items:
        where = it.course + (f" 第 {it.session} 回" if it.session is not None else "")
        first = (it.text.splitlines() or [""])[0]
        quiet = "（返事不要）" if it.no_reply else ""
        lines.append(f"- {it.ref} {where}{quiet}: {first}")
    lines += [f"- 読めない: {name}" for name in bad]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    setup_console()
    ap = argparse.ArgumentParser(prog="aidec week", description="週ごとの一覧")
    ap.add_argument("year", type=int)
    ap.add_argument("--from", dest="start", type=date.fromisoformat, default=date.today(),
                    help="この日を含む週から（既定: 今日）")
    ap.add_argument("--weeks", type=int, default=2)
    ap.add_argument("--table", action="store_true", help="--from の日から --days 日分を、何も無い日も含めて表にする")
    ap.add_argument("--days", type=int, default=21)
    ap.add_argument("--root", type=Path, default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    try:
        args.root = args.root or data_dir()
        yd = load_year(args.root / str(args.year))
        if args.table:
            out = day_table(yd, gitops.ghq_root(), args.start, args.days)
        else:
            out = week_report(yd, gitops.ghq_root(), args.start, args.weeks)
    except KNOWN_ERRORS as e:
        error(str(e))
        return 1
    print(out, end="")
    print(inbox_section(args.root), end="")
    return 0
