"""授業レポの日程ファイル（IK SPEC §8.8）。

class root（classes/<class id>/）の schedule.yaml を aidec が書き（Dates）、
schedule-changes.yaml を授業レポの director が書く（Change。aidec は読むだけ）。
各回の授業の日は sessions() が重ねる。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from classdays.calendar import Calendar
from classdays.plan import plan_sessions

from . import yamlio
from .data import Course, Event, Move

# 授業日の事実にする予定の種類（設計書: 出張・兼業・学会）。会議・締め切りなどは week に並べるだけ
FACT_KINDS = {"trip", "side_job", "conference"}


class ScheduleError(ValueError):
    pass


def _md(d: date) -> str:
    return f"{d.month}/{d.day}"


def facts_for(d: date, cal: Calendar, events: list[Event]) -> list[str]:
    out = []
    a = cal.amendment_closing(d)
    if a is not None:
        out.append(f"休講（{a.source}）")
    for e in events:
        if e.kind in FACT_KINDS and e.covers(d):
            span = _md(e.date) if e.end == e.date else f"{_md(e.date)}〜{_md(e.end)}"
            out.append(f"{e.title}（{span}）")
    return out


def _load(path: Path):
    try:
        return yamlio.load(path)
    except yamlio.YamlError as e:
        raise ScheduleError(f"{path}: {e}") from None


_DATES_KEYS = {"course", "class", "issued", "dates", "makeup_days"}
_DATE_ENTRY_KEYS = {"n", "date", "cancelled", "notes"}
_CHANGE_KEYS = {"n", "reason", "mode", "release", "prep_from", "cancel", "date", "ref"}


@dataclass(frozen=True)
class DateEntry:
    n: int
    date: date | None                  # cancelled の回は None
    cancelled: bool = False
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Dates:
    """schedule.yaml の中身。"""
    course: str
    cls: str | None                    # IK の class id。courses.yaml に class: が無ければ None（書けない）
    issued: str
    dates: tuple[DateEntry, ...]
    makeup_days: tuple[date, ...] = ()

    def same_content(self, other: "Dates") -> bool:
        return replace(self, issued="") == replace(other, issued="")


def build_dates(course: Course, cal: Calendar, events: list[Event], moves: list[Move], issued: str,
                *, course_id: str | None = None) -> Dates:
    """学事暦で各回の日を出し、moves（この授業の分）で日付を置き換えるか cancelled にする。

    course_id は書く course: の値（course root の course.yaml の id）。無ければ courses.yaml の id。
    """
    by_n = {m.n: m for m in moves if m.course == course.id}
    entries = []
    for s in plan_sessions(cal, course.term, course.slot, course.sessions):
        m = by_n.pop(s.n, None)
        if m is None:
            entries.append(DateEntry(s.n, s.date, False, tuple(facts_for(s.date, cal, events))))
        elif m.cancelled or m.date is None:
            entries.append(DateEntry(s.n, None, True, tuple(facts_for(s.date, cal, events)) + m.notes))
        else:
            entries.append(DateEntry(s.n, m.date, False, tuple(facts_for(m.date, cal, events)) + m.notes))
    if by_n:
        raise ScheduleError(f"{course.id}: moves の第 {min(by_n)} 回は学事暦の日程に無い")
    span = cal.terms[course.term]
    return Dates(course_id or course.id, course.class_id, issued, tuple(entries),
                 tuple(d for d in cal.makeup_days if d in span))


def _dates_map(d: Dates) -> CommentedMap:
    if not d.cls:
        raise ScheduleError(f"{d.course}: class が無い（courses.yaml の class:）")
    items = []
    for e in d.dates:
        m: dict = {"n": e.n}
        if e.cancelled:
            m["cancelled"] = True
        else:
            m["date"] = e.date
        if e.notes:
            m["notes"] = yamlio.flow_seq(list(e.notes))
        items.append(yamlio.flow_map(m))
    data = CommentedMap()
    data["course"] = d.course
    data["class"] = d.cls
    data["issued"] = d.issued
    data["dates"] = CommentedSeq(items)
    data["makeup_days"] = yamlio.flow_seq(list(d.makeup_days))
    return data


def write_dates(path: Path, d: Dates) -> bool:
    """schedule.yaml を書く。issued のほかが今のファイルと同じなら書かずに False。"""
    data = _dates_map(d)
    if path.exists():
        try:
            if read_dates(path).same_content(d):
                return False
        except ScheduleError:      # 読めないものは上書きする（書くのはこちらだけ）
            pass
    yamlio.dump(data, path)
    return True


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def read_dates(path: Path) -> Dates:
    where = str(path)
    data = _load(path)
    if not isinstance(data, dict):
        raise ScheduleError(f"{where}: 対応づけ（course: ... の形）になっていない")
    unknown = set(data) - _DATES_KEYS
    if unknown:
        raise ScheduleError(f"{where}: 知らない欄 {', '.join(sorted(map(str, unknown)))}")
    for k in ("course", "class", "issued", "dates"):
        if k not in data:
            raise ScheduleError(f"{where}: {k} が無い")
    if not isinstance(data["dates"], list):
        raise ScheduleError(f"{where}: dates は列で書く")
    entries: list[DateEntry] = []
    seen: set[int] = set()
    for i, e in enumerate(data["dates"]):
        at = f"{where}: dates[{i}]"
        form = f"{at}: {{n: 1, date: YYYY-MM-DD}} か {{n: 1, cancelled: true}} の形で書く"
        if not isinstance(e, dict) or not _is_int(e.get("n")) or e["n"] < 1:
            raise ScheduleError(form)
        unknown = set(e) - _DATE_ENTRY_KEYS
        if unknown:
            raise ScheduleError(f"{at}: 知らない欄 {', '.join(sorted(map(str, unknown)))}")
        if ("date" in e) == ("cancelled" in e) or ("cancelled" in e and e["cancelled"] is not True) \
                or ("date" in e and not isinstance(e["date"], date)):
            raise ScheduleError(form)
        notes = e.get("notes") or []
        if not isinstance(notes, list) or not all(isinstance(x, str) for x in notes):
            raise ScheduleError(f"{at}: notes は文字列の列で書く")
        n = int(e["n"])
        if n in seen:
            raise ScheduleError(f"{where}: 第 {n} 回が二度書かれている")
        seen.add(n)
        entries.append(DateEntry(n, e.get("date"), "cancelled" in e, tuple(str(x) for x in notes)))
    makeup = data.get("makeup_days") or []
    if not isinstance(makeup, list) or not all(isinstance(x, date) for x in makeup):
        raise ScheduleError(f"{where}: makeup_days は日付（YYYY-MM-DD）の列で書く")
    return Dates(str(data["course"]), str(data["class"]), str(data["issued"]), tuple(entries), tuple(makeup))


@dataclass(frozen=True)
class Change:
    """schedule-changes.yaml の 1 行。mode（online・ondemand）か cancel のどちらか。"""
    n: int
    reason: str
    mode: str | None = None
    release: date | None = None        # ondemand: 学生が教材を受け取る日（授業の日）
    prep_from: date | None = None      # ondemand: 取りかかれる最初の日
    cancel: bool = False
    date: date | None = None           # cancel: 取りやめる、予定の日
    ref: str | None = None             # 上に上げた変更の inbox の ref


def read_changes(path: Path) -> list[Change]:
    """schedule-changes.yaml を読む（書かない）。同じ回の後の行が前の行に代わる。無ければ空。"""
    if not path.exists():
        return []
    where = str(path)
    data = _load(path)
    if not isinstance(data, dict):
        raise ScheduleError(f"{where}: 対応づけ（course: ... の形）になっていない")
    raw = data.get("changes") or []
    if not isinstance(raw, list):
        raise ScheduleError(f"{where}: changes は列で書く")
    out: dict[int, Change] = {}
    for i, c in enumerate(raw):
        at = f"{where}: changes[{i}]"
        if not isinstance(c, dict) or "n" not in c:
            raise ScheduleError(f"{at}: n が無い")
        if not _is_int(c["n"]) or c["n"] < 1:
            raise ScheduleError(f"{at}: n は 1 以上の整数で書く")
        unknown = set(c) - _CHANGE_KEYS
        if unknown:
            raise ScheduleError(f"{at}: 知らない欄 {', '.join(sorted(map(str, unknown)))}"
                                f"（使える欄: {', '.join(sorted(_CHANGE_KEYS))}）")
        reason = c.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ScheduleError(f"{at}: reason が無い")
        for k in ("release", "prep_from", "date"):
            if k in c and not isinstance(c[k], date):
                raise ScheduleError(f"{at}: {k} が日付として読めない: {c[k]!r}（YYYY-MM-DD で書く）")
        ref = c.get("ref")
        if ref is not None and (not isinstance(ref, str) or not ref):
            raise ScheduleError(f"{at}: ref は文字列で書く")
        ondemand_only = "release" in c or "prep_from" in c
        if "mode" in c:
            if "cancel" in c or "date" in c:
                raise ScheduleError(f"{at}: mode か cancel のどちらか一方を書く")
            if c["mode"] not in ("online", "ondemand"):
                raise ScheduleError(f"{at}: mode は online か ondemand: {c['mode']!r}")
            if c["mode"] == "ondemand" and "release" not in c:
                raise ScheduleError(f"{at}: mode: ondemand には release が要る")
            if c["mode"] == "online" and ondemand_only:
                raise ScheduleError(f"{at}: release・prep_from は mode: ondemand のときだけ書く")
        else:
            if c.get("cancel") is not True:
                raise ScheduleError(f"{at}: mode か cancel: true のどちらかを書く")
            if "date" not in c:
                raise ScheduleError(f"{at}: cancel: true には date（取りやめる日）が要る")
            if ondemand_only:
                raise ScheduleError(f"{at}: release・prep_from は mode: ondemand のときだけ書く")
        n = int(c["n"])
        out[n] = Change(n, str(reason), c.get("mode"), c.get("release"), c.get("prep_from"),
                                "cancel" in c, c.get("date"), None if ref is None else str(ref))
    return sorted(out.values(), key=lambda x: x.n)


@dataclass(frozen=True)
class Session:
    n: int
    planned: date | None               # 学事暦で計算した日（cancelled の回にも残る）
    date: date | None                  # 授業の日。ondemand なら release。cancelled・未定・載っていない回は None
    mode: str | None
    cancelled: bool                    # schedule.yaml で cancelled: true
    notes: tuple[str, ...]
    change: Change | None
    pending: bool = False              # cancel の date が載っている日のまま: 日は佐藤に聞く


def sessions(computed: Dates, current: Dates, changes: list[Change]) -> list[Session]:
    """各回の授業の日。computed は moves を入れずに学事暦で計算したもの、current は授業レポの schedule.yaml。"""
    listed = {e.n: e for e in current.dates}
    ns = {e.n for e in computed.dates}
    extra = sorted(set(listed) - ns)
    if extra:
        raise ScheduleError(f"schedule.yaml の第 {extra[0]} 回は学事暦の日程に無い")
    for c in changes:
        if c.n not in listed:
            raise ScheduleError(f"schedule-changes.yaml の第 {c.n} 回は schedule.yaml の dates に無い")
    by_n = {c.n: c for c in changes}
    out = []
    for e in computed.dates:
        cur, c = listed.get(e.n), by_n.get(e.n)
        cancelled = bool(cur and cur.cancelled)
        d = cur.date if cur and not cancelled else None
        pending = False
        if c is not None and c.cancel:
            if d is not None and c.date == d:
                pending, d = True, None
        elif c is not None and c.mode == "ondemand" and d is not None:
            d = c.release
        out.append(Session(e.n, e.date, d, c.mode if c and not cancelled else None, cancelled,
                                cur.notes if cur else (), c, pending))
    return out
