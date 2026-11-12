from pathlib import Path

import pytest

from aidec.config import ConfigError, data_dir


def _config(tmp_path, monkeypatch, text):
    f = tmp_path / "config.yaml"
    f.write_text(text, encoding="utf-8")
    monkeypatch.setenv("AIDEC_CONFIG", str(f))
    return f


def test_reads_data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    _config(tmp_path, monkeypatch, f"data_dir: {d.as_posix()}\n")
    assert data_dir() == d


def test_expands_tilde(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    _config(tmp_path, monkeypatch, "data_dir: ~/data\n")
    assert data_dir() == Path(tmp_path / "data")


def test_default_file_is_under_home(tmp_path, monkeypatch):
    monkeypatch.delenv("AIDEC_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "data").mkdir()
    cfg = tmp_path / ".config" / "aidec" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(f"data_dir: {(tmp_path / 'data').as_posix()}\n", encoding="utf-8")
    assert data_dir() == tmp_path / "data"


def test_missing_file(tmp_path, monkeypatch):
    f = tmp_path / "nope.yaml"
    monkeypatch.setenv("AIDEC_CONFIG", str(f))
    with pytest.raises(ConfigError, match="nope.yaml"):
        data_dir()


def test_missing_key(tmp_path, monkeypatch):
    f = _config(tmp_path, monkeypatch, "other: 1\n")
    with pytest.raises(ConfigError, match="data_dir") as e:
        data_dir()
    assert str(f) in str(e.value)


def test_missing_directory(tmp_path, monkeypatch):
    f = _config(tmp_path, monkeypatch, f"data_dir: {(tmp_path / 'gone').as_posix()}\n")
    with pytest.raises(ConfigError, match="gone") as e:
        data_dir()
    assert str(f) in str(e.value)
