"""授業レポの <年度>/ の置き方（team.yaml）。"""
from __future__ import annotations

from pathlib import Path

from . import yamlio


def team(year_dir: Path) -> dict:
    path = year_dir / "team.yaml"
    if path.is_file():
        try:
            doc = yamlio.load(path)
            return doc if isinstance(doc, dict) else {}
        except yamlio.YamlError:
            pass
    return {}


def layout(year_dir: Path, doc: dict | None = None) -> tuple[str, Path]:
    """(回のディレクトリの書式, course-map のパス)。team.yaml があればそれに従う。

    すでに読んだ team.yaml があれば doc で渡す。
    """
    doc = team(year_dir) if doc is None else doc
    sessions = doc.get("sessions")
    pattern = str(sessions.get("dir") or "{nn}") if isinstance(sessions, dict) else "{nn}"
    return pattern, year_dir / str(doc.get("map") or "course-map.md")


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
