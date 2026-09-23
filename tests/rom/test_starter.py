"""#80: taking the starter Jev chose puts that one in the party, for each of the three balls."""

import pytest

from jevplays.emulator.pyboy import Emulator
from jevplays.loop import Loop, LoopConfig
from jevplays.state.modes import Mode
from jevplays.state.snapshot import snapshot


class Quiet:
    async def publish(self, event):
        pass


def put_the_ball_back(emu):
    """`prompt_starter` stands at the "So! You want CHARMANDER?" box. NO puts it back, so the
    table holds all three again."""
    for _ in range(4):
        state = snapshot(emu)
        if state.mode is Mode.PROMPT:
            emu.press("down", settle=8)
            emu.press("a", settle=40)
        elif state.mode is Mode.OVERWORLD:
            return
        else:
            emu.press("b", settle=30)


@pytest.mark.parametrize("species", ["BULBASAUR", "CHARMANDER", "SQUIRTLE"])
def test_taking_a_starter_puts_that_one_in_the_party(rom, state_path, species):
    with Emulator(rom) as emu:
        emu.load(state_path("prompt_starter"))
        put_the_ball_back(emu)
        assert snapshot(emu).party_count == 0
        loop = Loop(emu, Quiet(), LoopConfig(paced=False))
        assert loop._take_starter(species) is True
        state = snapshot(emu)
        assert state.party_count == 1 and state.party[0].name == species
        assert "got_starter" in state.flags
