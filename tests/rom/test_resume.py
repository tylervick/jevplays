"""A run leaves checkpoints behind and a resumed run continues from the newest one."""

from jevplays.emulator import ram
from jevplays.emulator.pyboy import Emulator
from jevplays.loop import Loop, LoopConfig
from jevplays.runlog import CHECKPOINT_EVERY, RunDir
from tests.rom.test_loop_overworld import FirstChoiceBrain  # the stand-in brain


class Quiet:
    async def publish(self, event):
        pass


def test_a_run_checkpoints_and_resumes_from_the_newest_one(rom, state_path, tmp_path):
    import asyncio

    run_dir = RunDir.create(tmp_path, rom=rom, flags={"state": "route1"})
    with Emulator(rom) as emu:
        emu.load(state_path("route1"))
        loop = Loop(
            emu, Quiet(), LoopConfig(paced=False, fps=0.001), brain=FirstChoiceBrain(), run_dir=run_dir
        )
        # 400 iterations (the brief's original figure) decides only ~12 times on this ROM/state;
        # 1200 -- the same budget test_loop_overworld's full parcel walk uses -- clears the
        # CHECKPOINT_EVERY threshold with margin (measured: 36 decisions).
        asyncio.run(loop.run(max_iterations=1200))
        asyncio.run(loop.checkpoint())
        made = loop.decision_count
        map_at_exit = emu.mem[ram.wCurMap]
    assert made >= CHECKPOINT_EVERY, "1200 iterations from Route 1 decide at least 25 times"
    newest = run_dir.last_checkpoint()
    assert newest is not None and newest.name == f"checkpoint-{made}.state"
    assert run_dir.count() == made

    resumed = RunDir.open(run_dir.path)
    resumed.mark_resumed()
    with Emulator(rom) as emu:
        emu.load(resumed.last_checkpoint())
        assert emu.mem[ram.wCurMap] == map_at_exit
        loop = Loop(
            emu, Quiet(), LoopConfig(paced=False, fps=0.001), brain=FirstChoiceBrain(), run_dir=resumed
        )
        assert loop.decision_count == made
        asyncio.run(loop.run(max_iterations=50))
    assert resumed.count() > made
    assert len(resumed.info()["resumed_at"]) == 1
