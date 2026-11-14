from datetime import date

import pytest

from conftest import CLASSES, add_class, issue_schedule, write
from aidec import check


@pytest.fixture
def setup(year_dir, ghq):
    """両方の授業に、今の学事暦・moves どおりの schedule.yaml を class root に置く。

    macro-mon の第 7 回（11/8）は年度途中の休講に当たるので、moves で補講日 11/20 に移しておく。
    """
    write(year_dir / "moves.yaml", "- {course: macro-mon, n: 7, date: 2027-11-20}\n")
    for name in CLASSES:
        issue_schedule(year_dir, ghq, name)
    return year_dir.parent, ghq


def croot(ghq, name):
    return ghq / "github.com" / "example" / name / "classes" / CLASSES[name][1]


def set_changes(ghq, name, *lines):
    write(croot(ghq, name) / "schedule-changes.yaml",
          "changes:\n" + "".join(f"  - {x}\n" for x in lines))


def run(root, ghq):
    return check.run_check(root, 2027, ghq)


def kinds(problems):
    return sorted((p.course, p.kind, p.date) for p in problems)


def test_issued_as_computed_is_quiet(setup):
    root, ghq = setup
    assert run(root, ghq) == []


def test_session_on_a_closed_day_is_reported(year_dir, ghq):
    for name in CLASSES:
        issue_schedule(year_dir, ghq, name)                      # 第 7 回 11/8 を動かしていない
    assert kinds(run(year_dir.parent, ghq)) == [("macro-mon", "closed_day", date(2027, 11, 8))]


def test_stale_when_moves_or_events_change(setup, year_dir):
    root, ghq = setup
    write(year_dir / "moves.yaml", "- {course: macro-mon, n: 7, date: 2027-11-20}\n"
                                   "- {course: seminar-wed, n: 5, cancelled: true}\n")
    assert kinds(run(root, ghq)) == [("seminar-wed", "stale", None)]
    write(year_dir / "moves.yaml", "- {course: macro-mon, n: 7, date: 2027-11-20}\n")
    with open(year_dir / "events.yaml", "a", encoding="utf-8", newline="\n") as f:
        f.write("- {date: 2027-12-06, kind: side_job, title: 集中講義}\n")
    assert kinds(run(root, ghq)) == [("macro-mon", "stale", None)]


@pytest.mark.parametrize("moved, kind", [
    ("2027-11-03", "closed_day"),      # 休講日
    ("2028-01-27", "closed_day"),      # 試験期間
    ("2027-10-24", "not_class_day"),   # 日曜
    ("2027-10-30", "not_class_day"),   # 補講日でない土曜
    ("2028-02-10", "not_class_day"),   # 学期の外
    ("2027-10-23", None),              # 補講日
    ("2027-10-12", None),              # 学期中の平日（別の時限での補講）
])
def test_listed_date_must_be_a_class_or_makeup_day(setup, year_dir, moved, kind):
    root, ghq = setup
    write(year_dir / "moves.yaml", f"- {{course: macro-mon, n: 7, date: {moved}}}\n")
    issue_schedule(year_dir, ghq, "macro-mon")
    assert kinds(run(root, ghq)) == ([("macro-mon", kind, date.fromisoformat(moved))] if kind else [])


def test_pending_cancel(setup, year_dir):
    root, ghq = setup
    set_changes(ghq, "macro-mon", "{n: 5, reason: 病気, cancel: true, date: 2027-10-25, ref: r1}")
    (p,) = run(root, ghq)
    assert (p.course, p.kind, p.date, p.soft) == ("macro-mon", "pending_cancel", date(2027, 10, 25), False)
    assert "第 5 回" in p.message
    # 上で決まって schedule.yaml の日付が変われば、もう出ない
    write(year_dir / "moves.yaml", "- {course: macro-mon, n: 7, date: 2027-11-20}\n"
                                   "- {course: macro-mon, n: 5, cancelled: true}\n")
    issue_schedule(year_dir, ghq, "macro-mon")
    assert run(root, ghq) == []


def test_other_changes_are_quiet(setup):
    root, ghq = setup
    set_changes(ghq, "macro-mon", "{n: 4, reason: 出張, mode: online}",
                "{n: 15, reason: 出張, mode: ondemand, release: 2028-01-11, prep_from: 2028-01-10}")
    assert run(root, ghq) == []


def test_broken_changes_file_is_one_line(setup):
    root, ghq = setup
    write(croot(ghq, "macro-mon") / "schedule-changes.yaml", "changes: [\n")
    set_changes(ghq, "seminar-wed", "{n: 99, reason: x, mode: online}")      # dates に無い回
    got = run(root, ghq)
    assert kinds(got) == [("macro-mon", "bad_changes", None), ("seminar-wed", "bad_changes", None)]
    assert all(len(p.line().splitlines()) == 1 for p in got)


def test_not_issued_and_bad_schedule(setup, ghq):
    root, _ = setup
    (croot(ghq, "seminar-wed") / "schedule.yaml").unlink()
    write(croot(ghq, "macro-mon") / "schedule.yaml", "dates: [\n")
    assert kinds(run(root, ghq)) == [("macro-mon", "bad_schedule", None), ("seminar-wed", "not_issued", None)]


def test_repo_not_moved_to_classes_is_not_issued(year_dir, ghq):
    # classes/ が無いレポ。旧い <年度>/schedule.yaml があっても読まない
    write(ghq / "github.com/example/seminar-wed/2027/schedule.yaml", "course: seminar-wed\nplan: []\n")
    add_class(year_dir, ghq, "macro-mon")
    got = run(year_dir.parent, ghq)
    assert kinds(got) == [("macro-mon", "not_issued", None), ("seminar-wed", "not_issued", None)]


def test_bad_moves_stop_check(setup, year_dir, capsys):
    root, _ = setup
    write(year_dir / "moves.yaml", "- {course: macro-mon, n: 17, cancelled: true}\n")
    assert check.main(["2027", "--root", str(root)]) == 1
    captured = capsys.readouterr()
    assert "moves.yaml" in captured.err and captured.out == ""


def test_main_exit_codes(setup, capsys):
    root, ghq = setup
    assert check.main(["2027", "--root", str(root)]) == 0
    assert "ぶつかりは無い" in capsys.readouterr().out
    set_changes(ghq, "macro-mon", "{n: 5, reason: x, cancel: true, date: 2027-10-25}")
    assert check.main(["2027", "--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "[pending_cancel] macro-mon:" in out and "10/25" in out


def test_research_day_is_a_soft_notice(setup, year_dir, capsys):
    root, ghq = setup
    write(year_dir / "settings.yaml", "research_days: [fri]\n")
    courses = (year_dir / "courses.yaml").read_text(encoding="utf-8")
    write(year_dir / "courses.yaml", courses.replace("  sessions: 16\n", "  sessions: 16\n  prep_on: [tue, fri]\n"))
    write(year_dir / "moves.yaml", "- {course: macro-mon, n: 7, date: 2027-11-12}\n")          # 金曜
    issue_schedule(year_dir, ghq, "macro-mon")
    got = run(root, ghq)
    assert [(p.kind, p.date, p.soft) for p in got] == [
        ("research_day", None, True), ("research_day", date(2027, 11, 12), True)]
    assert check.main(["2027", "--root", str(root)]) == 0
    assert "（注意）" in capsys.readouterr().out


def test_makeup_day_on_the_wrong_weekday(setup, year_dir):
    root, ghq = setup
    p = year_dir / "calendar-univa.yaml"
    text = p.read_text(encoding="utf-8")
    write(p, text.replace("makeup_days: [2027-10-23, 2027-11-20]\n",
                          "makeup_days: [2027-10-23, 2027-11-18]\nmakeup_weekday: sat\n"))   # 11/18 は木曜
    (prob,) = [p for p in run(root, ghq) if p.course is None]   # 各授業は stale などになる
    assert (prob.course, prob.kind, prob.date, prob.soft) == (None, "makeup_weekday", date(2027, 11, 18), False)
    assert "calendar-univa.yaml" in prob.message and "11/18（thu）" in prob.message
    write(p, text.replace("makeup_days: [2027-10-23, 2027-11-20]\n",
                          "makeup_days: [2027-10-23, 2027-11-20]\nmakeup_weekday: sat\n"))
    assert run(root, ghq) == []
