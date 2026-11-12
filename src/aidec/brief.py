"""朝（または前日の夜）の知らせ。その日の授業、近い締め切りと出張、相談、準備の候補を平文で出す。"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

from . import courserepo, gitops, yamlio
from .cli import KNOWN_ERRORS, error, setup_console
from .config import data_dir
from .data import Course, YearData, load_year
from .week import _md, _md_wd, _sessions, inbox_section, prep_days

DEADLINE_DAYS = 14
PREP_DAYS = 21
FOOTER = "手元の授業レポは fetch していない"


def _title(ydir: Path, dirname: str | None) -> str | None:
    if dirname is None:
        return None
    try:
        doc = yamlio.load(ydir / dirname / "session.yaml")
        title = ((doc or {}).get("session") or {}).get("title")
    except (yamlio.YamlError, AttributeError, OSError):
        return None
    return str(title) if title else None


def _accepted(repo: Path, year: int, base: str, dirname: str | None) -> bool:
    """base の枝の review.md に Accepted: で始まる行があるか。fetch はしない。"""
    if dirname is None:
        return False
    try:
        text = gitops.git(repo, "show", f"{base}:{year}/{dirname}/review.md")
    except gitops.GitError:
        return False
    return any(line.startswith("Accepted:") for line in text.splitlines())


def _todays_sessions(yd: YearData, ghq: Path, day: date) -> list[str]:
    lines = []
    for c in yd.courses:
        ss, _ = _sessions(yd, c, ghq)
        ydir = ghq / c.repo / str(yd.year) if c.repo else None
        pattern = courserepo.layout(ydir)[0] if ydir else "{nn}"
        for s in ss:
            if s.date == day:
                title = _title(ydir, courserepo.session_dir(pattern, s.n)) if ydir else None
                lines.append(f"- {c.name}・第 {s.n} 回" + (f"・{title}" if title else ""))
    return lines


def _upcoming_events(yd: YearData, day: date) -> list[str]:
    end = day + timedelta(days=DEADLINE_DAYS)
    items = []
    for e in yd.events:
        if e.date > end or e.end < day:
            continue
        if e.kind == "deadline":
            items.append((e.date, f"- {_md(e.date)} 締め切り: {e.title}"))
        else:
            span = _md(e.date) if e.end == e.date else f"{_md(e.date)}〜{_md(e.end)}"
            items.append((max(e.date, day), f"- {span} {e.title}"))
    return [text for _, text in sorted(items, key=lambda x: x[0])]


def _candidates(yd: YearData, c: Course, ghq: Path, day: date) -> tuple[list[tuple[date, int]], str | None]:
    """準備の候補の (授業日, 回) と、判定できなかったときの一行。

    team.yaml に base があれば受け入れで、無ければ prep_on で決める。
    """
    ss, _ = _sessions(yd, c, ghq)
    ydir = ghq / c.repo / str(yd.year) if c.repo else None
    doc = courserepo.team(ydir) if ydir else {}
    base = courserepo.base_branch(doc)
    if base is None:
        held = {s.n: s.date for s in ss if s.date is not None}
        return [(held[n], n) for d, n in prep_days(ss, c.prep_on) if d == day], None
    repo = ghq / c.repo
    try:
        gitops.git(repo, "rev-parse", "--verify", "-q", f"{base}^{{commit}}")
    except gitops.GitError:
        return [], f"- {c.name}: 枝 {base} を読めない（受け入れを判定できない）"
    pattern = courserepo.layout(ydir, doc)[0]
    end = day + timedelta(days=PREP_DAYS)
    return sorted((s.date, s.n) for s in ss
                  if s.date is not None and day <= s.date <= end
                  and not _accepted(repo, yd.year, base, courserepo.session_dir(pattern, s.n))), None


def _prep_candidates(yd: YearData, ghq: Path, day: date) -> list[str]:
    busy = any(e.kind != "deadline" and e.covers(day) for e in yd.events)
    found, warnings = [], []
    for c in yd.courses:
        cands, warning = _candidates(yd, c, ghq, day)
        found += [(d, c.name, n) for d, n in cands]
        if warning:
            warnings.append(warning)
    lines = ["- この日は会議・出張があり、使える時間が少ない"] if busy else []
    lines += warnings
    return lines + [f"- {name} 第 {n} 回（{_md_wd(d)}）" for d, name, n in sorted(found)]


def brief_report(yd: YearData, ghq: Path, root: Path, day: date) -> str:
    def block(head: str, lines: list[str]) -> str:
        return "\n".join([f"## {head}", *(lines or ["- なし"])])

    blocks = [
        block(f"{day.isoformat()}（{'月火水木金土日'[day.weekday()]}）の授業", _todays_sessions(yd, ghq, day)),
        block(f"{DEADLINE_DAYS} 日以内の締め切りと出張・会議", _upcoming_events(yd, day)),
    ]
    inbox_text = inbox_section(root).strip("\n")
    if inbox_text:
        blocks.append(inbox_text)
    blocks.append(block("準備の候補", _prep_candidates(yd, ghq, day)))
    return "\n\n".join(blocks) + f"\n\n{FOOTER}\n"


def main(argv: list[str] | None = None) -> int:
    setup_console()
    ap = argparse.ArgumentParser(prog="aidec brief", description="朝と前日の夜の知らせ")
    ap.add_argument("year", type=int)
    ap.add_argument("--date", type=date.fromisoformat, default=date.today(), help="今日（既定: 今日）")
    ap.add_argument("--evening", action="store_true", help="翌日の分を出す")
    ap.add_argument("--root", type=Path, default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    try:
        root = args.root or data_dir()
        yd = load_year(root / str(args.year))
        day = args.date + timedelta(days=1) if args.evening else args.date
        out = brief_report(yd, gitops.ghq_root(), root, day)
    except KNOWN_ERRORS as e:
        error(str(e))
        return 1
    print(out, end="")
    return 0
