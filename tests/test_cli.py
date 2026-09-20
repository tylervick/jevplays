from jevplays.cli import main


def test_state_command_without_rom_is_an_error(monkeypatch, capsys):
    monkeypatch.delenv("JEVPLAYS_ROM", raising=False)
    assert main(["state", "whatever.state"]) == 2
    assert "JEVPLAYS_ROM" in capsys.readouterr().err


def test_state_command_with_missing_file_is_an_error(monkeypatch, capsys):
    # A path that exists so the ROM check passes; the state-file check must fail before pyboy
    # is ever imported (see test_imports.py for the no-pyboy-import invariant itself), so this
    # needs no real ROM.
    monkeypatch.setenv("JEVPLAYS_ROM", __file__)
    assert main(["state", "no-such-file.state"]) == 2
    assert "no-such-file.state" in capsys.readouterr().err


def test_run_command_without_rom_is_an_error(monkeypatch, capsys):
    monkeypatch.delenv("JEVPLAYS_ROM", raising=False)
    assert main(["run"]) == 2
    assert "JEVPLAYS_ROM" in capsys.readouterr().err


def test_run_help_lists_the_brain_flags(capsys):
    import pytest

    with pytest.raises(SystemExit):
        main(["run", "--help"])
    out = capsys.readouterr().out
    assert "--no-brain" in out and "--goal" in out
