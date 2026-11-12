from datetime import date

import pytest

from classdays.plan import PlanError, Slot, class_dates, parse_slot, plan_sessions


def test_parse_slot():
    assert parse_slot("mon-3") == Slot("mon", 3)
    for bad in ("mon3", "monday-3", "mon-", "mon-x"):
        with pytest.raises(PlanError, match="mon-3 の形"):
            parse_slot(bad)


def test_monday_plan_uses_swap_and_skips_no_class(cal):
    plan = plan_sessions(cal, "fall", Slot("mon", 3), 16)
    assert [p.n for p in plan] == list(range(1, 17))
    assert plan[0].date == date(2027, 9, 27)
    assert plan[3].date == date(2027, 10, 18)
    assert plan[6].date == date(2027, 11, 8)       # amendments の休講でも番号は振り直さない
    assert plan[13].date == date(2027, 12, 22)     # 水曜だが月曜の授業を行う日
    assert plan[14].date == date(2028, 1, 10)      # 12/27・1/3 は休講日
    assert plan[15].date == date(2028, 1, 17)


def test_wednesday_dates_skip_holiday_and_swapped_day(cal):
    dates = class_dates(cal, "fall", "wed")
    assert date(2027, 11, 3) not in dates
    assert date(2027, 12, 22) not in dates
    assert len(dates) == 15


def test_too_few_class_days_is_an_error(cal):
    with pytest.raises(PlanError, match=r"univa 2027 fall の wed の授業日は 15 日で、16 回に足りない"):
        plan_sessions(cal, "fall", Slot("wed", 2), 16)


def test_unknown_term_is_an_error(cal):
    with pytest.raises(PlanError, match="spring"):
        plan_sessions(cal, "spring", Slot("mon", 1), 15)
