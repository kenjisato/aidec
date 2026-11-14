from dataclasses import replace
from datetime import date

import pytest

from conftest import write
from aidec.data import Event, Move, load_year
from aidec.schedule import (DateEntry, Dates, ScheduleChange, ScheduleError, build_dates, facts_for,
                            read_changes, read_dates, sessions, write_dates)

ISSUED = "2027-09-01 (abc1234)"


@pytest.fixture
def yd(year_dir):
    return load_year(year_dir)


@pytest.fixture
def mon(yd):
    return replace(yd.courses[0], class_id="2027-mon3")


def _build(yd, mon, moves=(), events=None, issued=ISSUED):
    return build_dates(mon, yd.calendar_for(mon), yd.events if events is None else events, list(moves), issued)


def test_facts(yd):
    cal = yd.calendars["univa"]
    assert facts_for(date(2027, 10, 18), cal, yd.events) == ["学会（○○）（10/18〜10/20）"]
    assert facts_for(date(2027, 11, 8), cal, yd.events) == ["休講（暴風警報による全学休講）"]
    assert facts_for(date(2028, 1, 10), cal, yd.events) == []      # 締め切りは事実にしない


def test_only_trips_side_jobs_and_conferences_are_facts(yd):
    cal = yd.calendars["univa"]
    d = date(2027, 10, 20)
    kinds = {k: facts_for(d, cal, [Event(d, d, k, k, None)]) for k in ("trip", "side_job", "conference", "meeting")}
    assert kinds == {"trip": ["trip（10/20）"], "side_job": ["side_job（10/20）"],
                     "conference": ["conference（10/20）"], "meeting": []}


def test_build_dates(yd, mon):
    d = _build(yd, mon)
    assert (d.course, d.cls, d.issued) == ("macro-mon", "2027-mon3", ISSUED)
    assert len(d.dates) == 16
    assert d.dates[0] == DateEntry(1, date(2027, 9, 27), False, ())
    assert d.dates[3].notes == ("学会（○○）（10/18〜10/20）",)
    assert d.dates[6].notes == ("休講（暴風警報による全学休講）",)
    assert d.makeup_days == (date(2027, 10, 23), date(2027, 11, 20))


def test_moves_change_date_or_cancel(yd, mon):
    moves = [Move("macro-mon", 7, date(2027, 11, 20), False, ("補講日に移す",), "inbox-1"),
             Move("macro-mon", 9, None, True, ("補講しない",)),
             Move("seminar-wed", 2, None, True)]            # 他の授業の分は見ない
    d = {e.n: e for e in _build(yd, mon, moves, events=[]).dates}
    assert d[7] == DateEntry(7, date(2027, 11, 20), False, ("補講日に移す",))
    assert d[9] == DateEntry(9, None, True, ("補講しない",))
    assert d[2].date == date(2027, 10, 4) and not d[2].cancelled


def test_move_out_of_plan_is_an_error(yd, mon):
    with pytest.raises(ScheduleError, match="第 17 回"):
        _build(yd, mon, [Move("macro-mon", 17, None, True)])


def test_write_and_read_back(tmp_path, yd, mon):
    moves = [Move("macro-mon", 9, None, True, ("補講しない",))]
    d = _build(yd, mon, moves)
    p = tmp_path / "classes" / "2027-mon3" / "schedule.yaml"
    assert write_dates(p, d) is True
    text = p.read_text(encoding="utf-8")
    assert text.startswith("course: macro-mon\nclass: 2027-mon3\nissued: 2027-09-01 (abc1234)\ndates:\n")
    assert "  - {n: 1, date: 2027-09-27}\n" in text
    assert "  - {n: 4, date: 2027-10-18, notes: [学会（○○）（10/18〜10/20）]}\n" in text
    assert "  - {n: 9, cancelled: true, notes: [補講しない]}\n" in text
    assert text.endswith("makeup_days: [2027-10-23, 2027-11-20]\n")
    assert b"\r\n" not in p.read_bytes()
    assert "workdesk" not in text and "aidec" not in text
    assert read_dates(p) == d


def test_write_skips_same_content(tmp_path, yd, mon):
    p = tmp_path / "schedule.yaml"
    assert write_dates(p, _build(yd, mon)) is True
    before = p.read_text(encoding="utf-8")
    assert write_dates(p, _build(yd, mon, issued="2027-12-01 (def5678)")) is False
    assert p.read_text(encoding="utf-8") == before
    assert write_dates(p, _build(yd, mon, events=[], issued="2027-12-01 (def5678)")) is True
    assert "issued: 2027-12-01 (def5678)" in p.read_text(encoding="utf-8")


def test_write_overwrites_unreadable_file(tmp_path, yd, mon):
    p = write(tmp_path / "schedule.yaml", "course: [\n")
    assert write_dates(p, _build(yd, mon)) is True
    assert read_dates(p) == _build(yd, mon)


def test_write_needs_class(tmp_path, yd):
    d = build_dates(yd.courses[0], yd.calendar_for(yd.courses[0]), [], [], ISSUED)
    assert d.cls is None
    with pytest.raises(ScheduleError, match="class"):
        write_dates(tmp_path / "schedule.yaml", d)


# SPEC §8.8 の例（templates/schedule.yaml）の形
SCHEDULE = """\
course: stat101                  # course.id
class: "2026-mon3"
issued: "by hand, 2026-03-20"
dates:
  - {n: 1, date: 2026-04-13}
  - {n: 2, date: 2026-04-20, notes: ["Room B201 this week"]}
  - {n: 3, cancelled: true, notes: ["University holiday; not made up"]}
  - {n: 4, date: 2026-07-27}     # moved to a make-up day
  - {n: 5, date: 2026-05-11}
  - {n: 6, date: 2026-05-18}
makeup_days: [2026-07-27, 2026-08-03]
"""

CHANGES = """\
course: stat101
class: "2026-mon3"
changes:
  - {n: 2, reason: "Instructor away at a conference", mode: online}
  - {n: 5, reason: "Recorded lecture", mode: ondemand, release: 2026-05-11, prep_from: 2026-05-08}
  - {n: 6, reason: "Instructor ill", cancel: true, date: 2026-05-18, ref: "sup-0042"}
"""


def test_read_dates_spec_example(tmp_path):
    d = read_dates(write(tmp_path / "schedule.yaml", SCHEDULE))
    assert (d.course, d.cls, d.issued) == ("stat101", "2026-mon3", "by hand, 2026-03-20")
    assert d.dates[1] == DateEntry(2, date(2026, 4, 20), False, ("Room B201 this week",))
    assert d.dates[2] == DateEntry(3, None, True, ("University holiday; not made up",))
    assert d.makeup_days == (date(2026, 7, 27), date(2026, 8, 3))


@pytest.mark.parametrize("old, new, message", [
    ("course: stat101                  # course.id\n", "", "course が無い"),
    ("  - {n: 1, date: 2026-04-13}\n", "  - {n: 1}\n", r"dates\[0\]"),
    ("  - {n: 1, date: 2026-04-13}\n", "  - {n: 1, date: 2026-04-13, cancelled: true}\n", r"dates\[0\]"),
    ("  - {n: 1, date: 2026-04-13}\n", "  - {n: 1, date: 2026/04/13}\n", r"dates\[0\]"),
    ("  - {n: 1, date: 2026-04-13}\n", "  - {n: 2, date: 2026-04-13}\n", "第 2 回が二度"),
    ("  - {n: 1, date: 2026-04-13}\n", "  - {n: 1, date: 2026-04-13, room: B}\n", "room"),
    ("makeup_days: [2026-07-27, 2026-08-03]\n", "makeup_days: [soon]\n", "makeup_days"),
])
def test_bad_dates(tmp_path, old, new, message):
    p = write(tmp_path / "schedule.yaml", SCHEDULE.replace(old, new))
    with pytest.raises(ScheduleError, match=message):
        read_dates(p)


def test_read_changes_spec_example(tmp_path):
    cs = read_changes(write(tmp_path / "schedule-changes.yaml", CHANGES))
    assert cs == [
        ScheduleChange(2, "Instructor away at a conference", mode="online"),
        ScheduleChange(5, "Recorded lecture", mode="ondemand", release=date(2026, 5, 11), prep_from=date(2026, 5, 8)),
        ScheduleChange(6, "Instructor ill", cancel=True, date=date(2026, 5, 18), ref="sup-0042"),
    ]


def test_read_changes_missing_file_is_empty(tmp_path):
    assert read_changes(tmp_path / "schedule-changes.yaml") == []


def test_later_change_replaces_earlier(tmp_path):
    p = write(tmp_path / "schedule-changes.yaml",
              CHANGES + '  - {n: 2, reason: "Back in town", mode: ondemand, release: 2026-04-22}\n')
    cs = read_changes(p)
    assert [c.n for c in cs] == [2, 5, 6]
    assert (cs[0].mode, cs[0].release) == ("ondemand", date(2026, 4, 22))


@pytest.mark.parametrize("entry, message", [
    ("{n: 7, mode: online}", "reason"),
    ("{reason: x, mode: online}", "n が無い"),
    ("{n: 7, reason: x}", "mode か cancel"),
    ("{n: 7, reason: x, mode: zoom}", "mode"),
    ("{n: 7, reason: x, mode: ondemand}", "release"),
    ("{n: 7, reason: x, mode: online, release: 2026-05-11}", "release"),
    ("{n: 7, reason: x, mode: online, cancel: true, date: 2026-05-18}", "mode か cancel"),
    ("{n: 7, reason: x, cancel: true}", "date"),
    ("{n: 7, reason: x, cancel: true, date: soon}", "date"),
    ("{n: 7, reason: x, mode: online, makeup: 2026-05-18}", "makeup"),
])
def test_bad_changes(tmp_path, entry, message):
    p = write(tmp_path / "schedule-changes.yaml", CHANGES + f"  - {entry}\n")
    with pytest.raises(ScheduleError, match=message):
        read_changes(p)


def test_changes_not_a_map(tmp_path):
    with pytest.raises(ScheduleError):
        read_changes(write(tmp_path / "schedule-changes.yaml", "- {n: 1}\n"))


def _computed():
    return Dates("stat101", "2026-mon3", "", tuple(
        DateEntry(n, d) for n, d in enumerate(
            [date(2026, 4, 13), date(2026, 4, 20), date(2026, 4, 27), date(2026, 5, 4),
             date(2026, 5, 11), date(2026, 5, 18), date(2026, 5, 25)], start=1)), ())


def test_sessions(tmp_path):
    current = read_dates(write(tmp_path / "schedule.yaml", SCHEDULE))
    changes = read_changes(write(tmp_path / "schedule-changes.yaml", CHANGES))
    s = {x.n: x for x in sessions(_computed(), current, changes)}
    assert len(s) == 7
    assert (s[1].planned, s[1].date, s[1].mode, s[1].cancelled, s[1].change) == (
        date(2026, 4, 13), date(2026, 4, 13), None, False, None)
    assert (s[2].mode, s[2].date, s[2].notes) == ("online", date(2026, 4, 20), ("Room B201 this week",))
    assert (s[3].planned, s[3].date, s[3].cancelled) == (date(2026, 4, 27), None, True)
    assert (s[4].planned, s[4].date) == (date(2026, 5, 4), date(2026, 7, 27))
    assert (s[5].mode, s[5].date) == ("ondemand", date(2026, 5, 11))
    assert (s[6].date, s[6].pending, s[6].change.ref) == (None, True, "sup-0042")
    assert not s[5].pending
    assert (s[7].date, s[7].cancelled) == (None, False)          # schedule.yaml に無い回は日が無い


def test_ondemand_class_date_is_release(tmp_path):
    current = read_dates(write(tmp_path / "schedule.yaml", SCHEDULE))
    s = {x.n: x for x in sessions(_computed(), current,
                                  [ScheduleChange(1, "x", mode="ondemand", release=date(2026, 4, 15))])}
    assert (s[1].planned, s[1].date) == (date(2026, 4, 13), date(2026, 4, 15))


def test_cancel_settled_by_new_date_is_not_pending(tmp_path):
    current = read_dates(write(tmp_path / "schedule.yaml", SCHEDULE))
    s = {x.n: x for x in sessions(_computed(), current,
                                  [ScheduleChange(4, "x", cancel=True, date=date(2026, 5, 4))])}
    assert (s[4].date, s[4].pending) == (date(2026, 7, 27), False)


def test_change_for_unlisted_session_is_an_error(tmp_path):
    current = read_dates(write(tmp_path / "schedule.yaml", SCHEDULE))
    with pytest.raises(ScheduleError, match="第 7 回"):
        sessions(_computed(), current, [ScheduleChange(7, "x", mode="online")])
