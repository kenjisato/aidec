"""授業レポの <年度>/schedule.yaml。

上半分（course・issued・plan・makeup_days）を workdesk が書き、下半分（changes）を授業レポが書く。
各回の実際の予定は plan に changes を重ねたものである。
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
from .data import Course, Event

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


def write_reviewed(path: Path, course: str, changes: list[Change], course_sha: str, day: date) -> None:
    """workdesk が見直したときの changes の控え。check が、報告の無い変更を見つけるのに使う。"""
    data = CommentedMap()
    data["course"] = course
    data["reviewed"] = day
    data["course_commit"] = course_sha
    data["changes"] = CommentedSeq(_change_map(c) for c in sorted(changes, key=lambda c: c.n))
    yamlio.dump(data, path)


def read_reviewed(path: Path) -> list[Change] | None:
    if not path.exists():
        return None
    data = _load(path)
    if not isinstance(data, dict):
        raise ScheduleError(f"{path}: 対応づけになっていない")
    return _parse_changes(data.get("changes"), str(path))


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
