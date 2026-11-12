"""設定ファイルから data_dir（データのレポの場所）を知る。"""
from __future__ import annotations

import os
from pathlib import Path

from ruamel.yaml import YAML, YAMLError


class ConfigError(Exception):
    pass


def config_path() -> Path:
    env = os.environ.get("AIDEC_CONFIG")
    return Path(env).expanduser() if env else Path.home() / ".config" / "aidec" / "config.yaml"


def data_dir() -> Path:
    path = config_path()
    if not path.is_file():
        raise ConfigError(f"設定ファイル {path} が無い。data_dir: <データのレポのパス> と書く")
    try:
        doc = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    except (YAMLError, OSError) as e:
        raise ConfigError(f"設定ファイル {path} を読めない: {e}") from e
    value = doc.get("data_dir") if isinstance(doc, dict) else None
    if not isinstance(value, str) or not value:
        raise ConfigError(f"設定ファイル {path} に data_dir が無い")
    d = Path(value).expanduser()
    if not d.is_dir():
        raise ConfigError(f"設定ファイル {path} の data_dir {d} がディレクトリではない")
    return d
