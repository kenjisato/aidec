import subprocess

import pytest
from ruamel.yaml import YAML

from classdays.calendar import calendar_from_dict

CALENDAR_UNIVA_2027 = """\
university: univa
year: 2027
source: "架空の学事暦（テスト用）"
terms:
  fall: {start: 2027-09-27, end: 2028-01-25}
no_class: [2027-11-03, 2027-12-27, 2028-01-03]
swap: [{date: 2027-12-22, as: mon}]
makeup_days: [2027-10-23, 2027-11-20]
exams: {start: 2028-01-26, end: 2028-02-01}
amendments:
  - announced: 2027-11-05
    source: 暴風警報による全学休講
    add_no_class: [2027-11-08]
"""

COURSES_2027 = """\
- id: macro-mon
  repo: github.com/example/macro-mon
  calendar: univa
  term: fall
  slot: mon-3
  sessions: 16
- id: seminar-wed
  repo: github.com/example/seminar-wed
  calendar: univa
  term: fall
  slot: wed-2
  sessions: 15
"""

EVENTS_2027 = """\
- {date: 2027-10-18, end: 2027-10-20, kind: trip, title: 学会（○○）}
- {date: 2028-01-10, kind: deadline, title: 卒論提出, prep: 2w}
"""


def safe_load(text):
    return YAML(typ="safe").load(text)


@pytest.fixture
def cal():
    return calendar_from_dict(safe_load(CALENDAR_UNIVA_2027))


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


@pytest.fixture
def year_dir(tmp_path):
    d = tmp_path / "workdesk" / "2027"
    write(d / "calendar-univa.yaml", CALENDAR_UNIVA_2027)
    write(d / "courses.yaml", COURSES_2027)
    write(d / "events.yaml", EVENTS_2027)
    return d


def run_git(repo, *args):
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stderr
    return p.stdout


@pytest.fixture
def git_env(tmp_path, monkeypatch):
    """利用者の ~/.gitconfig（hook・署名など）を読ませない。"""
    cfg = tmp_path / "gitconfig"
    cfg.write_text("[user]\n\tname = Test\n\temail = test@example.com\n"
                   "[init]\n\tdefaultBranch = main\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def make_repo(path, remote=None):
    """path に git レポを作って最初のコミットを入れる。remote を渡すと bare を作って push する。"""
    path.mkdir(parents=True, exist_ok=True)
    run_git(path, "init", "-q")
    if not any(p.name != ".git" for p in path.iterdir()):
        write(path / "README.md", "test\n")
    run_git(path, "add", "-A")
    run_git(path, "commit", "-q", "-m", "init")
    if remote is not None:
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        run_git(path, "remote", "add", "origin", str(remote))
        run_git(path, "push", "-q", "-u", "origin", "main")
    return path


@pytest.fixture
def workdesk_root(year_dir, git_env):
    return make_repo(year_dir.parent)


@pytest.fixture
def ghq(tmp_path, git_env, monkeypatch):
    root = tmp_path / "ghq"
    for name in ("macro-mon", "seminar-wed"):
        make_repo(root / "github.com" / "example" / name, tmp_path / "remotes" / f"{name}.git")
    monkeypatch.setenv("AIDEC_GHQ_ROOT", str(root))
    return root


@pytest.fixture(autouse=True)
def no_real_sr(monkeypatch):
    """テストが手元の sr（通信する）を呼ばないように。"""
    from aidec import repos
    monkeypatch.setattr(repos, "SR", "aidec-test-no-such-sr")


# 授業の id -> (IK の course.id, class id)
CLASSES = {"macro-mon": ("macro-2027", "2027-mon3"), "seminar-wed": ("seminar-2027", "2027-wed2")}


def add_class(year_dir, ghq, name):
    """courses.yaml の授業 name に class: を付け、授業レポに classes/<id>/class.yaml と course.yaml（id）を置く。class root を返す。"""
    cid, cls = CLASSES[name]
    p = year_dir / "courses.yaml"
    text = p.read_text(encoding="utf-8")
    write(p, text.replace(f"repo: github.com/example/{name}\n", f"repo: github.com/example/{name}\n  class: {cls}\n")
          .replace(f"repo: github.com/example/{name},", f"repo: github.com/example/{name}, class: {cls},"))
    croot = ghq / "github.com" / "example" / name / "classes" / cls
    write(croot.parent.parent / "course.yaml", f"id: {cid}\ntitle: t\n")
    write(croot / "class.yaml", f"classes:\n  - id: {cls}\n    destinations: [{{to: manual}}]\n")
    return croot


def issue_schedule(year_dir, ghq, name, edit=None):
    """今の学事暦・moves どおりの schedule.yaml を class root に置く。edit で本文を書き換えられる。"""
    from aidec import courserepo
    from aidec.data import load_year
    from aidec.schedule import build_dates, write_dates
    croot = add_class(year_dir, ghq, name) if not (ghq / "github.com" / "example" / name / "classes").is_dir() \
        else ghq / "github.com" / "example" / name / "classes" / CLASSES[name][1]
    yd = load_year(year_dir)
    (course,) = [c for c in yd.courses if c.id == name]
    path = croot / "schedule.yaml"
    write_dates(path, build_dates(course, yd.calendar_for(course), yd.events, yd.moves,
                                  "2027-09-01 (abc1234)", course_id=courserepo.course_id(croot.parent.parent)))
    if edit is not None:
        write(path, edit(path.read_text(encoding="utf-8")))
    return croot
