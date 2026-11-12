"""週ごとの一覧。授業の各回、出張・締め切り、prep の期間、未決の依頼を並べる。"""
from __future__ import annotations

import argparse
import unicodedata
from datetime import date, timedelta
from pathlib import Path

from classdays.calendar import WEEKDAYS

from . import gitops
from .cli import KNOWN_ERRORS, error, setup_console
from .config import data_dir
from .data import Course, YearData, load_year
from .requests import Request, load_requests
from .schedule import ScheduleError, Session, build_part, effective_sessions, load_schedule

_JP_WD = "月火水木金土日"


def _md(d: date) -> str:
    return f"{d.month}/{d.day}"


def _md_wd(d: date) -> str:
    return f"{_md(d)}（{_JP_WD[d.weekday()]}）"


def _sessions(yd: YearData, course: Course, ghq: Path) -> tuple[list[Session], str]:
    path = ghq / course.repo / str(yd.year) / "schedule.yaml" if course.repo else None
    if path is not None and path.exists():
        try:
            part, changes = load_schedule(path)
            return effective_sessions(part.plan, changes), ""
        except ScheduleError:
            note = "（schedule.yaml を読めない）"
    else:
        note = "（未配布）"
    part = build_part(course, yd.calendar_for(course), yd.events, "")
    return effective_sessions(part.plan, []), note


def prep_days(sessions: list[Session], prep_on: tuple[str, ...]) -> list[tuple[date, int]]:
    """準備を促す日（prep_on の曜日）と、準備する回の番号の組。

    通常の回は前の週（授業日の 6 日前から前日まで。前の回の翌日より前には広げない）。
    changes に prep_from がある回は、prep_from から授業日（release があればその前日）まで。
    回は実際に行う日の順に並べ、補講未定の休講の回は数えない。通常の第 1 回の前は出さない。
    """
    held = sorted((s.date, s.n, s.change) for s in sessions if s.date is not None)
    out = []
    for i, (d1, n1, change) in enumerate(held):
        if change is not None and change.prep_from is not None:
            start, end = change.prep_from, change.release or d1
        elif i == 0:
            continue
        else:
            start, end = max(held[i - 1][0] + timedelta(days=1), d1 - timedelta(days=6)), d1
        d = start
        while d < end:
            if WEEKDAYS[d.weekday()] in prep_on:
                out.append((d, n1))
            d += timedelta(days=1)
    return sorted(out)


def _overlaps(a: date, b: date, ws: date, we: date) -> bool:
    return a <= we and b >= ws


def week_report(yd: YearData, ghq: Path, reqs: list[Request], start: date, weeks: int) -> str:
    sessions = {c.id: _sessions(yd, c, ghq) for c in yd.courses}
    first = start - timedelta(days=start.weekday())
    blocks = []
    for w in range(weeks):
        ws = first + timedelta(weeks=w)
        we = ws + timedelta(days=6)
        items: list[tuple[date, int, str]] = []
        for course in yd.courses:
            ss, note = sessions[course.id]
            for s in ss:
                if ws <= s.planned <= we:
                    if s.cancelled:
                        text = f"第 {s.n} 回 休講（補講 {_md(s.date)}）" if s.date else f"第 {s.n} 回 休講（補講未定）"
                    else:
                        text = f"第 {s.n} 回" + (f" {s.mode}" if s.mode else "")
                    if s.facts:
                        text += " ／ " + "、".join(s.facts)
                    items.append((s.planned, 0, f"{_md_wd(s.planned)} {course.id} {text}{note}"))
                if s.cancelled and s.date and ws <= s.date <= we:
                    items.append((s.date, 0, f"{_md_wd(s.date)} {course.id} 第 {s.n} 回 補講"))
                release = s.change.release if s.change else None
                if release and ws <= release <= we:
                    items.append((release, 0, f"{_md_wd(release)} {course.id} 第 {s.n} 回 公開"))
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
        for r in reqs:
            if r.status != "open":
                continue
            hits = [d for d in [r.decide_by, *r.dates] if ws <= d <= we]
            if hits:
                d = min(hits)
                items.append((d, 3, f"{_md(d)} 未決の依頼 {r.id}（{r.to}、期限 {_md(r.decide_by)}）"))
        items.sort(key=lambda x: (x[0], x[1]))
        lines = [f"## {ws.isoformat()} の週（{_md(ws)}〜{_md(we)}）"]
        lines += [f"- {text}" for _, _, text in items] or ["- 予定なし"]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


_EN_WD = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _width(s: str) -> int:
    """表示の幅。全角（W・F）は 2 桁、曖昧な幅（A）は多くの端末の既定どおり 1 桁と数える。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _day_entries(yd: YearData, ghq: Path, reqs: list[Request], first: date,
                 last: date) -> dict[date, list[tuple[int, str, str]]]:
    """日ごとの (並び順, 名前, 中身)。並び順は 授業 0、準備 1、予定 2、繁忙期 3、依頼 4。"""
    days: dict[date, list[tuple[int, str, str]]] = {}

    def add(d: date, order: int, name: str, detail: str) -> None:
        if first <= d <= last:
            days.setdefault(d, []).append((order, name, detail))

    for course in yd.courses:
        ss, note = _sessions(yd, course, ghq)
        tag = " (not issued)" if note == "（未配布）" else (" (unreadable schedule.yaml)" if note else "")
        for s in ss:
            if s.cancelled:
                text = f"Day {s.n} cancelled → makeup {_md(s.date)}" if s.date else f"Day {s.n} cancelled (makeup TBD)"
            else:
                text = f"Day {s.n}" + (f" ({s.mode})" if s.mode else "")
            text += tag + "".join(f" · {f}" for f in s.facts)
            add(s.planned, 0, course.name, text)
            if s.cancelled and s.date:
                add(s.date, 0, course.name, f"Day {s.n} makeup")
            if s.change and s.change.release:
                add(s.change.release, 0, course.name, f"Day {s.n} release")
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
    names = {c.id: c.name for c in yd.courses}
    for r in reqs:
        if r.status == "open":
            add(r.decide_by, 4, names.get(r.to, r.to), f"request {r.id} due")
    for entries in days.values():
        entries.sort(key=lambda x: x[0])
    return days


def day_table(yd: YearData, ghq: Path, reqs: list[Request], start: date, days: int) -> str:
    """start から days 日分を、何も無い日も含めて 1 日 1 行以上の表にする。"""
    last = start + timedelta(days=days - 1)
    entries = _day_entries(yd, ghq, reqs, start, last)
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


def main(argv: list[str] | None = None) -> int:
    setup_console()
    ap = argparse.ArgumentParser(prog="week", description="週ごとの一覧")
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
        reqs = load_requests(args.root / "requests")
        if args.table:
            out = day_table(yd, gitops.ghq_root(), reqs, args.start, args.days)
        else:
            out = week_report(yd, gitops.ghq_root(), reqs, args.start, args.weeks)
    except KNOWN_ERRORS as e:
        error(str(e))
        return 1
    print(out, end="")
    return 0
