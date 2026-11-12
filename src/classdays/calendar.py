"""学事暦。大学の公表物を写した YAML を読み、授業日かどうかを答える。

このパッケージは workdesk の他のモジュールを import しない。instructor-kit に移せるようにするためである。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

_TOP_KEYS = {"university", "year", "source", "terms", "no_class", "swap",
             "makeup_days", "makeup_weekday", "exams", "amendments"}
_AMENDMENT_KEYS = {"announced", "source", "add_no_class"}


class CalendarError(ValueError):
    pass


@dataclass(frozen=True)
class Span:
    start: date
    end: date

    def __contains__(self, d: date) -> bool:
        return self.start <= d <= self.end


@dataclass(frozen=True)
class Amendment:
    announced: date
    source: str
    add_no_class: tuple[date, ...]


@dataclass(frozen=True)
class Calendar:
    university: str
    year: int
    source: str
    terms: dict[str, Span]
    no_class: frozenset[date]
    swap: dict[date, str]
    makeup_days: tuple[date, ...]
    exams: tuple[Span, ...]
    amendments: tuple[Amendment, ...]
    makeup_weekday: str | None = None      # 補講日の曜日が決まっている大学だけ書く

    def weekday_of(self, d: date) -> str:
        """振替を考えた曜日。"""
        return self.swap.get(d, WEEKDAYS[d.weekday()])

    def term_of(self, d: date) -> str | None:
        for name, span in self.terms.items():
            if d in span:
                return name
        return None

    def is_exam(self, d: date) -> bool:
        return any(d in s for s in self.exams)

    def amendment_closing(self, d: date) -> Amendment | None:
        """d を休講にした年度途中の変更。古い順に見て最初のもの。"""
        for a in sorted(self.amendments, key=lambda a: a.announced):
            if d in a.add_no_class:
                return a
        return None

    def is_base_class_day(self, d: date, term: str) -> bool:
        """元の学事暦で、その学期の授業日か。amendments は見ない。"""
        return d in self.terms[term] and d not in self.no_class and not self.is_exam(d)

    def is_closed(self, d: date) -> bool:
        """休講日・試験期間・年度途中の休講のどれかか。"""
        return d in self.no_class or self.is_exam(d) or self.amendment_closing(d) is not None


def _date(v, where: str) -> date:
    if isinstance(v, date):
        return v
    raise CalendarError(f"{where}: 日付として読めない: {v!r}（YYYY-MM-DD で書く）")


def _dates(v, where: str) -> tuple[date, ...]:
    if v is None:
        return ()
    if not isinstance(v, list):
        raise CalendarError(f"{where}: 日付の列で書く")
    return tuple(_date(x, f"{where}[{i}]") for i, x in enumerate(v))


def _span(v, where: str) -> Span:
    if not isinstance(v, dict) or set(v) != {"start", "end"}:
        raise CalendarError(f"{where}: {{start: YYYY-MM-DD, end: YYYY-MM-DD}} の形で書く")
    s = Span(_date(v["start"], f"{where}.start"), _date(v["end"], f"{where}.end"))
    if s.end < s.start:
        raise CalendarError(f"{where}: end が start より前にある")
    return s


def calendar_from_dict(d: dict) -> Calendar:
    if not isinstance(d, dict):
        raise CalendarError("学事暦は対応づけ（university: ... の形）で書く")
    unknown = set(d) - _TOP_KEYS
    if unknown:
        raise CalendarError(f"知らない欄: {', '.join(sorted(unknown))}")
    for k in ("university", "year", "source", "terms"):
        if k not in d:
            raise CalendarError(f"{k} が無い")
    if not isinstance(d["terms"], dict) or not d["terms"]:
        raise CalendarError("terms に学期を一つ以上書く")
    terms = {str(name): _span(v, f"terms.{name}") for name, v in d["terms"].items()}

    swap: dict[date, str] = {}
    for i, s in enumerate(d.get("swap") or []):
        if not isinstance(s, dict) or set(s) != {"date", "as"} or s["as"] not in WEEKDAYS:
            raise CalendarError(f"swap[{i}]: {{date: YYYY-MM-DD, as: mon}} の形で書く（as は {'/'.join(WEEKDAYS)}）")
        swap[_date(s["date"], f"swap[{i}].date")] = s["as"]

    exams_raw = d.get("exams")
    if exams_raw is None:
        exams: tuple[Span, ...] = ()
    elif isinstance(exams_raw, list):
        exams = tuple(_span(x, f"exams[{i}]") for i, x in enumerate(exams_raw))
    else:
        exams = (_span(exams_raw, "exams"),)

    amendments = []
    for i, a in enumerate(d.get("amendments") or []):
        where = f"amendments[{i}]"
        if not isinstance(a, dict):
            raise CalendarError(f"{where}: announced・source・add_no_class を書く")
        unknown = set(a) - _AMENDMENT_KEYS
        if unknown:
            raise CalendarError(f"{where}: 知らない欄 {', '.join(sorted(unknown))}（いまは add_no_class だけを扱う）")
        for k in ("announced", "source"):
            if k not in a:
                raise CalendarError(f"{where}: {k} が無い")
        amendments.append(Amendment(_date(a["announced"], f"{where}.announced"), str(a["source"]),
                                    _dates(a.get("add_no_class"), f"{where}.add_no_class")))

    makeup_weekday = d.get("makeup_weekday")
    if makeup_weekday is not None and makeup_weekday not in WEEKDAYS:
        raise CalendarError(f"makeup_weekday: {'/'.join(WEEKDAYS)} のどれかで書く: {makeup_weekday!r}")

    return Calendar(
        university=str(d["university"]),
        year=int(d["year"]),
        source=str(d["source"]),
        terms=terms,
        no_class=frozenset(_dates(d.get("no_class"), "no_class")),
        swap=swap,
        makeup_days=_dates(d.get("makeup_days"), "makeup_days"),
        exams=exams,
        amendments=tuple(amendments),
        makeup_weekday=makeup_weekday,
    )


def load_calendar(path: Path) -> Calendar:
    try:
        with open(path, encoding="utf-8") as f:
            data = YAML(typ="safe").load(f)
    except (ValueError, YAMLError) as e:
        raise CalendarError(f"{path.name}: 読めない（{e}）") from None
    try:
        return calendar_from_dict(data)
    except CalendarError as e:
        raise CalendarError(f"{path.name}: {e}") from None
