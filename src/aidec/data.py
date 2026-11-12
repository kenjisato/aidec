"""<年度>/ の学事暦・courses.yaml・events.yaml を読む。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath

from classdays.calendar import WEEKDAYS, Calendar, CalendarError, load_calendar
from classdays.plan import PlanError, Slot, parse_slot

from . import yamlio

_COURSE_KEYS = {"id", "repo", "calendar", "term", "slot", "sessions", "prep_on", "label"}
_SETTINGS_KEYS = {"research_days"}
_EVENT_KEYS = {"date", "end", "kind", "title", "prep", "note"}


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
class YearData:
    year: int
    dir: Path
    calendars: dict[str, Calendar]
    courses: list[Course]
    events: list[Event]
    research_days: tuple[str, ...] = ()   # なるべく空けておきたい曜日

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
        try:
            slot = parse_slot(c["slot"])
        except PlanError as e:
            raise DataError(f"{where}: {e}") from None
        out.append(Course(cid, None if repo is None else str(repo), str(c["calendar"]),
                          str(c["term"]), slot, int(c["sessions"]),
                          _weekdays(c.get("prep_on"), f"{where}.prep_on"),
                          None if c.get("label") is None else str(c["label"])))
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


def load_year(year_dir: Path) -> YearData:
    calendars = _load_calendars(year_dir)
    courses_path = year_dir / "courses.yaml"
    if not courses_path.exists():
        raise DataError(f"{courses_path} が無い")
    return YearData(
        year=int(year_dir.name),
        dir=year_dir,
        calendars=calendars,
        courses=_load_courses(courses_path, calendars),
        events=_load_events(year_dir / "events.yaml"),
        research_days=_load_settings(year_dir / "settings.yaml"),
    )
