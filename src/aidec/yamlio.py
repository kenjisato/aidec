"""YAML の読み書き。コメントと並びを保ち、書くときは UTF-8・LF に揃える。"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError


class YamlError(ValueError):
    pass


def _yaml() -> YAML:
    y = YAML()
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def loads(text: str) -> Any:
    return _yaml().load(text)


def load(path: Path) -> Any:
    """読めなければ（実在しない日付なども）、ファイル名を付けて YamlError にする。"""
    try:
        with open(path, encoding="utf-8") as f:
            return _yaml().load(f)
    except (ValueError, YAMLError) as e:
        raise YamlError(f"{path.name}: 読めない（{e}）") from None


def dumps(data: Any) -> str:
    buf = io.StringIO()
    _yaml().dump(data, buf)
    return buf.getvalue()


def dump(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(dumps(data))


def flow_map(d: dict) -> CommentedMap:
    m = CommentedMap(d)
    m.fa.set_flow_style()
    return m


def flow_seq(items: list) -> CommentedSeq:
    s = CommentedSeq(items)
    s.fa.set_flow_style()
    return s
