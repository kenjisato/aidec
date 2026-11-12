from datetime import date

import pytest

from classdays.calendar import CalendarError, calendar_from_dict
from conftest import CALENDAR_UNIVA_2027, safe_load


def test_fields(cal):
    assert cal.university == "univa"
    assert cal.year == 2027
    assert cal.terms["fall"].start == date(2027, 9, 27)
    assert date(2027, 11, 3) in cal.no_class
    assert cal.makeup_days == (date(2027, 10, 23), date(2027, 11, 20))
    assert cal.amendments[0].add_no_class == (date(2027, 11, 8),)


def test_weekday_of_follows_swap(cal):
    assert cal.weekday_of(date(2027, 12, 22)) == "mon"
    assert cal.weekday_of(date(2027, 12, 15)) == "wed"


def test_base_class_day_ignores_amendments(cal):
    assert cal.is_base_class_day(date(2027, 11, 8), "fall")
    assert not cal.is_base_class_day(date(2027, 11, 3), "fall")      # 休講日
    assert not cal.is_base_class_day(date(2028, 1, 26), "fall")      # 試験期間
    assert not cal.is_base_class_day(date(2027, 9, 20), "fall")      # 学期の前


def test_is_closed(cal):
    assert cal.is_closed(date(2027, 11, 3))
    assert cal.is_closed(date(2027, 11, 8))                           # amendments
    assert cal.is_closed(date(2028, 1, 27))                           # 試験期間
    assert not cal.is_closed(date(2027, 11, 20))


def test_amendment_closing(cal):
    assert cal.amendment_closing(date(2027, 11, 8)).source == "暴風警報による全学休講"
    assert cal.amendment_closing(date(2027, 11, 9)) is None


def test_term_of(cal):
    assert cal.term_of(date(2027, 10, 1)) == "fall"
    assert cal.term_of(date(2027, 9, 1)) is None


def test_exams_as_list():
    d = safe_load(CALENDAR_UNIVA_2027)
    d["exams"] = [{"start": date(2027, 7, 26), "end": date(2027, 8, 1)},
                  {"start": date(2028, 1, 26), "end": date(2028, 2, 1)}]
    cal = calendar_from_dict(d)
    assert cal.is_exam(date(2027, 7, 27)) and cal.is_exam(date(2028, 1, 27))


def test_date_written_with_slashes_is_an_error():
    d = safe_load(CALENDAR_UNIVA_2027)
    d["no_class"] = ["2027/11/03"]
    with pytest.raises(CalendarError, match=r"no_class\[0\].*2027/11/03"):
        calendar_from_dict(d)


def test_unknown_top_key_is_an_error():
    d = safe_load(CALENDAR_UNIVA_2027)
    d["holidays"] = []
    with pytest.raises(CalendarError, match="holidays"):
        calendar_from_dict(d)


def test_unknown_amendment_key_is_an_error():
    d = safe_load(CALENDAR_UNIVA_2027)
    d["amendments"][0]["add_swap"] = []
    with pytest.raises(CalendarError, match=r"amendments\[0\].*add_swap"):
        calendar_from_dict(d)


def test_bad_swap_is_an_error():
    d = safe_load(CALENDAR_UNIVA_2027)
    d["swap"] = [{"date": date(2027, 12, 22), "as": "monday"}]
    with pytest.raises(CalendarError, match=r"swap\[0\]"):
        calendar_from_dict(d)


def test_makeup_weekday():
    d = safe_load(CALENDAR_UNIVA_2027)
    assert calendar_from_dict(d).makeup_weekday is None              # 書かなければ見ない
    d["makeup_weekday"] = "sat"
    assert calendar_from_dict(d).makeup_weekday == "sat"
    d["makeup_weekday"] = "saturday"
    with pytest.raises(CalendarError, match="makeup_weekday"):
        calendar_from_dict(d)


def test_span_end_before_start_is_an_error():
    d = safe_load(CALENDAR_UNIVA_2027)
    d["terms"]["fall"] = {"start": date(2028, 1, 25), "end": date(2027, 9, 27)}
    with pytest.raises(CalendarError, match="terms.fall"):
        calendar_from_dict(d)


def test_impossible_date_names_the_file(tmp_path):
    from classdays.calendar import load_calendar
    p = tmp_path / "calendar-univa.yaml"
    p.write_text(CALENDAR_UNIVA_2027.replace("2028-01-25", "2027-11-31"), encoding="utf-8")
    with pytest.raises(CalendarError, match="calendar-univa.yaml"):
        load_calendar(p)
