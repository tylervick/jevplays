import asyncio

from jevplays.loop import Loop, LoopConfig
from jevplays.runlog import RunDir
from tests.support import FakeEmulator
from tests.test_loop import QuestionBrain, RecordingBroadcaster, explore_emu


def test_a_snapshot_writes_the_state_and_its_sidecar(tmp_path):
    run = RunDir.create(tmp_path, rom=None, flags={})
    path = run.snapshot(FakeEmulator(), 3, {"frame": 120, "milestone": "get_pokedex", "memory": {}})
    assert path == run.snapshots_path / "3.state" and path.is_file()
    assert run.snapshot_state(3) == path
    assert run.snapshot_info(3) == {"frame": 120, "milestone": "get_pokedex", "memory": {}}
    assert run.snapshot_state(4) is None and run.snapshot_info(4) is None


def test_milestones_done_keeps_the_first_frame_of_each(tmp_path):
    run = RunDir.create(tmp_path, rom=None, flags={})
    assert run.milestones_done() == {}
    run.note_milestone("get_starter", 500)
    run.note_milestone("get_pokedex", 9000)
    run.note_milestone("get_starter", 9999)
    assert run.milestones_done() == {"get_starter": 500, "get_pokedex": 9000}


def test_the_loop_snapshots_every_decision_when_asked(tmp_path):
    run = RunDir.create(tmp_path, rom=None, flags={})
    loop = Loop(
        explore_emu(),
        RecordingBroadcaster(),
        LoopConfig(paced=False, snapshot_every_decision=True),
        brain=QuestionBrain(explore="exit_north", needs_heal=0.1),
        run_dir=run,
    )
    asyncio.run(loop.run(max_iterations=1))
    assert run.count() == 1
    info = run.snapshot_info(1)
    assert set(info) == {"frame", "milestone", "memory"}
    assert info["memory"] == loop.memory.to_dict()


def test_the_loop_takes_no_snapshots_by_default(tmp_path):
    run = RunDir.create(tmp_path, rom=None, flags={})
    loop = Loop(
        explore_emu(),
        RecordingBroadcaster(),
        LoopConfig(paced=False),
        brain=QuestionBrain(explore="exit_north", needs_heal=0.1),
        run_dir=run,
    )
    asyncio.run(loop.run(max_iterations=1))
    assert not run.snapshots_path.exists()
