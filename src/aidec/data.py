"""<年度>/ の学事暦・courses.yaml・events.yaml・settings.yaml・moves.yaml を読む。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath

from classdays.calendar import WEEKDAYS, Calendar, CalendarError, load_calendar
from classdays.plan import PlanError, Slot, parse_slot

from . import yamlio

_COURSE_KEYS = {"id", "repo", "calendar", "term", "slot", "sessions", "prep_on", "label", "class"}
_MOVE_KEYS = {"course", "n", "date", "cancelled", "notes", "ref"}
_SETTINGS_KEYS = {"research_days"}
_EVENT_KEYS = {"date", "end", "kind", "title", "prep", "note"}
ID = re.compile(r"[A-Za-z0-9_-]+")       # 授業の id に使える文字
CLASS_ID = re.compile(r"[a-z0-9-]+")     # IK の class id（^[a-z0-9-]+$）


class DataError(ValueError):
    pass


@dataclass(frozen=True)
class Course:
    id: str
    repo: str | None
    calendar: str
    term: str
    slot: Slot
    sessions: int
    prep_on: tuple[str, ...] = ()      # 次の回の準備をする曜日
    label: str | None = None           # 表に出す短い名前。無ければ id
    class_id: str | None = None        # 授業レポの classes/<id>/（IK の class id）

    @property
    def name(self) -> str:
        return self.label or self.id


@dataclass(frozen=True)
class Event:
    date: date
    end: date
    kind: str
    title: str
    prep_weeks: int | None
    note: str | None = None            # 時刻・場所などの添え書き

    def covers(self, d: date) -> bool:
        return self.date <= d <= self.end

    def prep_span(self) -> tuple[date, date] | None:
        """締め切りの前の、授業準備を重くしたくない期間。"""
        if not self.prep_weeks:
            return None
        return self.date - timedelta(weeks=self.prep_weeks), self.date - timedelta(days=1)


@dataclass(frozen=True)
class Move:
    """授業の 1 回を、学事暦が示す日から動かす（日付に移す、または休講）。"""
    course: str
    n: int
    date: date | None
    cancelled: bool
    notes: tuple[str, ...] = ()
    ref: str | None = None             # inbox の ref


@dataclass(frozen=True)
class YearData:
    year: int
    dir: Path
    calendars: dict[str, Calendar]
    courses: list[Course]
    events: list[Event]
    research_days: tuple[str, ...] = ()   # なるべく空けておきたい曜日
    moves: list[Move] = field(default_factory=list)

    def calendar_for(self, course: Course) -> Calendar:
        return self.calendars[course.calendar]


def _is_relative(repo: str) -> bool:
    if PureWindowsPath(repo).is_absolute() or PureWindowsPath(repo).drive or PurePosixPath(repo).is_absolute():
        return False
    return ".." not in PurePosixPath(repo.replace("\\", "/")).parts


def _load_calendars(year_dir: Path) -> dict[str, Calendar]:
    out = {}
    for path in sorted(year_dir.glob("calendar-*.yaml")):
        try:
            cal = load_calendar(path)
        except CalendarError as e:
            raise DataError(str(e)) from None
        if path.stem != f"calendar-{cal.university}":
            raise DataError(f"{path.name}: university が {cal.university} なので calendar-{cal.university}.yaml にする")
        out[cal.university] = cal
    return out


def _load(path: Path):
    try:
        return yamlio.load(path)
    except yamlio.YamlError as e:
        raise DataError(str(e)) from None


def _weekdays(v, where: str) -> tuple[str, ...]:
    if v is None:
        return ()
    if not isinstance(v, list) or any(d not in WEEKDAYS for d in v):
        raise DataError(f"{where}: 曜日の列で書く（{'/'.join(WEEKDAYS)}）: {v!r}")
    return tuple(str(d) for d in v)


def _load_settings(path: Path) -> tuple[str, ...]:
    if not path.exists():
        return ()
    raw = _load(path) or {}
    if not isinstance(raw, dict):
        raise DataError(f"{path.name}: 対応づけで書く")
    unknown = set(raw) - _SETTINGS_KEYS
    if unknown:
        raise DataError(f"{path.name}: 知らない欄 {', '.join(sorted(unknown))}")
    return _weekdays(raw.get("research_days"), f"{path.name}.research_days")


def _load_courses(path: Path, calendars: dict[str, Calendar]) -> list[Course]:
    raw = _load(path) or []
    if not isinstance(raw, list):
        raise DataError(f"{path.name}: 授業の列で書く")
    out: list[Course] = []
    for i, c in enumerate(raw):
        where = f"{path.name}[{i}]"
        if not isinstance(c, dict):
            raise DataError(f"{where}: 対応づけで書く")
        unknown = set(c) - _COURSE_KEYS
        if unknown:
            raise DataError(f"{where}: 知らない欄 {', '.join(sorted(unknown))}")
        for k in ("id", "calendar", "term", "slot", "sessions"):
            if k not in c:
                raise DataError(f"{where}: {k} が無い")
        cid = str(c["id"])
        if any(x.id == cid for x in out):
            raise DataError(f"{path.name}: 授業 {cid} が二つある")
        if c["calendar"] not in calendars:
            raise DataError(f"{where}: 学事暦 {c['calendar']} が無い（calendar-{c['calendar']}.yaml）")
        if c["term"] not in calendars[c["calendar"]].terms:
            raise DataError(f"{where}: 学事暦 {c['calendar']} に学期 {c['term']} が無い")
        repo = c.get("repo")
        if repo is not None and not _is_relative(str(repo)):
            raise DataError(f"{where}: repo は ghq root からの相対パスで書く: {repo}")
        cls = c.get("class")
        if cls is not None and not (isinstance(cls, (str, int)) and not isinstance(cls, bool)
                                    and CLASS_ID.fullmatch(str(cls))):
            raise DataError(f"{where}.class: 小文字の英字・数字・- で書く: {cls!r}")
        try:
            slot = parse_slot(c["slot"])
        except PlanError as e:
            raise DataError(f"{where}: {e}") from None
        out.append(Course(cid, None if repo is None else str(repo), str(c["calendar"]),
                          str(c["term"]), slot, int(c["sessions"]),
                          _weekdays(c.get("prep_on"), f"{where}.prep_on"),
                          None if c.get("label") is None else str(c["label"]),
                          None if c.get("class") is None else str(c["class"])))
    return out


def _load_events(path: Path) -> list[Event]:
    if not path.exists():
        return []
    raw = _load(path) or []
    if not isinstance(raw, list):
        raise DataError(f"{path.name}: 予定の列で書く")
    out = []
    for i, e in enumerate(raw):
        where = f"{path.name}[{i}]"
        if not isinstance(e, dict):
            raise DataError(f"{where}: 対応づけで書く")
        unknown = set(e) - _EVENT_KEYS
        if unknown:
            raise DataError(f"{where}: 知らない欄 {', '.join(sorted(unknown))}")
        for k in ("date", "kind", "title"):
            if k not in e:
                raise DataError(f"{where}: {k} が無い")
        start, end = e["date"], e.get("end", e["date"])
        for name, v in (("date", start), ("end", end)):
            if not isinstance(v, date):
                raise DataError(f"{where}.{name}: 日付として読めない: {v!r}（YYYY-MM-DD で書く）")
        if end < start:
            raise DataError(f"{where}: end が date より前にある")
        prep = e.get("prep")
        weeks = None
        if prep is not None:
            m = re.fullmatch(r"(\d+)w", str(prep))
            if not m:
                raise DataError(f"{where}: prep は 2w の形で書く: {prep!r}")
            weeks = int(m.group(1))
        out.append(Event(start, end, str(e["kind"]), str(e["title"]), weeks,
                         None if e.get("note") is None else str(e["note"])))
    return out


def load_moves(year_dir: Path, courses: list[Course] | None = None) -> list[Move]:
    """moves.yaml を読む。courses があれば授業の id と回の範囲も確かめる。"""
    path = year_dir / "moves.yaml"
    if not path.exists():
        return []
    raw = _load(path) or []
    if not isinstance(raw, list):
        raise DataError(f"{path.name}: 動かす回の列で書く")
    by_id = None if courses is None else {c.id: c for c in courses}
    out: list[Move] = []
    seen: set[tuple[str, int]] = set()
    for i, m in enumerate(raw):
        where = f"{path.name}[{i}]"
        if not isinstance(m, dict):
            raise DataError(f"{where}: 対応づけで書く")
        unknown = set(m) - _MOVE_KEYS
        if unknown:
            raise DataError(f"{where}: 知らない欄 {', '.join(sorted(unknown))}")
        for k in ("course", "n"):
            if k not in m:
                raise DataError(f"{where}: {k} が無い")
        cid, n = str(m["course"]), m["n"]
        if isinstance(n, bool) or not isinstance(n, int):
            raise DataError(f"{where}.n: 整数で書く: {n!r}")
        d, cancelled = m.get("date"), m.get("cancelled", False)
        if not isinstance(cancelled, bool):
            raise DataError(f"{where}.cancelled: cancelled: true か false で書く: {cancelled!r}")
        if d is not None and type(d) is not date:       # 時刻付き（datetime）も弾く
            raise DataError(f"{where}.date: 日付として読めない: {d!r}（YYYY-MM-DD で書く）")
        if d is not None and cancelled:
            raise DataError(f"{where}: date と cancelled は同時に書けない")
        if d is None and not cancelled:
            raise DataError(f"{where}: date か cancelled: true のどちらかを書く")
        if by_id is not None:
            if cid not in by_id:
                raise DataError(f"{where}: 授業 {cid} が無い（courses.yaml）")
            if not 1 <= n <= by_id[cid].sessions:
                raise DataError(f"{where}: n は 1..{by_id[cid].sessions} の範囲で書く: {n}")
        if (cid, n) in seen:
            raise DataError(f"{path.name}: {cid} の第 {n} 回が二つある")
        seen.add((cid, n))
        notes = m.get("notes") or []
        if not isinstance(notes, list) or not all(isinstance(x, str) and x.strip() for x in notes):
            raise DataError(f"{where}.notes: 空でない文字列の列で書く")
        out.append(Move(cid, n, d, cancelled, tuple(str(x) for x in notes),
                        None if m.get("ref") is None else str(m["ref"])))
    return out


def load_year(year_dir: Path) -> YearData:
    calendars = _load_calendars(year_dir)
    courses_path = year_dir / "courses.yaml"
    if not courses_path.exists():
        raise DataError(f"{courses_path} が無い")
    courses = _load_courses(courses_path, calendars)
    return YearData(
        year=int(year_dir.name),
        dir=year_dir,
        calendars=calendars,
        courses=courses,
        events=_load_events(year_dir / "events.yaml"),
        research_days=_load_settings(year_dir / "settings.yaml"),
        moves=load_moves(year_dir, courses),
    )
