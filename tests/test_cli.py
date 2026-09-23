import json

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


def test_resume_and_no_log_together_are_rejected(capsys):
    import pytest

    with pytest.raises(SystemExit) as exc:
        main(["run", "--resume", "runs/x", "--no-log"])
    assert exc.value.code == 2
    assert "--no-log" in capsys.readouterr().err


def test_resolve_resume_picks_the_newest_checkpoint_and_sets_later_decisions_aside(tmp_path):
    from jevplays.brain.decision import Decision, PromptAction
    from jevplays.cli import resolve_resume
    from jevplays.runlog import RunDir
    from tests.support import FakeEmulator

    run = RunDir.create(tmp_path / "runs", rom=None, flags={})
    for i in range(28):
        run.append(
            Decision(
                id=f"d{i}",
                ts=float(i),
                kind="prompt",
                state_summary={},
                questions={},
                answers={},
                action="answer YES",
                action_value=PromptAction(yes=True),
            )
        )
        if (i + 1) % 25 == 0:
            run.checkpoint(FakeEmulator(), i + 1)

    path, n, orphaned = resolve_resume(run)
    assert path.name == "checkpoint-25.state" and n == 25 and orphaned == 3
    assert run.count() == 25
    assert [
        json.loads(line)["id"] for line in (run.path / "decisions.orphaned.jsonl").read_text().splitlines()
    ] == [
        "d25",
        "d26",
        "d27",
    ]
    assert run.info()["resumed_at"][0]["from_checkpoint"] == 25
    assert run.info()["resumed_at"][0]["orphaned"] == 3


def test_resume_hands_the_loop_the_memory_the_run_kept(tmp_path):
    """The run dir carries `memory.json` across a restart, so a resumed run is not amnesiac:
    it still knows which maps it has seen and which options came to nothing."""
    from jevplays.cli import resume_memory
    from jevplays.runlog import RunDir

    run = RunDir.create(tmp_path / "runs", rom=None, flags={})
    run.save_memory({"visited_maps": [0, 41], "talked": [[41, 3]], "tried": [[0, "grass"]]})

    memory = resume_memory(RunDir.open(run.path))
    assert memory.visited_maps == {0, 41}
    assert memory.talked == {(41, 3)} and memory.tried == {(0, "grass")}


def test_resume_without_a_memory_file_starts_from_an_empty_one(tmp_path):
    from jevplays.cli import resume_memory
    from jevplays.runlog import RunDir

    run = RunDir.create(tmp_path / "runs", rom=None, flags={})
    memory = resume_memory(run)
    assert memory.visited_maps == set() and memory.talked == set() and memory.tried == set()


def test_resolve_resume_without_a_checkpoint_raises(tmp_path):
    import pytest

    from jevplays.cli import resolve_resume
    from jevplays.runlog import RunDir

    run = RunDir.create(tmp_path / "runs", rom=None, flags={})
    with pytest.raises(FileNotFoundError, match="checkpoint"):
        resolve_resume(run)


def test_run_and_replay_take_a_host_so_another_device_can_watch(capsys):
    import pytest

    for command in ("run", "replay"):
        with pytest.raises(SystemExit):
            main([command, "--help"])
        assert "--host" in capsys.readouterr().out


def test_the_dashboard_stays_on_localhost_unless_asked(monkeypatch):
    from jevplays.cli import build_parser

    args = build_parser().parse_args(["run"])
    assert args.host == "127.0.0.1"
    assert build_parser().parse_args(["run", "--host", "0.0.0.0"]).host == "0.0.0.0"


def test_the_printed_dashboard_url_names_an_address_a_browser_can_open():
    """0.0.0.0 is every interface, not somewhere to point a browser -- least of all a browser on
    the other device the flag exists for."""
    from jevplays.cli import dashboard_url

    assert dashboard_url("127.0.0.1", 8765) == "http://127.0.0.1:8765"
    wide = dashboard_url("0.0.0.0", 8765)
    assert not wide.startswith("http://0.0.0.0") and wide.endswith(":8765")


def test_run_takes_a_speed_multiplier_that_defaults_to_real_time():
    from jevplays.cli import build_parser

    parser = build_parser()
    assert parser.parse_args(["run"]).speed == 1.0
    assert parser.parse_args(["run", "--speed", "6"]).speed == 6.0


def test_run_takes_the_demo_limits_and_leaves_them_off_by_default():
    """A run on the command line plays until stopped for whoever is at the keyboard; only the demo
    behind a public link pauses when nobody watches, rests at a daily budget, and turns viewers
    away past a limit."""
    from jevplays.cli import build_parser

    parser = build_parser()
    plain = parser.parse_args(["run"])
    assert (plain.pause_after, plain.max_decisions, plain.max_viewers) == (None, None, None)
    demo = parser.parse_args(["run", "--pause-after", "60", "--max-decisions", "40", "--max-viewers", "20"])
    assert (demo.pause_after, demo.max_decisions, demo.max_viewers) == (60.0, 40, 20)


def test_snapshots_cannot_be_combined_with_resume_or_no_log(tmp_path, capsys):
    import pytest

    from jevplays.cli import main

    for extra in (["--resume", str(tmp_path)], ["--no-log"]):
        with pytest.raises(SystemExit):
            main(["run", "--snapshot-every-decision", *extra])
        assert "--snapshot-every-decision" in capsys.readouterr().err


def test_branch_needs_at_least_two_seeds_and_one_worker(capsys):
    import pytest

    from jevplays.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["branch", "run", "--seeds", "2", "--workers", "1"])
    assert (args.seeds, args.workers) == (2, 1)
    for bad in (
        ["--seeds", "1"],
        ["--seeds", "0"],
        ["--workers", "0"],
        ["--workers", "-3"],
        ["--seeds", "x"],
    ):
        with pytest.raises(SystemExit):
            parser.parse_args(["branch", "run", *bad])
        assert bad[0] in capsys.readouterr().err
