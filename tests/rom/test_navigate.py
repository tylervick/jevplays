from jevplays.emulator import ram
from jevplays.emulator.pyboy import Emulator
from jevplays.executor.navigate import goto


def test_collision_window_has_the_expected_shape(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("overworld"))
        grid = emu.collision()
        assert len(grid) == 9 and all(len(row) == 10 for row in grid)
        assert all(cell in (0, 1) for row in grid for cell in row)


def test_goto_reaches_the_bedroom_stairs_and_warps_downstairs(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("overworld"))
        assert goto(emu, 7, 1)
        emu.tick(60)
        assert emu.mem[ram.wCurMap] == 37  # REDS_HOUSE_1F
