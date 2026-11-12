"""授業から上がってきた相談（inbox/<ref>.md）の読み書き。"""
from __future__ import annotations

import io
import secrets
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from ruamel.yaml import YAML, YAMLError

_FIELDS = ("ref", "verb", "course", "class", "session", "received", "no_reply")


@dataclass(frozen=True)
class Item:
    ref: str
    verb: str
    course: str
    cls: str | None
    session: int | None
    received: datetime
    no_reply: bool
    text: str


def new_ref(today: date, course: str) -> str:
    """機械をまたいでも重ならないよう、末尾に乱数を付ける。"""
    return f"{today:%Y%m%d}-{course}-{secrets.token_hex(3)}"


def write(data_dir: Path, item: Item) -> Path:
    meta = {"ref": item.ref, "verb": item.verb, "course": item.course, "class": item.cls,
            "session": item.session, "received": item.received.isoformat(), "no_reply": item.no_reply}
    buf = io.StringIO()
    y = YAML(typ="safe")
    y.default_flow_style = False
    y.allow_unicode = True
    y.dump(meta, buf)
    path = data_dir / "inbox" / f"{item.ref}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"---\n{buf.getvalue()}---\n{item.text.rstrip()}\n")
    return path


def _read(path: Path) -> Item:
    raw = path.read_text(encoding="utf-8")
    _, front, body = raw.split("---\n", 2)
    meta = YAML(typ="safe").load(front)
    received = meta["received"]
    if not isinstance(received, datetime):
        received = datetime.fromisoformat(str(received))
    session = meta.get("session")
    return Item(str(meta["ref"]), str(meta["verb"]), str(meta["course"]), meta.get("class"),
                None if session is None else int(session), received, bool(meta.get("no_reply")),
                body.rstrip("\n"))


def load(data_dir: Path) -> tuple[list[Item], list[str]]:
    """読めたものと、読めなかったファイル名。"""
    items, bad = [], []
    for path in sorted((data_dir / "inbox").glob("*.md")):
        try:
            items.append(_read(path))
        except (ValueError, KeyError, TypeError, AttributeError, YAMLError, OSError):
            bad.append(path.name)
    return items, bad
