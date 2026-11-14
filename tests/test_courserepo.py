import pytest

from conftest import write
from aidec.courserepo import base_branch, class_dir, class_root, course_id, layout, team

# IK の course.id（macro-2027）は courses.yaml の id（macro-mon）と別のもの。日程の course: には前者を書く
COURSE_YAML = """\
classes:
  - id: 2027-mon3
    destinations: [{to: manual}]
"""


@pytest.fixture
def repo(tmp_path):
    return tmp_path / "macro-mon"


def test_class_root(repo):
    write(repo / "classes" / "2027-mon3" / "class.yaml", COURSE_YAML)
    assert class_root(repo, "2027-mon3") == repo / "classes" / "2027-mon3"


@pytest.mark.parametrize("text", [
    "x: 1\n",                                                                        # classes が無い
    COURSE_YAML + "  - id: 2027-wed2\n    destinations: [{to: manual}]\n",       # 2 つある
    COURSE_YAML.replace("2027-mon3", "2027-tue1"),                               # id が違う
    "course: [\n",                                                               # 読めない
])
def test_class_root_none(repo, text):
    write(repo / "classes" / "2027-mon3" / "class.yaml", text)
    assert class_root(repo, "2027-mon3") is None


def test_course_id(repo):
    assert course_id(repo) is None
    write(repo / "course.yaml", "id: macro-2027\ntitle: t\n")
    assert course_id(repo) == "macro-2027"


def test_class_root_none_with_only_old_course_yaml(repo):
    write(repo / "classes" / "2027-mon3" / "course.yaml", "course: {id: macro-2027}\n" + COURSE_YAML)
    assert class_root(repo, "2027-mon3") is None


def test_class_root_ignores_year_dir(repo):
    write(repo / "2027" / "class.yaml", COURSE_YAML)
    assert class_root(repo, "2027-mon3") is None
    assert class_root(repo, None) is None


def test_class_dir(repo):
    assert class_dir(repo, 2027, "2027-mon3") == repo / "2027"
    assert class_dir(repo, 2027, None) == repo / "2027"
    (repo / "classes" / "2027-mon3").mkdir(parents=True)
    assert class_dir(repo, 2027, "2027-mon3") == repo / "classes" / "2027-mon3"


def test_new_layout_reads_team_from_course_root_and_packet(repo):
    cdir = repo / "classes" / "2027-mon3"
    write(repo / "team.yaml", "course_id: macro-2027\nsessions: {base: develop}\n")
    write(cdir / "packet.yaml", "sessions: {dir: 'sessions/{nn}', map: plan/map.md}\n")
    doc = team(repo, cdir)
    assert base_branch(doc) == "develop"
    assert layout(cdir, doc) == ("sessions/{nn}", cdir / "plan" / "map.md")
    assert layout(cdir) == ("sessions/{nn}", cdir / "plan" / "map.md")


def test_packet_without_map_uses_default(repo):
    cdir = repo / "classes" / "2027-mon3"
    write(cdir / "packet.yaml", "sessions: {dir: '{nn}'}\n")
    assert layout(cdir) == ("{nn}", cdir / "course-map.md")


def test_old_layout_reads_year_dir(repo):
    ydir = repo / "2027"
    write(ydir / "team.yaml", "sessions: {dir: 's{nn}', base: main}\nmap: m.md\n")
    doc = team(repo, ydir)
    assert base_branch(doc) == "main"
    assert layout(ydir, doc) == ("s{nn}", ydir / "m.md")
    assert layout(ydir) == ("s{nn}", ydir / "m.md")


def test_nothing_written(repo):
    ydir = repo / "2027"
    assert team(repo, ydir) == {}
    assert layout(ydir) == ("{nn}", ydir / "course-map.md")
