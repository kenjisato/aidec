from datetime import date

import pytest

from conftest import run_git, write
from aidec import brief
from aidec.cli import main
from aidec.data import load_year

MON = "github.com/example/macro-mon"
SEM = "github.com/example/seminar-wed"


def _mon(ghq):
    return ghq / MON


@pytest.fixture
def desk(year_dir, ghq):
    """macro-mon: 第 4 回 10/18、第 5 回 10/25。seminar-wed: 第 4 回 10/20。"""
    write(year_dir / "courses.yaml",
          f"- {{id: macro-mon, label: マクロ月, repo: {MON}, calendar: univa, term: fall,"
          " slot: mon-3, sessions: 16}\n"
          f"- {{id: seminar-wed, repo: {SEM}, calendar: univa, term: fall,"
          " slot: wed-2, sessions: 15, prep_on: [tue]}\n")
    write(year_dir / "events.yaml",
          "- {date: 2027-10-18, end: 2027-10-20, kind: trip, title: 学会（○○）}\n"
          "- {date: 2027-10-25, kind: deadline, title: 報告書}\n"
          "- {date: 2027-11-30, kind: deadline, title: 遠い締め切り}\n"
          "- {date: 2027-11-02, kind: meeting, title: 教授会}\n")
    write(_mon(ghq) / "2027" / "04" / "session.yaml", "session:\n  title: 財政政策\n")
    return year_dir.parent


def run(desk, *args):
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert brief.main(["2027", "--root", str(desk), *args]) == 0
    return buf.getvalue()


def section(out, head):
    lines, on = [], False
    for ln in out.splitlines():
        if ln.startswith("## "):
            on = ln.startswith(f"## {head}")
            continue
        if on and ln:
            lines.append(ln)
    return lines


def test_todays_sessions_with_theme_and_without(desk):
    out = run(desk, "--date", "2027-10-18")
    # 第 4 回は session.yaml がありテーマが出る。seminar-wed は 10/18 に授業が無い
    assert section(out, "2027-10-18") == ["- マクロ月・第 4 回・財政政策"]
    out = run(desk, "--date", "2027-10-20")
    assert section(out, "2027-10-20") == ["- seminar-wed・第 4 回"]


def test_evening_shows_tomorrow(desk):
    out = run(desk, "--date", "2027-10-17", "--evening")
    assert "## 2027-10-18" in out
    assert section(out, "2027-10-18") == ["- マクロ月・第 4 回・財政政策"]


def test_team_yaml_dir_pattern_is_used_for_the_theme(desk, ghq):
    write(_mon(ghq) / "2027" / "team.yaml", "sessions: {dir: 's{nn}'}\n")
    write(_mon(ghq) / "2027" / "s04" / "session.yaml", "session:\n  title: 別の形\n")
    assert section(run(desk, "--date", "2027-10-18"), "2027-10-18") == ["- マクロ月・第 4 回・別の形"]


def test_deadlines_within_14_days_and_trips(desk):
    items = section(run(desk, "--date", "2027-10-18"), "14 日")
    assert "- 10/18〜10/20 学会（○○）" in items
    assert "- 10/25 締め切り: 報告書" in items
    assert "- 11/2 教授会" not in items           # 15 日後
    assert not any("遠い" in i for i in items)


def test_deadline_window_is_14_days(desk):
    items = section(run(desk, "--date", "2027-10-22"), "14 日")
    assert "- 11/2 教授会" in items                # 11 日後
    assert not any("学会" in i for i in items)     # 終わっている


def _accept(repo, branch, dirname, text="Accepted: 2027-10-10 佐藤\n", on_branch=True):
    run_git(repo, "checkout", "-q", "-b", branch)
    write(repo / "2027" / dirname / "review.md", text)
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "review")
    run_git(repo, "checkout", "-q", "main")


def test_accepted_sessions_are_not_candidates_even_only_on_base(desk, ghq):
    repo = _mon(ghq)
    write(repo / "2027" / "team.yaml", "sessions: {base: develop}\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "team")
    _accept(repo, "develop", "05")         # 第 5 回は develop にだけ Accepted がある
    out = run(desk, "--date", "2027-10-18")
    cands = section(out, "準備の候補")
    assert not any("マクロ月 第 5 回" in c for c in cands)
    assert any("マクロ月 第 6 回" in c for c in cands)     # 11/1。review.md が無い
    assert any("マクロ月 第 4 回" in c for c in cands)     # 今日の授業も未受け入れなら出る
    # 近い順
    days = [c for c in cands if "マクロ月" in c]
    assert days == sorted(days, key=lambda c: int(c.split("第 ")[1].split(" ")[0]))


def test_review_without_accepted_line_is_not_accepted(desk, ghq):
    repo = _mon(ghq)
    write(repo / "2027" / "team.yaml", "sessions: {base: develop}\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "team")
    _accept(repo, "develop", "05", text="Requested changes\nnot Accepted: yet\n")
    cands = section(run(desk, "--date", "2027-10-18"), "準備の候補")
    assert any("マクロ月 第 5 回" in c for c in cands)


def test_candidates_stop_at_21_days(desk, ghq):
    repo = _mon(ghq)
    write(repo / "2027" / "team.yaml", "sessions: {base: main}\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "team")
    cands = section(run(desk, "--date", "2027-10-18"), "準備の候補")
    assert any("第 7 回" in c or "第 6 回" in c for c in cands)
    assert not any("マクロ月 第 8 回" in c for c in cands)   # 11/15 は 28 日後


def test_without_team_yaml_prep_on_decides(desk):
    # seminar-wed は prep_on: [tue]。10/19（火）に第 4 回（10/20）の準備
    out = run(desk, "--date", "2027-10-19")
    cands = section(out, "準備の候補")
    assert [c for c in cands if "seminar-wed" in c] and "seminar-wed 第 4 回" in " ".join(cands)
    # 準備日でない日は出ない。macro-mon は prep_on が無いので出ない
    out = run(desk, "--date", "2027-10-21")
    assert not any("seminar-wed" in c for c in section(out, "準備の候補"))
    assert not any("マクロ月" in c for c in section(run(desk, "--date", "2027-10-19"), "準備の候補"))


def test_busy_day_note(desk):
    cands = section(run(desk, "--date", "2027-10-19"), "準備の候補")
    assert any("使える時間が少ない" in c for c in cands)          # 10/19 は学会の最中
    cands = section(run(desk, "--date", "2027-10-26"), "準備の候補")
    assert not any("使える時間が少ない" in c for c in cands)


def test_inbox_and_footer(desk):
    from aidec import inbox
    from datetime import datetime
    inbox.write(desk, inbox.Item("r1", "raise", "macro-mon", None, 5, datetime(2027, 10, 1), False, "補講日がほしい"))
    out = run(desk, "--date", "2027-10-18")
    assert "r1 macro-mon 第 5 回: 補講日がほしい" in out
    assert out.rstrip().splitlines()[-1] == "手元の授業レポは fetch していない"


def test_cli_dispatch_and_config_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AIDEC_CONFIG", str(tmp_path / "none.yaml"))
    assert main(["brief", "2027"]) == 1
    assert "none.yaml" in capsys.readouterr().err
