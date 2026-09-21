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


def test_run_help_lists_the_run_dir_flags(capsys):
    import pytest

    with pytest.raises(SystemExit):
        main(["run", "--help"])
    out = capsys.readouterr().out
    assert "--runs-dir" in out and "--resume" in out and "--no-log" in out


def test_resume_without_a_checkpoint_is_an_error(monkeypatch, tmp_path, capsys):
    from jevplays.runlog import RunDir

    rom = tmp_path / "game.gb"
    rom.write_bytes(b"rom")
    monkeypatch.setenv("JEVPLAYS_ROM", str(rom))
    run = RunDir.create(tmp_path / "runs", rom=rom, flags={})
    assert main(["run", "--resume", str(run.path)]) == 2
    assert "checkpoint" in capsys.readouterr().err


def test_state_and_resume_together_are_rejected(capsys):
    import pytest

    with pytest.raises(SystemExit) as exc:
        main(["run", "--state", "a.state", "--resume", "runs/x"])
    assert exc.value.code == 2
