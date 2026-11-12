import os
import subprocess
from datetime import date

from conftest import write
from aidec.data import load_year
from aidec.schedule import build_part, write_part
from aidec.week import day_table, prep_days, week_report


def test_week_report(year_dir, ghq):
    yd = load_year(year_dir)
    mon = yd.courses[0]
    p = ghq / mon.repo / "2027" / "schedule.yaml"
    write_part(p, build_part(mon, yd.calendar_for(mon), yd.events, "x"))
    write(p, p.read_text(encoding="utf-8").replace(
        "changes: []\n", "changes:\n  - {n: 4, mode: zoom}\n  - {n: 5, cancel: true, makeup: 2027-10-23}\n"))
    out = week_report(yd, ghq, date(2027, 10, 20), 2)
    assert out.splitlines() == [
        "## 2027-10-18 の週（10/18〜10/24）",
        "- 10/18（月） macro-mon 第 4 回 zoom ／ 学会（○○）（10/18〜10/20）",
        "- 10/18〜10/20 学会（○○）",
        "- 10/20（水） seminar-wed 第 4 回 ／ 学会（○○）（10/18〜10/20）（未配布）",
        "- 10/23（土） macro-mon 第 5 回 補講",
        "",
        "## 2027-10-25 の週（10/25〜10/31）",
        "- 10/25（月） macro-mon 第 5 回 休講（補講 10/23）",
        "- 10/27（水） seminar-wed 第 5 回（未配布）",
    ]


def _session(n, planned, actual=None, cancelled=False, prep_from=None, release=None):
    from aidec.schedule import Change, Session
    change = Change(n, prep_from=prep_from, release=release) if prep_from or release else None
    return Session(n, planned, planned if actual is None and not cancelled else actual, None, cancelled, (), change)


def test_prep_days_are_in_the_week_before():
    ss = [_session(13, date(2027, 12, 20)), _session(14, date(2027, 12, 22)), _session(15, date(2028, 1, 10))]
    got = prep_days(ss, ("tue", "wed"))
    # 12/22（水）は授業の日なので入れない。冬休みの間は出さず、1/10 の前の週だけ
    assert got == [(date(2027, 12, 21), 14), (date(2028, 1, 4), 15), (date(2028, 1, 5), 15)]


def test_prep_days_follow_actual_dates():
    # 第 2 回を休講にして 10/23（土）に補講する。第 4 回は休講で補講未定
    ss = [_session(1, date(2027, 9, 27)), _session(2, date(2027, 10, 4), date(2027, 10, 23), True),
          _session(3, date(2027, 10, 11)), _session(4, date(2027, 10, 18), cancelled=True)]
    # 9/27 の次は 10/11 の第 3 回、その次は 10/23 の第 2 回（補講）。補講未定の第 4 回は数えない
    assert prep_days(ss, ("tue",)) == [(date(2027, 10, 5), 3), (date(2027, 10, 19), 2)]
    assert prep_days(ss, ("sat",)) == [(date(2027, 10, 9), 3)]          # 10/17〜10/22 に土曜は無い


def test_prep_from_starts_early_and_release_ends_it():
    ss = [_session(13, date(2027, 12, 20)), _session(14, date(2027, 12, 22)),
          _session(15, date(2028, 1, 10), prep_from=date(2027, 12, 21), release=date(2028, 1, 5))]
    got = prep_days(ss, ("tue", "wed"))
    assert got == [(date(2027, 12, 21), 14), (date(2027, 12, 21), 15), (date(2027, 12, 22), 15),
                   (date(2027, 12, 28), 15), (date(2027, 12, 29), 15), (date(2028, 1, 4), 15)]


def test_week_report_shows_prep_days(year_dir, ghq):
    write(year_dir / "courses.yaml",
          "- {id: macro-mon, repo: github.com/example/macro-mon, calendar: univa, term: fall,"
          " slot: mon-3, sessions: 16, prep_on: [tue, wed]}\n")
    out = week_report(load_year(year_dir), ghq, date(2027, 10, 4), 1)
    assert "- 10/5（火） macro-mon 第 3 回の準備" in out
    assert "- 10/6（水） macro-mon 第 3 回の準備" in out


def test_week_report_shows_release(year_dir, ghq):
    yd = load_year(year_dir)
    mon = yd.courses[0]
    p = ghq / mon.repo / "2027" / "schedule.yaml"
    write_part(p, build_part(mon, yd.calendar_for(mon), yd.events, "x"))
    write(p, p.read_text(encoding="utf-8").replace(
        "changes: []\n", "changes:\n  - {n: 15, mode: ondemand, prep_from: 2027-12-21, release: 2028-01-05}\n"))
    out = week_report(yd, ghq, date(2028, 1, 3), 1)
    assert "- 1/5（水） macro-mon 第 15 回 公開" in out


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
    yd = load_year(year_dir)
    mon = yd.courses[0]
    p = ghq / mon.repo / "2027" / "schedule.yaml"
    write_part(p, build_part(mon, yd.calendar_for(mon), yd.events, "x"))
    write(p, p.read_text(encoding="utf-8").replace(
        "changes: []\n", "changes:\n  - {n: 15, cancel: true, makeup: 2028-01-08}\n"
                         "  - {n: 16, mode: ondemand, release: 2028-01-14}\n"))
    out = day_table(yd, ghq, date(2028, 1, 7), 4)
    assert "01-07 Fri | busy" in out                                   # 卒論提出の前 2 週
    assert "01-08 Sat | macro-mon | Day 15 makeup" in out
    assert "01-10 Mon | macro-mon | Day 15 cancelled → makeup 1/8" in out


def test_table_from_the_command_line(year_dir, ghq, capsys):
    from aidec.week import main
    assert main(["2027", "--root", str(year_dir.parent), "--table", "--from", "2027-10-16", "--days", "2"]) == 0
    assert capsys.readouterr().out.splitlines() == ["10-16 Sat |", "10-17 Sun |"]
