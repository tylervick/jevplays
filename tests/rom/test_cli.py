import json

from jevplays.cli import main


def test_state_command_prints_the_snapshot_as_json(rom, state_path, capsys, monkeypatch):
    monkeypatch.setenv("JEVPLAYS_ROM", str(rom))
    assert main(["state", str(state_path("overworld"))]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "overworld"
    assert out["map"] == "Red's House 2F"
