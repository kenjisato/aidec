"""授業からの報告（inbox/<id>.md）。書式は plugin/INTERFACE.md のとおり。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .requests import read_front


class ReportError(ValueError):
    pass


@dataclass
class Report:
    id: str
    frm: str
    date: date
    re: str | None
    dates: list[date]
    gap: str | None
    body: str


def parse_report(text: str, where: str) -> Report:
    meta, body = read_front(text, where, ReportError)
    for k in ("from", "date"):
        if k not in meta:
            raise ReportError(f"{where}: {k} が無い")
    if not isinstance(meta["date"], date):
        raise ReportError(f"{where}: date が日付として読めない")
    dates = list(meta.get("dates") or [])
    if not all(isinstance(d, date) for d in dates):
        raise ReportError(f"{where}: dates に日付として読めないものがある")
    re_, gap = meta.get("re"), meta.get("gap")
    return Report(Path(where).stem, str(meta["from"]), meta["date"], None if re_ is None else str(re_),
                  dates, None if gap is None else str(gap), body)


def load_reports(inbox: Path) -> list[Report]:
    """未処理の報告（inbox/ の直下だけ。見直し済みの done/ は読まない）。"""
    if not inbox.is_dir():
        return []
    return [parse_report(p.read_text(encoding="utf-8"), p.name) for p in sorted(inbox.glob("*.md"))]
