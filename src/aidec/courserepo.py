"""授業レポの置き方（SPEC §8.2・§8.8）。

新しい置き方: course root（レポのルート）に team.yaml、class root（classes/<class id>/）に
course.yaml・packet.yaml・schedule.yaml。まだ classes/ に移っていないレポは <年度>/ に team.yaml を置く。
"""
from __future__ import annotations

from pathlib import Path

from . import yamlio


def _load_map(path: Path) -> dict:
    if path.is_file():
        try:
            doc = yamlio.load(path)
            return doc if isinstance(doc, dict) else {}
        except yamlio.YamlError:
            pass
    return {}


def class_root(repo: Path, class_id: str | None) -> Path | None:
    """日程を置く class root。classes/<class_id>/ だけを見る（<年度>/ は見ない）。

    そこの course.yaml の classes がちょうど 1 つで、その id が class_id のときだけ返す。
    """
    if not class_id:
        return None
    root = repo / "classes" / class_id
    classes = _load_map(root / "course.yaml").get("classes")
    if not isinstance(classes, list) or len(classes) != 1:
        return None
    only = classes[0]
    if not isinstance(only, dict) or str(only.get("id")) != class_id:
        return None
    return root


def class_dir(repo: Path, year: int, class_id: str | None) -> Path:
    """回のディレクトリなどを読む場所。classes/<class_id>/ があればそこ、無ければ <年度>/。"""
    if class_id and (repo / "classes" / class_id).is_dir():
        return repo / "classes" / class_id
    return repo / str(year)


def team(repo: Path, cdir: Path) -> dict:
    """team.yaml。course root にあればそれ、無ければ cdir（移っていないレポの <年度>/）のもの。"""
    path = repo / "team.yaml"
    return _load_map(path if path.is_file() else cdir / "team.yaml")


def layout(cdir: Path, doc: dict | None = None) -> tuple[str, Path]:
    """(回のディレクトリの書式, course-map のパス)。

    cdir に packet.yaml があれば sessions.dir・sessions.map をそこから読む。
    無ければ旧い team.yaml の sessions.dir と map を読む。すでに読んだ team.yaml があれば doc で渡す。
    """
    packet = cdir / "packet.yaml"
    if packet.is_file():
        sessions = _load_map(packet).get("sessions")
        sessions = sessions if isinstance(sessions, dict) else {}
        cmap = sessions.get("map")
    else:
        doc = _load_map(cdir / "team.yaml") if doc is None else doc
        sessions = doc.get("sessions")
        sessions = sessions if isinstance(sessions, dict) else {}
        cmap = doc.get("map")
    return str(sessions.get("dir") or "{nn}"), cdir / str(cmap or "course-map.md")


def base_branch(doc: dict) -> str | None:
    """回の受け入れを見る枝（team.yaml の sessions.base）。"""
    sessions = doc.get("sessions")
    base = sessions.get("base") if isinstance(sessions, dict) else None
    return str(base) if base else None


def session_dir(pattern: str, n: int) -> str | None:
    """回 n のディレクトリ名。書式に合わなければ None。"""
    try:
        return pattern.format(nn=f"{n:02d}", n=n)
    except (KeyError, IndexError, ValueError, AttributeError):
        return None
