import os
import subprocess
from datetime import date

from conftest import add_class, issue_schedule, write
from aidec.data import load_year
from aidec.week import day_table, prep_days, week_report

MON_SCHED = ("github.com", "example", "macro-mon")


def changes(croot, *lines):
    write(croot / "schedule-changes.yaml",
          "course: macro-2027\nclass: 2027-mon3\nchanges:\n" + "".join(f"  - {x}\n" for x in lines))


def test_week_report(year_dir, ghq):
    # macro-mon は新しい置き方で配ってある（第 5 回を 10/23 の補講日に移した）。seminar-wed は classes/ が無い
    croot = issue_schedule(year_dir, ghq, "macro-mon",
                           lambda t: t.replace("{n: 5, date: 2027-10-25}", "{n: 5, date: 2027-10-23}"))
    changes(croot, "{n: 4, reason: 出張, mode: online}")
    out = week_report(load_year(year_dir), ghq, date(2027, 10, 20), 2)
    assert out.splitlines() == [
        "## 2027-10-18 の週（10/18〜10/24）",
        "- 10/18（月） macro-mon 第 4 回 online ／ 学会（○○）（10/18〜10/20）",
        "- 10/18〜10/20 学会（○○）",
        "- 10/20（水） seminar-wed 第 4 回 ／ 学会（○○）（10/18〜10/20）（未配布）",
        "- 10/23（土） macro-mon 第 5 回",
        "",
        "## 2027-10-25 の週（10/25〜10/31）",
        "- 10/27（水） seminar-wed 第 5 回（未配布）",
    ]


def _mon_week(year_dir, ghq, start=date(2027, 10, 25)):
    return [ln for ln in week_report(load_year(year_dir), ghq, start, 1).splitlines() if "macro-mon" in ln]


def test_cancelled_session_is_shown_as_cancelled(year_dir, ghq):
    issue_schedule(year_dir, ghq, "macro-mon",
                   lambda t: t.replace("{n: 5, date: 2027-10-25}", "{n: 5, cancelled: true}"))
    assert _mon_week(year_dir, ghq) == ["- 10/25（月） macro-mon 第 5 回 休講"]


def test_pending_cancel_is_marked_on_its_date(year_dir, ghq):
    croot = issue_schedule(year_dir, ghq, "macro-mon")
    changes(croot, "{n: 5, reason: 病気, cancel: true, date: 2027-10-25, ref: r1}")
    assert _mon_week(year_dir, ghq) == ["- 10/25（月） macro-mon 第 5 回 休講（未決）"]


def test_ondemand_is_on_release_and_prep_from_is_only_shown(year_dir, ghq):
    croot = issue_schedule(year_dir, ghq, "macro-mon")
    changes(croot, "{n: 15, reason: 出張, mode: ondemand, release: 2028-01-05, prep_from: 2027-12-21}")
    out = week_report(load_year(year_dir), ghq, date(2028, 1, 3), 2)
    assert "- 1/5（水） macro-mon 第 15 回 ondemand（prep_from 12/21）" in out
    assert "1/10（月） macro-mon" not in out


def test_broken_changes_file_is_marked(year_dir, ghq):
    croot = issue_schedule(year_dir, ghq, "macro-mon")
    write(croot / "schedule-changes.yaml", "changes: [\n")
    assert _mon_week(year_dir, ghq) == ["- 10/25（月） macro-mon 第 5 回（schedule-changes.yaml を読めない）"]
    changes(croot, "{n: 99, reason: x, mode: online}")          # dates に無い回
    assert _mon_week(year_dir, ghq) == ["- 10/25（月） macro-mon 第 5 回（schedule-changes.yaml を読めない）"]


def test_broken_schedule_is_marked(year_dir, ghq):
    croot = issue_schedule(year_dir, ghq, "macro-mon")
    write(croot / "schedule.yaml", "dates: [\n")
    assert _mon_week(year_dir, ghq) == ["- 10/25（月） macro-mon 第 5 回（schedule.yaml を読めない）"]


def test_not_issued_uses_moves(year_dir, ghq):
    write(year_dir / "moves.yaml", "- {course: macro-mon, n: 5, cancelled: true}\n")
    add_class(year_dir, ghq, "macro-mon")                         # class root はあるが schedule.yaml が無い
    assert _mon_week(year_dir, ghq) == ["- 10/25（月） macro-mon 第 5 回 休講（未配布）"]


def test_old_layout_schedule_is_not_read(year_dir, ghq):
    # classes/ に移っていないレポの <年度>/schedule.yaml は見ない
    old = write(ghq.joinpath(*MON_SCHED) / "2027" / "schedule.yaml",
                "course: macro-mon\nissued: x\nplan:\n  - {n: 5, date: 2027-10-26}\nchanges: []\n")
    before = old.read_text(encoding="utf-8")
    assert _mon_week(year_dir, ghq) == ["- 10/25（月） macro-mon 第 5 回（未配布）"]
    assert old.read_text(encoding="utf-8") == before


def _session(n, d, cancelled=False):
    from aidec.schedule import Session
    return Session(n, d, None if cancelled else d, None, cancelled, (), None)


def test_prep_days_are_in_the_week_before():
    ss = [_session(13, date(2027, 12, 20)), _session(14, date(2027, 12, 22)), _session(15, date(2028, 1, 10))]
    got = prep_days(ss, ("tue", "wed"))
    # 12/22（水）は授業の日なので入れない。冬休みの間は出さず、1/10 の前の週だけ
    assert got == [(date(2027, 12, 21), 14), (date(2028, 1, 4), 15), (date(2028, 1, 5), 15)]


def test_prep_days_follow_class_dates():
    # 第 2 回は 10/23（土）に移した。第 4 回は休講
    ss = [_session(1, date(2027, 9, 27)), _session(2, date(2027, 10, 23)),
          _session(3, date(2027, 10, 11)), _session(4, date(2027, 10, 18), cancelled=True)]
    # 9/27 の次は 10/11 の第 3 回、その次は 10/23 の第 2 回。休講の第 4 回は数えない
    assert prep_days(ss, ("tue",)) == [(date(2027, 10, 5), 3), (date(2027, 10, 19), 2)]
    assert prep_days(ss, ("sat",)) == [(date(2027, 10, 9), 3)]          # 10/17〜10/22 に土曜は無い


def test_week_report_shows_prep_days(year_dir, ghq):
    write(year_dir / "courses.yaml",
          "- {id: macro-mon, repo: github.com/example/macro-mon, calendar: univa, term: fall,"
          " slot: mon-3, sessions: 16, prep_on: [tue, wed]}\n")
    out = week_report(load_year(year_dir), ghq, date(2027, 10, 4), 1)
    assert "- 10/5（火） macro-mon 第 3 回の準備" in out
    assert "- 10/6（水） macro-mon 第 3 回の準備" in out


def test_prep_and_deadline(year_dir, ghq):
    out = week_report(load_year(year_dir), ghq, date(2028, 1, 3), 2)
    assert "- 1/3 準備を軽くしたい期間（1/10 卒論提出の前 2 週）" in out
    assert "- 1/10 締め切り: 卒論提出" in out
    assert "- 1/10 準備を軽くしたい期間（1/10 卒論提出の前 2 週）" not in out   # 締め切りの週には出さない


def test_empty_week(year_dir, ghq):
    out = week_report(load_year(year_dir), ghq, date(2027, 8, 2), 1)
    assert out.splitlines() == ["## 2027-08-02 の週（8/2〜8/8）", "- 予定なし"]


def test_script_prints_utf8_through_a_pipe(year_dir, ghq):
    # UTF-8 モードを切り、Windows の既定（cp932）でパイプに書く状態にする
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    env["PYTHONUTF8"] = "0"
    p = subprocess.run(["uv", "run", "aidec", "week", "2027",
                        "--root", str(year_dir.parent), "--from", "2027-10-18", "--weeks", "1"],
                       capture_output=True, env=env)
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")
    assert "第 4 回" in p.stdout.decode("utf-8")


def _table_year(year_dir):
    write(year_dir / "courses.yaml",
          "- {id: macro-mon, repo: github.com/example/macro-mon, calendar: univa, term: fall,"
          " slot: mon-3, sessions: 16, prep_on: [tue, wed]}\n"
          "- {id: seminar-wed, label: seminar, repo: github.com/example/seminar-wed, calendar: univa,"
          " term: fall, slot: wed-2, sessions: 15}\n")
    write(year_dir / "events.yaml",
          "- {date: 2027-10-18, end: 2027-10-19, kind: trip, title: 学会（○○）}\n"
          "- {date: 2027-10-20, kind: meeting, title: faculty mtg, note: 13:30 on Zoom}\n")
    return load_year(year_dir)


def test_day_table_lists_every_day_with_aligned_columns(year_dir, ghq):
    out = day_table(_table_year(year_dir), ghq, date(2027, 10, 16), 5)
    assert out.splitlines() == [
        "10-16 Sat |",
        "10-17 Sun |",
        "10-18 Mon | macro-mon   | Day 4 (not issued) · 学会（○○）（10/18〜10/19）",
        "          | 学会（○○）  | trip 10/18–10/19",
        "10-19 Tue | macro-mon   | Prep for Day 5",
        "          | 学会（○○）  | trip 10/18–10/19",
        "10-20 Wed | seminar     | Day 4 (not issued)",
        "          | macro-mon   | Prep for Day 5",
        "          | faculty mtg | 13:30 on Zoom",
    ]                                                                  # 全角は 2 桁、○ などの曖昧な幅は 1 桁と数える


def test_day_table_shows_changes_and_busy(year_dir, ghq):
    croot = issue_schedule(year_dir, ghq, "macro-mon",
                           lambda t: t.replace("{n: 15, date: 2028-01-10}", "{n: 15, date: 2028-01-08}"))
    changes(croot, "{n: 16, reason: x, mode: ondemand, release: 2028-01-14, prep_from: 2028-01-09}",
            "{n: 13, reason: x, cancel: true, date: 2027-12-20}")
    yd = load_year(year_dir)
    out = [" ".join(ln.split()) for ln in day_table(yd, ghq, date(2028, 1, 7), 8).splitlines()]
    assert "01-07 Fri | busy | before 卒論提出 (1/10)" in out           # 卒論提出の前 2 週
    assert "01-08 Sat | macro-mon | Day 15" in out
    assert not any(ln.startswith("01-10 Mon | macro-mon") for ln in out)
    assert "01-14 Fri | macro-mon | Day 16 (ondemand) · prep_from 1/9" in out
    assert "12-20 Mon | macro-mon | Day 13 cancel pending" in day_table(yd, ghq, date(2027, 12, 20), 1)
    issue_schedule(year_dir, ghq, "macro-mon",
                   lambda t: t.replace("{n: 13, date: 2027-12-20}", "{n: 13, cancelled: true}"))
    write(croot / "schedule-changes.yaml", "changes: [\n")
    assert day_table(load_year(year_dir), ghq, date(2027, 12, 20), 1).splitlines() == [
        "12-20 Mon | macro-mon | Day 13 cancelled (unreadable schedule-changes.yaml)"]


def test_table_from_the_command_line(year_dir, ghq, capsys):
    from aidec.week import main
    assert main(["2027", "--root", str(year_dir.parent), "--table", "--from", "2027-10-16", "--days", "2"]) == 0
    assert capsys.readouterr().out.splitlines() == ["10-16 Sat |", "10-17 Sun |"]


def test_week_lists_raised_matters(tmp_path):
    from datetime import datetime, timezone
    from aidec import inbox
    from aidec.week import inbox_section
    assert inbox_section(tmp_path) == ""
    inbox.write(tmp_path, inbox.Item("20271105-macro-mon-a1b2c3", "raise", "macro-mon", None, 5,
                                     datetime(2027, 11, 5, tzinfo=timezone.utc), False, "補講日がほしい\n詳細"))
    assert inbox_section(tmp_path).splitlines() == [
        "", "## 上がってきた相談", "- 20271105-macro-mon-a1b2c3 macro-mon 第 5 回: 補講日がほしい"]


def test_inbox_section_survives_empty_body_and_shows_in_table(tmp_path, capsys, monkeypatch):
    from datetime import datetime, timezone
    from aidec import inbox
    from aidec.week import inbox_section, main
    inbox.write(tmp_path, inbox.Item("20271105-macro-mon-a1b2c3", "raise", "macro-mon", None, None,
                                     datetime(2027, 11, 5, tzinfo=timezone.utc), True, ""))
    assert "macro-mon（返事不要）" in inbox_section(tmp_path)
    write(tmp_path / "2027" / "calendar-univa.yaml", "university: univa\nyear: 2027\nsource: x\nterms: {fall: {start: 2027-09-27, end: 2028-01-25}}\n")
    write(tmp_path / "2027" / "courses.yaml", "[]\n")
    monkeypatch.setenv("AIDEC_GHQ_ROOT", str(tmp_path))
    assert main(["2027", "--table", "--from", "2027-10-18", "--days", "1", "--root", str(tmp_path)]) == 0
    assert "## 上がってきた相談" in capsys.readouterr().out
