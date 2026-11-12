from aidec.cli import main


def test_unknown_subcommand(capsys):
    assert main(["nope"]) == 2
    assert "usage: aidec" in capsys.readouterr().err


def test_without_config_the_command_stops_with_a_message(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AIDEC_CONFIG", str(tmp_path / "none.yaml"))
    assert main(["week", "2027"]) == 1
    assert "none.yaml" in capsys.readouterr().err
