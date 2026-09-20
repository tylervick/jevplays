import json

from jevplays.cli import main


def test_state_command_prints_the_snapshot_as_json(rom, state_path, capsys, monkeypatch):
    monkeypatch.setenv("JEVPLAYS_ROM", str(rom))
    assert main(["state", str(state_path("overworld"))]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "overworld"
    assert out["map"] == "Red's House 2F"


def test_state_command_without_rom_is_an_error(monkeypatch, capsys):
    monkeypatch.delenv("JEVPLAYS_ROM", raising=False)
    assert main(["state", "whatever.state"]) == 2
    assert "JEVPLAYS_ROM" in capsys.readouterr().err
