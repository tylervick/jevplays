from jevplays.emulator.intro import walk_intro
from jevplays.emulator.pyboy import Emulator
from jevplays.emulator.ram import read_name, wCurMap, wPartyCount, wPlayerName, wRivalName, wXCoord, wYCoord


def test_walk_intro_reaches_reds_bedroom(rom):
    with Emulator(rom) as emu:
        steps = walk_intro(emu)
        assert 0 < steps < 600
        assert emu.mem[wCurMap] == 38  # REDS_HOUSE_2F
        assert (emu.mem[wXCoord], emu.mem[wYCoord]) == (3, 7)  # one step below the start tile
        assert emu.mem[wPartyCount] == 0
        assert read_name(emu.mem, wPlayerName) == "RED"
        assert read_name(emu.mem, wRivalName) == "BLUE"
