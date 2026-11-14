"""授業レポの日程ファイル（IK SPEC §8.8）。

新しい書式: class root（classes/<class id>/）の schedule.yaml を aidec が書き（Dates）、
schedule-changes.yaml を授業レポの director が書く（ScheduleChange。aidec は読むだけ）。
各回の授業の日は sessions() が重ねる。

旧い書式（<年度>/schedule.yaml の plan と changes。WorkdeskPart・Change・Session）は、
呼び出し元（issue・week・check・brief）が新しい書式に移るまで残す。
"""
from __future__ import annotations

import re
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
CHANGE_KEYS = {"n", "mode", "cancel", "makeup", "reason", "note", "prep_from", "release"}
_HEADER_PLAN = "workdesk が書く: 学事暦から決まる各回の日付と、その日の事実"
_HEADER_CHANGES = "授業レポが書く: その授業の事情で plan から変えたこと"


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


@dataclass(frozen=True)
class PlanEntry:
    n: int
    date: date
    facts: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkdeskPart:
    course: str
    issued: str
    plan: tuple[PlanEntry, ...]
    makeup_days: tuple[date, ...]

    def same_content(self, other: "WorkdeskPart") -> bool:
        return replace(self, issued="") == replace(other, issued="")


def build_part(course: Course, cal: Calendar, events: list[Event], issued: str) -> WorkdeskPart:
    plan = tuple(PlanEntry(s.n, s.date, tuple(facts_for(s.date, cal, events)))
                 for s in plan_sessions(cal, course.term, course.slot, course.sessions))
    span = cal.terms[course.term]
    return WorkdeskPart(course.id, issued, plan, tuple(d for d in cal.makeup_days if d in span))


def _plan_seq(part: WorkdeskPart) -> CommentedSeq:
    items = []
    for e in part.plan:
        m = {"n": e.n, "date": e.date}
        if e.facts:
            m["facts"] = yamlio.flow_seq(list(e.facts))
        items.append(yamlio.flow_map(m))
    return CommentedSeq(items)


def _set_part(data: CommentedMap, part: WorkdeskPart) -> None:
    data["course"] = part.course
    data["issued"] = part.issued
    data["plan"] = _plan_seq(part)
    data["makeup_days"] = yamlio.flow_seq(list(part.makeup_days))


_TOP_KEY = re.compile(r"^([A-Za-z_][\w-]*)\s*:(\s|$)")


def _top_blocks(text: str, where: str) -> tuple[list[list], list[str]]:
    """最上位の欄ごとに [欄名, 前に置かれたコメント・空行, 欄の行] に分ける。

    末尾のコメント・空行は別に返す。欄の中の字下げした行・行頭の '-' は、その欄の行とする。
    """
    blocks: list[list] = []
    trivia: list[str] = []
    for line in text.splitlines(keepends=True):
        m = _TOP_KEY.match(line)
        if m:
            blocks.append([m.group(1), trivia, [line]])
            trivia = []
        elif not line.strip() or line.startswith("#") or (not blocks and line.strip() == "---"):
            trivia.append(line)
        elif blocks and (line[:1].isspace() or line.startswith("-")):
            blocks[-1][2].extend(trivia)
            trivia = []
            blocks[-1][2].append(line)
        else:
            raise ScheduleError(f"{where}: 最上位の欄の形が読めない行がある: {line.rstrip()!r}")
    return blocks, trivia


def _splice(text: str, part: WorkdeskPart, where: str) -> str:
    """workdesk の 4 つの欄の行だけを差し替える。それ以外の行は一字も変えない。"""
    data = CommentedMap()
    _set_part(data, part)
    rendered = {k: yamlio.dumps(CommentedMap({k: v})) for k, v in data.items()}
    blocks, tail = _top_blocks(text, where)
    for b in blocks:
        if b[0] in rendered:
            b[2] = [rendered[b[0]]]
    names = [b[0] for b in blocks]
    missing = [k for k in rendered if k not in names]
    at = names.index("changes") if "changes" in names else len(blocks)
    blocks[at:at] = [[k, [], [rendered[k]]] for k in missing]
    if "changes" not in names:
        blocks.append(["changes", [], ["changes: []\n"]])
    out = "".join("".join(tr) + "".join(lines) for _, tr, lines in blocks) + "".join(tail)
    if not out.endswith("\n"):
        out += "\n"
    return out


def write_part(path: Path, part: WorkdeskPart) -> None:
    """workdesk の部分だけを書き換える。changes とコメントには触れない。"""
    if not path.exists():
        data = CommentedMap()
        _set_part(data, part)
        data["changes"] = CommentedSeq()
        data.yaml_set_comment_before_after_key("plan", before=_HEADER_PLAN)
        data.yaml_set_comment_before_after_key("changes", before=_HEADER_CHANGES)
        yamlio.dump(data, path)
        return
    current = _load(path)
    if current is not None and not isinstance(current, dict):
        raise ScheduleError(f"{path}: 対応づけ（course: ... の形）になっていない")
    with open(path, encoding="utf-8") as f:
        out = _splice(f.read(), part, str(path))
    try:
        yamlio.loads(out)
    except Exception as e:     # 差し替えた結果が読めないなら書かない
        raise ScheduleError(f"{path}: 書き換えると読めなくなる（{e}）") from None
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)


def write_issued_copy(path: Path, part: WorkdeskPart) -> None:
    data = CommentedMap()
    _set_part(data, part)
    yamlio.dump(data, path)


def _part_from_map(data, where: str) -> WorkdeskPart:
    if not isinstance(data, dict):
        raise ScheduleError(f"{where}: 対応づけ（course: ... の形）になっていない")
    for k in ("course", "issued", "plan"):
        if k not in data:
            raise ScheduleError(f"{where}: {k} が無い")
    plan = []
    for i, e in enumerate(data["plan"] or []):
        if not isinstance(e, dict) or "n" not in e or not isinstance(e.get("date"), date):
            raise ScheduleError(f"{where}: plan[{i}] は {{n: 1, date: YYYY-MM-DD}} の形で書く")
        plan.append(PlanEntry(int(e["n"]), e["date"], tuple(str(f) for f in e.get("facts") or [])))
    return WorkdeskPart(str(data["course"]), str(data["issued"]), tuple(plan),
                        tuple(data.get("makeup_days") or []))


def _load(path: Path):
    try:
        return yamlio.load(path)
    except yamlio.YamlError as e:
        raise ScheduleError(f"{path}: {e}") from None


def read_part(path: Path) -> WorkdeskPart:
    """workdesk の部分だけを読む。changes は見ない。"""
    return _part_from_map(_load(path), str(path))


@dataclass(frozen=True)
class Change:
    n: int
    mode: str | None = None
    cancel: bool = False
    makeup: date | None = None
    reason: str | None = None
    note: str | None = None
    prep_from: date | None = None      # 早めの準備が要る回で、準備を始める日
    release: date | None = None        # オンデマンドなどの公開日


def _parse_changes(raw, where: str) -> list[Change]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ScheduleError(f"{where}: changes は列で書く")
    out: list[Change] = []
    for i, c in enumerate(raw):
        at = f"{where}: changes[{i}]"
        if not isinstance(c, dict) or "n" not in c:
            raise ScheduleError(f"{at}: n が無い")
        unknown = set(c) - CHANGE_KEYS
        if unknown:
            raise ScheduleError(f"{at}: 知らない欄 {', '.join(sorted(unknown))}"
                                f"（使える欄: {', '.join(sorted(CHANGE_KEYS))}）")
        for k in ("makeup", "prep_from", "release"):
            v = c.get(k)
            if v is not None and not isinstance(v, date):
                raise ScheduleError(f"{at}: {k} が日付として読めない: {v!r}（YYYY-MM-DD で書く）")
        makeup = c.get("makeup")
        if makeup is not None and not c.get("cancel"):
            raise ScheduleError(f"{at}: makeup は cancel: true と一緒に書く")
        n = int(c["n"])
        if any(x.n == n for x in out):
            raise ScheduleError(f"{at}: 第 {n} 回が二度書かれている")
        out.append(Change(n, c.get("mode"), bool(c.get("cancel", False)), makeup,
                          c.get("reason"), c.get("note"), c.get("prep_from"), c.get("release")))
    return out


def _change_map(c: Change) -> CommentedMap:
    d: dict = {"n": c.n}
    for k in ("mode", "cancel", "makeup", "reason", "note", "prep_from", "release"):
        v = getattr(c, k)
        if v not in (None, False):
            d[k] = v
    return yamlio.flow_map(d)


def load_schedule(path: Path) -> tuple[WorkdeskPart, list[Change]]:
    data = _load(path)
    part = _part_from_map(data, str(path))
    return part, _parse_changes(data.get("changes"), str(path))


@dataclass(frozen=True)
class Session:
    n: int
    planned: date
    date: date | None          # 実際に行う日。休講で補講が未定なら None
    mode: str | None
    cancelled: bool
    facts: tuple[str, ...]
    change: Change | None


def effective_sessions(plan: tuple[PlanEntry, ...], changes: list[Change]) -> list[Session]:
    ns = {e.n for e in plan}
    for c in changes:
        if c.n not in ns:
            raise ScheduleError(f"changes の第 {c.n} 回は plan に無い")
    by_n = {c.n: c for c in changes}
    out = []
    for e in plan:
        c = by_n.get(e.n)
        if c is None:
            out.append(Session(e.n, e.date, e.date, None, False, e.facts, None))
        elif c.cancel:
            out.append(Session(e.n, e.date, c.makeup, c.mode, True, e.facts, c))
        else:
            out.append(Session(e.n, e.date, e.date, c.mode, False, e.facts, c))
    return out


# ---- 新しい書式（IK SPEC §8.8）: classes/<class id>/schedule.yaml と schedule-changes.yaml ----

_DATES_KEYS = {"course", "class", "issued", "dates", "makeup_days"}
_DATE_ENTRY_KEYS = {"n", "date", "cancelled", "notes"}
_SCHEDULE_CHANGE_KEYS = {"n", "reason", "mode", "release", "prep_from", "cancel", "date", "ref"}


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

    course_id は書く course: の値（class root の course.yaml の course.id）。無ければ courses.yaml の id。
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
class ScheduleChange:
    """schedule-changes.yaml の 1 行。mode（online・ondemand）か cancel のどちらか。"""
    n: int
    reason: str
    mode: str | None = None
    release: date | None = None        # ondemand: 学生が教材を受け取る日（授業の日）
    prep_from: date | None = None      # ondemand: 取りかかれる最初の日
    cancel: bool = False
    date: date | None = None           # cancel: 取りやめる、予定の日
    ref: str | None = None             # 上に上げた変更の inbox の ref


def read_changes(path: Path) -> list[ScheduleChange]:
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
    out: dict[int, ScheduleChange] = {}
    for i, c in enumerate(raw):
        at = f"{where}: changes[{i}]"
        if not isinstance(c, dict) or "n" not in c:
            raise ScheduleError(f"{at}: n が無い")
        if not _is_int(c["n"]) or c["n"] < 1:
            raise ScheduleError(f"{at}: n は 1 以上の整数で書く")
        unknown = set(c) - _SCHEDULE_CHANGE_KEYS
        if unknown:
            raise ScheduleError(f"{at}: 知らない欄 {', '.join(sorted(map(str, unknown)))}"
                                f"（使える欄: {', '.join(sorted(_SCHEDULE_CHANGE_KEYS))}）")
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
        out[n] = ScheduleChange(n, str(reason), c.get("mode"), c.get("release"), c.get("prep_from"),
                                "cancel" in c, c.get("date"), None if ref is None else str(ref))
    return sorted(out.values(), key=lambda x: x.n)


@dataclass(frozen=True)
class ClassSession:
    n: int
    planned: date | None               # 学事暦で計算した日（cancelled の回にも残る）
    date: date | None                  # 授業の日。ondemand なら release。cancelled・未定・載っていない回は None
    mode: str | None
    cancelled: bool                    # schedule.yaml で cancelled: true
    notes: tuple[str, ...]
    change: ScheduleChange | None
    pending: bool = False              # cancel の date が載っている日のまま: 日は佐藤に聞く


def sessions(computed: Dates, current: Dates, changes: list[ScheduleChange]) -> list[ClassSession]:
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
        out.append(ClassSession(e.n, e.date, d, c.mode if c and not cancelled else None, cancelled,
                                cur.notes if cur else (), c, pending))
    return out
