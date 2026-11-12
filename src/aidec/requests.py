"""依頼ファイル（requests/<id>.md）。front matter に宛先・期限・状態を書き、本文に事実を書く。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

STATUSES = ("open", "reported", "closed")
_KEYS = ("id", "to", "issued", "decide_by", "status", "dates")


class RequestError(ValueError):
    pass


@dataclass
class Request:
    id: str
    to: str
    issued: date
    decide_by: date
    status: str
    dates: list[date]
    body: str


def format_request(r: Request) -> str:
    front = [
        f"id: {r.id}",
        f"to: {r.to}",
        f"issued: {r.issued.isoformat()}",
        f"decide_by: {r.decide_by.isoformat()}",
        f"status: {r.status}",
        "dates: [" + ", ".join(d.isoformat() for d in r.dates) + "]",
    ]
    return "---\n" + "\n".join(front) + "\n---\n" + r.body.rstrip("\n") + "\n"


def _split(text: str, where: str, err: type[ValueError]) -> tuple[list[str], int]:
    """行の列と、front matter を閉じる --- の行番号。"""
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        raise err(f"{where}: --- で始まる front matter が無い")
    try:
        return lines, next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise err(f"{where}: front matter を閉じる --- が無い") from None


def read_front(text: str, where: str, err: type[ValueError] = RequestError) -> tuple[dict, str]:
    """front matter（対応づけ）と本文。"""
    lines, end = _split(text, where, err)
    try:
        meta = YAML(typ="safe").load("\n".join(lines[1:end])) or {}
    except (ValueError, YAMLError) as e:
        raise err(f"{where}: 読めない（{e}）") from None
    if not isinstance(meta, dict):
        raise err(f"{where}: front matter は対応づけで書く")
    return meta, "\n".join(lines[end + 1:]).strip("\n") + "\n"


def parse_request(text: str, where: str) -> Request:
    meta, body = read_front(text, where)
    for k in _KEYS:
        if k not in meta:
            raise RequestError(f"{where}: {k} が無い")
    if meta["status"] not in STATUSES:
        raise RequestError(f"{where}: status は {' / '.join(STATUSES)} のどれか: {meta['status']!r}")
    for k in ("issued", "decide_by"):
        if not isinstance(meta[k], date):
            raise RequestError(f"{where}: {k} が日付として読めない")
    return Request(str(meta["id"]), str(meta["to"]), meta["issued"], meta["decide_by"],
                   meta["status"], list(meta["dates"] or []), body)


def set_status(path: Path, old: tuple[str, ...], new: str) -> None:
    """front matter の status: 行だけを書き換える。今の値が old のどれでもなければ止める。"""
    lines, end = _split(path.read_text(encoding="utf-8"), path.name, RequestError)
    for i in range(1, end):
        m = re.match(r"^(status:\s*)(\S+)(.*)$", lines[i])
        if m:
            if m.group(2) not in old:
                raise RequestError(f"{path.name}: status が {m.group(2)} になっている"
                                   f"（{' / '.join(old)} のときだけ {new} にする）")
            lines[i] = m.group(1) + new + m.group(3)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(lines))
            return
    raise RequestError(f"{path.name}: status が無い")


def write_request(dir: Path, r: Request) -> Path:
    path = dir / f"{r.id}.md"
    if path.exists():
        raise RequestError(f"{path} は既にある")
    dir.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(format_request(r))
    return path


def load_requests(dir: Path) -> list[Request]:
    if not dir.is_dir():
        return []
    return [parse_request(p.read_text(encoding="utf-8"), p.name) for p in sorted(dir.glob("*.md"))]


def next_request_id(dir: Path, issued: date, course_id: str) -> str:
    base = f"{issued.isoformat()}-{course_id}"
    rid, k = base, 1
    while (dir / f"{rid}.md").exists():
        k += 1
        rid = f"{base}-{k}"
    return rid
