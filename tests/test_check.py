from datetime import date

import pytest

from conftest import write
from aidec import check
from aidec.data import load_year
from aidec.requests import Request, write_request
from aidec.schedule import build_part, write_part

TODAY = date(2027, 9, 1)


@pytest.fixture
def setup(year_dir, ghq):
    """両方の授業に、今の学事暦・予定どおりの schedule.yaml を置く（git は使わない）。"""
    yd = load_year(year_dir)
    for c in yd.courses:
        write_part(ghq / c.repo / "2027" / "schedule.yaml",
                   build_part(c, yd.calendar_for(c), yd.events, "2027-09-01 (workdesk abc1234)"))
    return year_dir.parent, ghq


def set_changes(ghq, name, changes_text):
    """changes の段をまるごと差し替える。"""
    p = ghq / "github.com" / "example" / name / "2027" / "schedule.yaml"
    text = p.read_text(encoding="utf-8")
    write(p, text[:text.index("\nchanges:") + 1] + changes_text)


def run(root, ghq, today=TODAY):
    """報告の無い変更（unreported）を除いて見る。changes を直に書くテスト用。"""
    return [p for p in check.run_check(root, 2027, ghq, today) if p.kind != "unreported"]


def kinds(problems):
    return sorted((p.course, p.kind, p.date) for p in problems)


def test_undecided_facts(setup):
    root, ghq = setup
    assert kinds(run(root, ghq)) == [
        ("macro-mon", "undecided", date(2027, 10, 18)),
        ("macro-mon", "undecided", date(2027, 11, 8)),
        ("seminar-wed", "undecided", date(2027, 10, 20)),
    ]


def test_decided_facts_are_quiet(setup):
    root, ghq = setup
    set_changes(ghq, "macro-mon", "changes:\n  - {n: 4, mode: zoom}\n"
                                  "  - {n: 7, cancel: true, makeup: 2027-11-20}\n")
    set_changes(ghq, "seminar-wed", "changes:\n  - {n: 4, note: そのまま行う}\n")
    assert run(root, ghq) == []


@pytest.mark.parametrize("makeup, kind", [
    ("2027-11-03", "closed_day"),      # 休講日
    ("2027-11-08", "closed_day"),      # 年度途中の休講
    ("2028-01-27", "closed_day"),      # 試験期間
    ("2027-10-24", "not_class_day"),   # 日曜
    ("2027-10-30", "not_class_day"),   # 補講日でない土曜
    ("2028-02-10", "not_class_day"),   # 学期の外
    ("2027-10-23", None),              # 補講日
    ("2027-10-12", None),              # 学期中の平日（別の時限での補講）
])
def test_makeup_day(setup, makeup, kind):
    root, ghq = setup
    set_changes(ghq, "macro-mon", f"changes:\n  - {{n: 4, mode: zoom}}\n"
                                  f"  - {{n: 7, cancel: true, makeup: {makeup}}}\n")
    set_changes(ghq, "seminar-wed", "changes:\n  - {n: 4, note: そのまま行う}\n")
    got = [p.kind for p in run(root, ghq)]
    assert got == ([kind] if kind else [])


def test_overdue_request(setup):
    root, ghq = setup
    set_changes(ghq, "macro-mon", "changes:\n  - {n: 4, mode: zoom}\n  - {n: 7, note: x}\n")
    set_changes(ghq, "seminar-wed", "changes:\n  - {n: 4, note: x}\n")
    for rid, status in (("2027-08-20-macro-mon", "open"), ("2027-08-21-macro-mon", "reported")):
        write_request(root / "requests", Request(rid, "macro-mon", date(2027, 8, 20), date(2027, 8, 31),
                                                 status, [date(2027, 10, 18)], "x\n"))
    (p,) = run(root, ghq)
    assert (p.kind, p.course) == ("overdue", "macro-mon")
    assert "2027-08-20-macro-mon" in p.message


def test_not_issued_and_stale_and_bad(setup, year_dir):
    root, ghq = setup
    (ghq / "github.com" / "example" / "seminar-wed" / "2027" / "schedule.yaml").unlink()
    with open(year_dir / "events.yaml", "a", encoding="utf-8", newline="\n") as f:
        f.write("- {date: 2027-12-06, kind: side_job, title: 集中講義}\n")
    got = kinds(run(root, ghq))
    assert ("seminar-wed", "not_issued", None) in got
    assert ("macro-mon", "stale", None) in got
    assert ("macro-mon", "undecided", date(2027, 12, 6)) in got        # 配る前でも今の事実で見る
    set_changes(ghq, "macro-mon", "changes:\n  - {n: 4, makup: 2027-11-20}\n")
    got = kinds(run(root, ghq))
    assert ("macro-mon", "bad_schedule", None) in got


def test_main_exit_codes(setup, capsys):
    root, ghq = setup
    assert check.main(["2027", "--root", str(root), "--today", "2027-09-01"]) == 1
    out = capsys.readouterr().out
    assert "macro-mon" in out and "10/18" in out
    set_changes(ghq, "macro-mon", "changes:\n  - {n: 4, mode: zoom}\n  - {n: 7, note: x}\n")
    set_changes(ghq, "seminar-wed", "changes:\n  - {n: 4, note: x}\n")
    _review_all(root, ghq)
    assert check.main(["2027", "--root", str(root), "--today", "2027-09-01"]) == 0
    assert "ぶつかりは無い" in capsys.readouterr().out


@pytest.mark.parametrize("change, message", [
    ("{n: 15, mode: ondemand, release: 2028-01-11}", "公開日 1/11 が授業日 1/10 より後"),
    ("{n: 15, mode: ondemand, prep_from: 2028-01-10}", "準備を始める日 1/10 が授業日 1/10 より前でない"),
])
def test_prep_timing(setup, change, message):
    root, ghq = setup
    set_changes(ghq, "macro-mon", f"changes:\n  - {{n: 4, mode: zoom}}\n  - {{n: 7, note: x}}\n  - {change}\n")
    set_changes(ghq, "seminar-wed", "changes:\n  - {n: 4, note: x}\n")
    (p,) = run(root, ghq)
    assert p.kind == "prep_timing" and message in p.message and not p.soft


def test_research_day_is_a_soft_notice(setup, year_dir, capsys):
    root, ghq = setup
    write(year_dir / "settings.yaml", "research_days: [fri]\n")
    courses = (year_dir / "courses.yaml").read_text(encoding="utf-8")
    write(year_dir / "courses.yaml", courses.replace("  sessions: 16\n", "  sessions: 16\n  prep_on: [tue, fri]\n"))
    set_changes(ghq, "macro-mon", "changes:\n  - {n: 4, mode: zoom}\n"
                                  "  - {n: 7, cancel: true, makeup: 2027-11-12}\n")   # 金曜
    set_changes(ghq, "seminar-wed", "changes:\n  - {n: 4, note: x}\n")
    got = run(root, ghq)
    assert sorted((p.kind, p.soft) for p in got) == [("research_day", True), ("research_day", True)]
    _review_all(root, ghq)
    assert check.main(["2027", "--root", str(root), "--today", "2027-09-01"]) == 0
    assert "（注意）" in capsys.readouterr().out


def test_makeup_day_on_the_wrong_weekday(setup, year_dir):
    root, ghq = setup
    set_changes(ghq, "macro-mon", "changes:\n  - {n: 4, mode: zoom}\n  - {n: 7, note: x}\n")
    set_changes(ghq, "seminar-wed", "changes:\n  - {n: 4, note: x}\n")
    p = year_dir / "calendar-univa.yaml"
    text = p.read_text(encoding="utf-8")
    write(p, text.replace("makeup_days: [2027-10-23, 2027-11-20]\n",
                          "makeup_days: [2027-10-23, 2027-11-18]\nmakeup_weekday: sat\n"))   # 11/18 は木曜
    (prob,) = [p for p in run(root, ghq) if p.course is None]   # 各授業は stale になる
    assert (prob.course, prob.kind, prob.date, prob.soft) == (None, "makeup_weekday", date(2027, 11, 18), False)
    assert "calendar-univa.yaml" in prob.message and "11/18（thu）" in prob.message
    write(p, text.replace("makeup_days: [2027-10-23, 2027-11-20]\n",
                          "makeup_days: [2027-10-23, 2027-11-20]\nmakeup_weekday: sat\n"))
    assert run(root, ghq) == []


def test_impossible_makeup_date_is_bad_schedule_and_others_continue(setup):
    root, ghq = setup
    set_changes(ghq, "macro-mon", "changes:\n  - {n: 7, cancel: true, makeup: 2027-11-31}\n")
    got = kinds(run(root, ghq))
    assert ("macro-mon", "bad_schedule", None) in got
    assert ("seminar-wed", "undecided", date(2027, 10, 20)) in got


def _decide_all(ghq, extra=""):
    set_changes(ghq, "macro-mon", "changes:\n  - {n: 4, mode: zoom}\n  - {n: 7, note: x}\n" + extra)
    set_changes(ghq, "seminar-wed", "changes:\n  - {n: 4, note: x}\n")


def _review_all(root, ghq):
    from aidec.schedule import load_schedule, write_reviewed
    for name in ("macro-mon", "seminar-wed"):
        _, changes = load_schedule(ghq / "github.com" / "example" / name / "2027" / "schedule.yaml")
        write_reviewed(root / "2027" / "reviewed" / f"{name}.yaml", name, changes, "abc1234", TODAY)


def test_changes_without_report_are_unreported(setup):
    root, ghq = setup
    _decide_all(ghq)
    got = kinds(check.run_check(root, 2027, ghq, TODAY))
    assert got == [("macro-mon", "unreported", None), ("seminar-wed", "unreported", None)]   # 控えが無ければ [] と比べる


def test_reviewed_changes_are_quiet(setup):
    root, ghq = setup
    _decide_all(ghq)
    _review_all(root, ghq)
    assert check.run_check(root, 2027, ghq, TODAY) == []
    # コメントと並びだけを変えても同じ
    set_changes(ghq, "macro-mon", "changes:\n  - {n: 7, note: x}   # 全学休講\n  - {mode: zoom, n: 4}\n")
    assert check.run_check(root, 2027, ghq, TODAY) == []


def test_new_change_after_review(setup, capsys):
    root, ghq = setup
    _decide_all(ghq)
    _review_all(root, ghq)
    _decide_all(ghq, "  - {n: 10, mode: zoom}\n")
    (p,) = check.run_check(root, 2027, ghq, TODAY)
    assert (p.course, p.kind, p.soft) == ("macro-mon", "unreported", False)
    assert "第 10 回" in p.message
