import pytest

from conftest import add_class, issue_schedule, run_git, write
from aidec import brief
from aidec.cli import main

MON = "github.com/example/macro-mon"
SEM = "github.com/example/seminar-wed"
MON_CLASS = "classes/2027-mon3"


def _mon(ghq):
    return ghq / MON


@pytest.fixture
def desk(year_dir, ghq):
    """macro-mon: 第 4 回 10/18、第 5 回 10/25（classes/2027-mon3/）。seminar-wed: 第 4 回 10/20（旧い <年度>/）。"""
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
    croot = add_class(year_dir, ghq, "macro-mon")
    write(croot / "04" / "session.yaml", "session:\n  title: 財政政策\n")
    write(ghq / SEM / "2027" / "04" / "session.yaml", "session:\n  title: 演習\n")
    run_git(_mon(ghq), "add", "-A")
    run_git(_mon(ghq), "commit", "-q", "-m", "classes/")
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
        if on and ln and ln != brief.FOOTER:
            lines.append(ln)
    return lines


def test_todays_sessions_with_theme_and_without(desk):
    out = run(desk, "--date", "2027-10-18")
    # 第 4 回は session.yaml がありテーマが出る。seminar-wed は 10/18 に授業が無い
    assert section(out, "授業 2027-10-18") == ["- マクロ月・第 4 回・財政政策"]
    out = run(desk, "--date", "2027-10-20")
    assert section(out, "授業 2027-10-20") == ["- seminar-wed・第 4 回・演習"]     # classes/ に移っていないレポ


def test_evening_shows_tomorrow(desk):
    out = run(desk, "--date", "2027-10-17", "--evening")
    assert "## 授業 2027-10-18" in out
    assert section(out, "授業 2027-10-18") == ["- マクロ月・第 4 回・財政政策"]


def test_packet_yaml_dir_pattern_is_used_for_the_theme(desk, ghq):
    write(_mon(ghq) / MON_CLASS / "packet.yaml", "sessions: {dir: 's{nn}'}\n")
    write(_mon(ghq) / MON_CLASS / "s04" / "session.yaml", "session:\n  title: 別の形\n")
    assert section(run(desk, "--date", "2027-10-18"), "授業 2027-10-18") == ["- マクロ月・第 4 回・別の形"]


def test_course_root_team_yaml_dir_pattern_is_used_for_the_theme(desk, ghq):
    write(_mon(ghq) / "team.yaml", "sessions: {dir: 's{nn}'}\n")              # packet.yaml が無い
    write(_mon(ghq) / MON_CLASS / "s04" / "session.yaml", "session:\n  title: 別の形\n")
    assert section(run(desk, "--date", "2027-10-18"), "授業 2027-10-18") == ["- マクロ月・第 4 回・別の形"]


def test_old_team_yaml_dir_pattern_is_used_for_the_theme(desk, ghq):
    write(ghq / SEM / "2027" / "team.yaml", "sessions: {dir: 's{nn}'}\n")
    write(ghq / SEM / "2027" / "s04" / "session.yaml", "session:\n  title: 別の形\n")
    assert section(run(desk, "--date", "2027-10-20"), "授業 2027-10-20") == ["- seminar-wed・第 4 回・別の形"]


def test_ondemand_session_is_on_its_release_day(desk, ghq, year_dir):
    croot = issue_schedule(year_dir, ghq, "macro-mon")
    write(croot / "schedule-changes.yaml",
          "changes:\n  - {n: 4, reason: 出張, mode: ondemand, release: 2027-10-16}\n")
    assert section(run(desk, "--date", "2027-10-16"), "授業 2027-10-16") == ["- マクロ月・第 4 回・財政政策"]
    assert section(run(desk, "--date", "2027-10-18"), "授業 2027-10-18") == ["- なし"]


def test_deadlines_within_14_days_and_trips(desk):
    items = section(run(desk, "--date", "2027-10-18"), "締め切り")
    assert "- 10/18〜10/20 学会（○○）" in items
    assert "- 10/25 締め切り: 報告書" in items
    assert "- 11/2 教授会" not in items           # 15 日後
    assert not any("遠い" in i for i in items)


def test_deadline_window_is_14_days(desk):
    items = section(run(desk, "--date", "2027-10-22"), "締め切り")
    assert "- 11/2 教授会" in items                # 11 日後
    assert not any("学会" in i for i in items)     # 終わっている


def _accept(repo, branch, dirname, text="Accepted: 2027-10-10 山田太郎\n", on_branch=True, cdir=MON_CLASS):
    run_git(repo, "checkout", "-q", "-b", branch)
    write(repo / cdir / dirname / "review.md", text)
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "review")
    run_git(repo, "checkout", "-q", "main")


def test_accepted_sessions_are_not_candidates_even_only_on_base(desk, ghq):
    repo = _mon(ghq)
    write(repo / "team.yaml", "sessions: {base: develop}\n")
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


def test_acceptance_in_a_repo_not_moved_to_classes(desk, ghq):
    repo = ghq / SEM
    write(repo / "2027" / "team.yaml", "sessions: {base: develop}\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "team")
    _accept(repo, "develop", "05", cdir="2027")
    cands = section(run(desk, "--date", "2027-10-18"), "準備の候補")
    assert "- seminar-wed 第 4 回（10/20（水））" in cands
    assert not any("seminar-wed 第 5 回" in c for c in cands)


def test_pending_cancel_is_shown_on_its_day(desk, ghq, year_dir):
    croot = issue_schedule(year_dir, ghq, "macro-mon")
    write(croot / "schedule-changes.yaml",
          "changes:\n  - {n: 5, reason: 病気, cancel: true, date: 2027-10-25}\n")
    assert section(run(desk, "--date", "2027-10-25"), "授業 2027-10-25") == ["- マクロ月・第 5 回 休講（未決）"]


def test_review_without_accepted_line_is_not_accepted(desk, ghq):
    repo = _mon(ghq)
    write(repo / "team.yaml", "sessions: {base: develop}\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "team")
    _accept(repo, "develop", "05", text="Requested changes\nnot Accepted: yet\n")
    cands = section(run(desk, "--date", "2027-10-18"), "準備の候補")
    assert any("マクロ月 第 5 回" in c for c in cands)


def test_candidates_stop_at_21_days(desk, ghq):
    repo = _mon(ghq)
    write(repo / "team.yaml", "sessions: {base: main}\n")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "team")
    cands = section(run(desk, "--date", "2027-10-18"), "準備の候補")
    assert any("第 7 回" in c or "第 6 回" in c for c in cands)
    assert not any("マクロ月 第 8 回" in c for c in cands)   # 11/15 は 28 日後


def test_without_team_yaml_prep_on_decides(desk):
    # seminar-wed は prep_on: [tue]。10/19（火）に第 4 回（10/20）の準備
    cands = section(run(desk, "--date", "2027-10-19"), "準備の候補")
    assert cands == ["- 会議・出張あり", "- seminar-wed 第 4 回（10/20（水））"]
    # 準備日でない日は出ない。macro-mon は prep_on が無いので出ない
    assert section(run(desk, "--date", "2027-10-21"), "準備の候補") == ["- なし"]


def test_busy_note_is_said_once(desk):
    cands = section(run(desk, "--date", "2027-10-19"), "準備の候補")
    assert [c for c in cands if "会議・出張あり" in c] == ["- 会議・出張あり"]
    cands = section(run(desk, "--date", "2027-10-26"), "準備の候補")
    assert not any("会議・出張あり" in c for c in cands)


def _team_commit(repo, text):
    write(repo / "team.yaml", text)
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "team")


def test_moved_session_is_a_candidate_with_the_new_date(desk, ghq, year_dir):
    issue_schedule(year_dir, ghq, "macro-mon",
                   lambda t: t.replace("{n: 5, date: 2027-10-25}", "{n: 5, date: 2027-10-23}"))
    _team_commit(_mon(ghq), "sessions: {base: main}\n")
    cands = section(run(desk, "--date", "2027-10-18"), "準備の候補")
    assert "- マクロ月 第 5 回（10/23（土））" in cands
    assert not any("（10/25（月））" in c for c in cands)


def test_unreadable_base_is_reported_not_listed(desk, ghq):
    _team_commit(_mon(ghq), "sessions: {base: nosuch}\n")
    cands = section(run(desk, "--date", "2027-10-18"), "準備の候補")
    assert "- マクロ月: nosuch 読めない" in cands
    assert not any(c.startswith("- マクロ月 第") for c in cands)


def test_acceptance_uses_sessions_dir_pattern(desk, ghq):
    repo = _mon(ghq)
    write(repo / MON_CLASS / "packet.yaml", "sessions: {dir: 's{nn}'}\n")
    _team_commit(repo, "sessions: {base: develop}\n")
    _accept(repo, "develop", "s05")
    cands = section(run(desk, "--date", "2027-10-18"), "準備の候補")
    assert not any("マクロ月 第 5 回" in c for c in cands)
    assert any("マクロ月 第 6 回" in c for c in cands)


def test_inbox_and_footer(desk):
    from aidec import inbox
    from datetime import datetime
    inbox.write(desk, inbox.Item("r1", "raise", "macro-mon", None, 5, datetime(2027, 10, 1), False, "補講日がほしい"))
    out = run(desk, "--date", "2027-10-18")
    assert "r1 macro-mon 第 5 回: 補講日がほしい" in out
    assert out.rstrip().splitlines()[-1] == "授業レポは未 fetch"


def test_cli_dispatch_and_config_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AIDEC_CONFIG", str(tmp_path / "none.yaml"))
    assert main(["brief", "2027"]) == 1
    assert "none.yaml" in capsys.readouterr().err
