from datetime import date

import pytest

from classdays.plan import Slot
from conftest import write
from aidec.data import DataError, load_year


def test_load_year(year_dir):
    yd = load_year(year_dir)
    assert yd.year == 2027
    assert set(yd.calendars) == {"univa"}
    c = yd.courses[0]
    assert (c.id, c.repo, c.calendar, c.term, c.slot, c.sessions) == (
        "macro-mon", "github.com/example/macro-mon", "univa", "fall", Slot("mon", 3), 16)
    assert yd.calendar_for(c).university == "univa"
    trip, deadline = yd.events
    assert trip.covers(date(2027, 10, 19)) and not trip.covers(date(2027, 10, 21))
    assert deadline.end == deadline.date
    assert deadline.prep_span() == (date(2027, 12, 27), date(2028, 1, 9))
    assert trip.prep_span() is None


def test_events_file_is_optional(year_dir):
    (year_dir / "events.yaml").unlink()
    assert load_year(year_dir).events == []


def test_course_without_repo(year_dir):
    write(year_dir / "courses.yaml",
          "- {id: x, calendar: univa, term: fall, slot: mon-1, sessions: 15}\n")
    assert load_year(year_dir).courses[0].repo is None


@pytest.mark.parametrize("line, message", [
    ("- {id: x, calendar: univz, term: fall, slot: mon-1, sessions: 15}", "学事暦 univz が無い"),
    ("- {id: x, calendar: univa, term: spring, slot: mon-1, sessions: 15}", "学期 spring"),
    ("- {id: x, calendar: univa, term: fall, slot: mon1, sessions: 15}", "mon-3 の形"),
    ("- {id: x, calendar: univa, term: fall, slot: mon-1, sessions: 15, room: A}", "room"),
    ("- {id: x, repo: C:/ghq/x, calendar: univa, term: fall, slot: mon-1, sessions: 15}", "相対パス"),
    ("- {id: x, repo: ../x, calendar: univa, term: fall, slot: mon-1, sessions: 15}", "相対パス"),
    ("- {calendar: univa, term: fall, slot: mon-1, sessions: 15}", "id が無い"),
])
def test_bad_course(year_dir, line, message):
    write(year_dir / "courses.yaml", line + "\n")
    with pytest.raises(DataError, match=message):
        load_year(year_dir)


def test_duplicate_course_id(year_dir):
    write(year_dir / "courses.yaml",
          "- {id: x, calendar: univa, term: fall, slot: mon-1, sessions: 15}\n"
          "- {id: x, calendar: univa, term: fall, slot: tue-1, sessions: 15}\n")
    with pytest.raises(DataError, match="x が二つある"):
        load_year(year_dir)


@pytest.mark.parametrize("line, message", [
    ("- {date: 2027-10-20, end: 2027-10-18, kind: trip, title: t}", "end が date より前"),
    ("- {date: 2028-01-10, kind: deadline, title: t, prep: 2}", "prep は 2w の形"),
    ("- {date: 2027/10/18, kind: trip, title: t}", "日付として読めない"),
    ("- {date: 2027-10-18, title: t}", "kind が無い"),
])
def test_bad_event(year_dir, line, message):
    write(year_dir / "events.yaml", line + "\n")
    with pytest.raises(DataError, match=message):
        load_year(year_dir)


def test_calendar_file_name_must_match_university(year_dir):
    (year_dir / "calendar-univa.yaml").rename(year_dir / "calendar-univb.yaml")
    with pytest.raises(DataError, match="calendar-univb.yaml"):
        load_year(year_dir)


def test_prep_on_and_research_days(year_dir):
    write(year_dir / "courses.yaml",
          "- {id: x, calendar: univa, term: fall, slot: mon-1, sessions: 15, prep_on: [tue, wed]}\n"
          "- {id: y, calendar: univa, term: fall, slot: thu-2, sessions: 15}\n")
    write(year_dir / "settings.yaml", "research_days: [fri]\n")
    yd = load_year(year_dir)
    assert yd.courses[0].prep_on == ("tue", "wed")
    assert yd.courses[1].prep_on == ()
    assert yd.research_days == ("fri",)


def test_course_label_and_event_note(year_dir):
    write(year_dir / "courses.yaml",
          "- {id: univa-macro-analysis2, label: analysis2, calendar: univa, term: fall, slot: mon-1, sessions: 15}\n")
    write(year_dir / "events.yaml", "- {date: 2027-10-20, kind: meeting, title: faculty mtg, note: 13:30 on Zoom}\n")
    yd = load_year(year_dir)
    assert yd.courses[0].label == "analysis2"
    assert yd.events[0].note == "13:30 on Zoom"


def test_settings_file_is_optional(year_dir):
    assert load_year(year_dir).research_days == ()


@pytest.mark.parametrize("courses, settings, message", [
    ("- {id: x, calendar: univa, term: fall, slot: mon-1, sessions: 15, prep_on: [tuesday]}\n", None, "prep_on"),
    (None, "research_days: [friday]\n", "research_days"),
    (None, "holidays: [fri]\n", "holidays"),
])
def test_bad_prep_settings(year_dir, courses, settings, message):
    if courses:
        write(year_dir / "courses.yaml", courses)
    if settings:
        write(year_dir / "settings.yaml", settings)
    with pytest.raises(DataError, match=message):
        load_year(year_dir)


def test_impossible_event_date_names_the_file(year_dir):
    write(year_dir / "events.yaml", "- {date: 2027-11-31, kind: trip, title: t}\n")
    with pytest.raises(DataError, match="events.yaml"):
        load_year(year_dir)
