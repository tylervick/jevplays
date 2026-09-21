"""The Boulder Badge is granted one dialog after Brock falls (#40).

`beat_brock` is set when the battle ends; `wObtainedBadges` bit 0 is set while "RED received
the BOULDERBADGE!" is on screen. `brock_award.state` is saved at the flag (mid-dialog) by
`Scripts/make-states.py --only brock`; a run that finished on the flag would stop right there.
"""

import asyncio

from jevplays.emulator.pyboy import Emulator
from jevplays.executor.goals import active_milestone
from jevplays.loop import Loop, LoopConfig
from jevplays.state.snapshot import snapshot


class Quiet:
    async def publish(self, event: dict) -> None:
        pass


def test_the_run_finishes_on_the_badge_bit_not_on_the_flag(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("brock_award"))
        before = snapshot(emu)
        assert "beat_brock" in before.flags and before.badges == 0
        assert active_milestone(before) is not None, "the flag alone must not end the spine"
        loop = Loop(emu, Quiet(), LoopConfig(paced=False, fps=0.001))

        async def until_finished():
            for _ in range(80):
                if loop.finished:
                    return
                await loop.advance(snapshot(emu))
            state = snapshot(emu)
            if state.badges >= 1:
                await loop.advance(state)  # one more turn notices the badge and finishes

        asyncio.run(until_finished())
        after = snapshot(emu)
        assert after.badges == 1 and loop.finished
