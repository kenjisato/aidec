from datetime import date

import pytest

from conftest import write
from aidec.data import load_year
from aidec.schedule import (Change, ScheduleError, build_part, effective_sessions, facts_for,
                               load_schedule, read_part, write_issued_copy, write_part)


@pytest.fixture
def yd(year_dir):
    return load_year(year_dir)


@pytest.fixture
def mon_part(yd):
    c = yd.courses[0]
    return build_part(c, yd.calendar_for(c), yd.events, "2027-09-01 (workdesk abc1234)")


def test_facts(yd):
    cal = yd.calendars["univa"]
    assert facts_for(date(2027, 10, 18), cal, yd.events) == ["学会（○○）（10/18〜10/20）"]
    assert facts_for(date(2027, 11, 8), cal, yd.events) == ["休講（暴風警報による全学休講）"]
    assert facts_for(date(2028, 1, 10), cal, yd.events) == []      # 締め切りは事実にしない


def test_only_trips_side_jobs_and_conferences_are_facts(yd):
    from aidec.data import Event
    cal = yd.calendars["univa"]
    d = date(2027, 10, 20)
    kinds = {k: facts_for(d, cal, [Event(d, d, k, k, None)]) for k in ("trip", "side_job", "conference", "meeting")}
    assert kinds == {"trip": ["trip（10/20）"], "side_job": ["side_job（10/20）"],
                     "conference": ["conference（10/20）"], "meeting": []}


def test_build_part(mon_part):
    assert mon_part.course == "macro-mon"
    assert len(mon_part.plan) == 16
    assert mon_part.plan[3].facts == ("学会（○○）（10/18〜10/20）",)
    assert mon_part.plan[6].facts == ("休講（暴風警報による全学休講）",)
    assert mon_part.plan[0].facts == ()
    assert mon_part.makeup_days == (date(2027, 10, 23), date(2027, 11, 20))


def test_write_new_file(tmp_path, mon_part):
    p = tmp_path / "2027" / "schedule.yaml"
    write_part(p, mon_part)
    text = p.read_text(encoding="utf-8")
    assert text.startswith("course: macro-mon\nissued: 2027-09-01 (workdesk abc1234)\n")
    assert "  - {n: 4, date: 2027-10-18, facts: [学会（○○）（10/18〜10/20）]}\n" in text
    assert "  - {n: 1, date: 2027-09-27}\n" in text
    assert "makeup_days: [2027-10-23, 2027-11-20]\n" in text
    assert "# workdesk が書く" in text and "# 授業レポが書く" in text
    assert text.rstrip().endswith("changes: []")
    assert b"\r\n" not in p.read_bytes()


def test_rewrite_keeps_changes_and_comments(tmp_path, yd, mon_part):
    p = tmp_path / "schedule.yaml"
    write_part(p, mon_part)
    text = p.read_text(encoding="utf-8").replace(
        "changes: []",
        "changes:\n  - {n: 4, mode: zoom, reason: 出張}   # 学生に連絡済み\n"
        "  - {n: 7, cancel: true, reason: 全学休講, makeup: 2027-11-20}\n")
    write(p, text)
    c = yd.courses[0]
    write_part(p, build_part(c, yd.calendar_for(c), [], "2027-09-02 (workdesk def5678)"))
    after = p.read_text(encoding="utf-8")
    assert "issued: 2027-09-02 (workdesk def5678)" in after
    assert "  - {n: 4, date: 2027-10-18}\n" in after                # 事実が消えた
    tail = text[text.index("# 授業レポが書く"):]
    assert after.endswith(tail)                                     # 下半分は一字も変わらない


def _rewrite_after(p, yd):
    c = yd.courses[0]
    write_part(p, build_part(c, yd.calendar_for(c), [], "2027-09-02 (workdesk def5678)"))
    return p.read_text(encoding="utf-8")


def test_rewrite_keeps_comment_after_block_style_makeup_days(tmp_path, yd, mon_part):
    p = tmp_path / "schedule.yaml"
    write_part(p, mon_part)
    text = p.read_text(encoding="utf-8").replace(
        "makeup_days: [2027-10-23, 2027-11-20]\n",
        "makeup_days:\n  - 2027-10-23\n  - 2027-11-20\n\n")
    text = text.replace("changes: []", "changes:\n  - {n: 4, mode: zoom}   # 連絡済み")
    write(p, text)
    after = _rewrite_after(p, yd)
    tail = text[text.index("\n\n# 授業レポが書く") + 1:]
    assert after.endswith(tail)
    assert "  - {n: 4, date: 2027-10-18}\n" in after


def test_rewrite_inserts_missing_key_before_changes(tmp_path, yd, mon_part):
    p = tmp_path / "schedule.yaml"
    write_part(p, mon_part)
    text = p.read_text(encoding="utf-8").replace("makeup_days: [2027-10-23, 2027-11-20]\n", "")
    write(p, text)
    after = _rewrite_after(p, yd)
    tail = text[text.index("# 授業レポが書く"):]
    assert after.endswith(tail)
    assert after.index("makeup_days:") < after.index("# 授業レポが書く")


def test_rewrite_keeps_comment_on_top_and_unknown_keys(tmp_path, yd, mon_part):
    p = tmp_path / "schedule.yaml"
    write_part(p, mon_part)
    text = "# この授業の日程（2027 後期）\n" + p.read_text(encoding="utf-8") + "memo: 授業側のメモ  # 残す\n"
    write(p, text)
    after = _rewrite_after(p, yd)
    assert after.startswith("# この授業の日程（2027 後期）\ncourse: macro-mon\n")
    assert after.endswith("memo: 授業側のメモ  # 残す\n")


def test_issued_copy_round_trip(tmp_path, mon_part):
    p = tmp_path / "issued" / "macro-mon.yaml"
    write_issued_copy(p, mon_part)
    assert read_part(p) == mon_part


def test_same_content_ignores_issued(yd, mon_part):
    c = yd.courses[0]
    other = build_part(c, yd.calendar_for(c), yd.events, "2027-12-01 (workdesk 0000000)")
    assert mon_part.same_content(other)
    assert not mon_part.same_content(build_part(c, yd.calendar_for(c), [], "x"))


def _schedule_with(tmp_path, mon_part, changes_text):
    p = tmp_path / "schedule.yaml"
    write_part(p, mon_part)
    write(p, p.read_text(encoding="utf-8").replace("changes: []", changes_text))
    return p


def test_load_schedule_and_effective_sessions(tmp_path, mon_part):
    p = _schedule_with(tmp_path, mon_part,
                       "changes:\n  - {n: 4, mode: zoom, reason: 出張}\n"
                       "  - {n: 7, cancel: true, reason: 全学休講, makeup: 2027-11-20}\n"
                       "  - {n: 9, cancel: true, reason: 体調不良}\n")
    part, changes = load_schedule(p)
    assert part == mon_part
    assert changes[0] == Change(4, "zoom", False, None, "出張", None)
    s = {x.n: x for x in effective_sessions(part.plan, changes)}
    assert (s[1].date, s[1].mode, s[1].cancelled, s[1].change) == (date(2027, 9, 27), None, False, None)
    assert (s[4].date, s[4].mode) == (date(2027, 10, 18), "zoom")
    assert (s[7].planned, s[7].date, s[7].cancelled) == (date(2027, 11, 8), date(2027, 11, 20), True)
    assert (s[9].date, s[9].cancelled) == (None, True)
    assert s[7].facts == ("休講（暴風警報による全学休講）",)


def test_prep_from_and_release(tmp_path, mon_part):
    p = _schedule_with(tmp_path, mon_part,
                       "changes:\n  - {n: 15, mode: ondemand, prep_from: 2027-12-21, release: 2028-01-05}\n")
    _, changes = load_schedule(p)
    assert (changes[0].prep_from, changes[0].release) == (date(2027, 12, 21), date(2028, 1, 5))


@pytest.mark.parametrize("changes_text, message", [
    ("changes:\n  - {n: 15, prep_from: 2027/12/21}\n", "prep_from が日付として読めない"),
    ("changes:\n  - {n: 15, release: soon}\n", "release が日付として読めない"),
    ("changes:\n  - {n: 7, cancel: true, makup: 2027-11-20}\n", r"makup.*使える欄"),
    ("changes:\n  - {n: 7, makeup: 2027-11-20}\n", "cancel: true と一緒に"),
    ("changes:\n  - {n: 7, cancel: true, makeup: 2027/11/20}\n", "日付として読めない"),
    ("changes:\n  - {mode: zoom}\n", "n が無い"),
    ("changes:\n  - {n: 4, mode: zoom}\n  - {n: 4, note: x}\n", "第 4 回が二度"),
    ("changes:\n  - {n: 17, mode: zoom}\n", "第 17 回は plan に無い"),
])
def test_bad_changes(tmp_path, mon_part, changes_text, message):
    p = _schedule_with(tmp_path, mon_part, changes_text)
    with pytest.raises(ScheduleError, match=message):
        part, changes = load_schedule(p)
        effective_sessions(part.plan, changes)


def test_reviewed_copy_round_trip(tmp_path):
    from aidec.schedule import read_reviewed, write_reviewed
    p = tmp_path / "reviewed" / "macro-mon.yaml"
    assert read_reviewed(p) is None
    changes = [Change(4, "zoom", reason="出張"), Change(7, cancel=True, makeup=date(2027, 11, 20)),
               Change(15, "ondemand", prep_from=date(2027, 12, 21), release=date(2028, 1, 5))]
    write_reviewed(p, "macro-mon", changes, "abc1234", date(2027, 10, 6))
    text = p.read_text(encoding="utf-8")
    assert "course: macro-mon\nreviewed: 2027-10-06\ncourse_commit: abc1234\n" in text
    assert "  - {n: 4, mode: zoom, reason: 出張}\n" in text
    assert read_reviewed(p) == changes
