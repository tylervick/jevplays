from jevplays.cli import main


def test_state_command_without_rom_is_an_error(monkeypatch, capsys):
    monkeypatch.delenv("JEVPLAYS_ROM", raising=False)
    assert main(["state", "whatever.state"]) == 2
    assert "JEVPLAYS_ROM" in capsys.readouterr().err


def test_run_command_without_rom_is_an_error(monkeypatch, capsys):
    monkeypatch.delenv("JEVPLAYS_ROM", raising=False)
    assert main(["run"]) == 2
    assert "JEVPLAYS_ROM" in capsys.readouterr().err
