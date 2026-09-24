import pytest

from jevplays.brain.decision import Decision
from jevplays.branch.runner import SeedsMismatch, candidates, check_seeds
from jevplays.branch.store import BranchStore
from jevplays.runlog import RunDir
from tests.support import FakeEmulator


def decision(kind="battle", fallback=False, questions=True, forced=False):
    return Decision(
        id="x",
        ts=0.0,
        kind=kind,
        state_summary={},
        questions={"q": {}} if questions else {},
        answers={},
        action="use EMBER",
        fallback=fallback,
        forced=forced,
    )


def recorded(tmp_path, decisions, frames, milestone_done=None):
    run = RunDir.create(tmp_path, rom=None, flags={})
    for n, (d, frame) in enumerate(zip(decisions, frames, strict=True), start=1):
        run.append(d)
        run.snapshot(FakeEmulator(), n, {"frame": frame, "milestone": "get_pokedex", "memory": {}})
    if milestone_done is not None:
        run.note_milestone("get_pokedex", milestone_done)
    return run


def test_candidates_are_jevs_battle_and_explore_decisions_with_their_reference(tmp_path):
    ds = [
        decision(),
        decision("explore"),
        decision("prompt"),
        decision(fallback=True),
        decision(questions=False),
    ]
    run = recorded(tmp_path, ds, [100, 200, 300, 400, 500], milestone_done=1100)
    got = candidates(run)
    assert [c.n for c in got] == [1, 2]
    assert [c.reference_frames for c in got] == [1000, 900]
    assert got[0].state == run.snapshot_state(1)


def test_a_milestone_the_run_never_finished_leaves_no_reference(tmp_path):
    run = recorded(tmp_path, [decision()], [100])
    assert candidates(run)[0].reference_frames is None


def test_a_run_recorded_without_snapshots_is_refused(tmp_path):
    """Review focus 5."""
    run = RunDir.create(tmp_path, rom=None, flags={})
    run.append(decision())
    with pytest.raises(FileNotFoundError, match="--snapshot-every-decision"):
        candidates(run)


def test_a_measurement_refuses_a_different_seed_count(tmp_path):
    """Review focus 4."""
    store = BranchStore(tmp_path / "b.sqlite")
    check_seeds(store, 8)
    assert store.meta()["seeds"] == "8"
    check_seeds(store, 8)
    with pytest.raises(SeedsMismatch, match="8"):
        check_seeds(store, 4)


def test_the_branch_command_needs_an_api_key(tmp_path, monkeypatch, capsys):
    from jevplays.cli import main

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    rom = tmp_path / "rom.gb"
    rom.write_bytes(b"")
    assert main(["branch", str(tmp_path), "--rom", str(rom)]) == 2
    assert "TYPESAFE_API_KEY" in capsys.readouterr().err
