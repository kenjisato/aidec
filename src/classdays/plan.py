"""曜日・時限と回数から、各回を何月何日に行うかを出す。

元の学事暦だけを使い、年度途中の変更（amendments）は見ない。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .calendar import WEEKDAYS, Calendar


class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class Slot:
    weekday: str
    period: int


@dataclass(frozen=True)
class PlannedSession:
    n: int
    date: date


def parse_slot(text: str) -> Slot:
    """'mon-3' を曜日と時限に分ける。"""
    day, sep, period = str(text).partition("-")
    if not sep or day not in WEEKDAYS or not period.isdigit():
        raise PlanError(f"slot は mon-3 の形で書く: {text!r}")
    return Slot(day, int(period))


def class_dates(cal: Calendar, term: str, weekday: str) -> list[date]:
    if term not in cal.terms:
        raise PlanError(f"学事暦 {cal.university} {cal.year} に学期 {term} が無い")
    span = cal.terms[term]
    out = []
    d = span.start
    while d <= span.end:
        if cal.weekday_of(d) == weekday and cal.is_base_class_day(d, term):
            out.append(d)
        d += timedelta(days=1)
    return out


def plan_sessions(cal: Calendar, term: str, slot: Slot, sessions: int) -> list[PlannedSession]:
    dates = class_dates(cal, term, slot.weekday)
    if len(dates) < sessions:
        raise PlanError(f"{cal.university} {cal.year} {term} の {slot.weekday} の授業日は "
                        f"{len(dates)} 日で、{sessions} 回に足りない")
    return [PlannedSession(i + 1, d) for i, d in enumerate(dates[:sessions])]
