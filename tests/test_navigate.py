from jevplays.emulator import ram
from jevplays.executor.navigate import PLAYER_COL, PLAYER_ROW, first_step, goto
from tests.support import FakeEmulator

OPEN = [[1] * 10 for _ in range(9)]


def test_first_step_goes_straight_when_nothing_blocks():
    assert first_step(OPEN, (PLAYER_ROW - 2, PLAYER_COL)) == "up"
    assert first_step(OPEN, (PLAYER_ROW, PLAYER_COL + 3)) == "right"


def test_first_step_routes_around_a_wall():
    grid = [row[:] for row in OPEN]
    grid[PLAYER_ROW - 1][PLAYER_COL] = 0  # wall directly above
    assert first_step(grid, (PLAYER_ROW - 2, PLAYER_COL)) in ("left", "right")


def test_first_step_is_none_when_unreachable():
    grid = [row[:] for row in OPEN]
    for c in range(10):
        grid[PLAYER_ROW - 1][c] = 0
    assert first_step(grid, (PLAYER_ROW - 2, PLAYER_COL)) is None


def test_goto_walks_the_fake_to_the_target():
    emu = FakeEmulator()
    emu.mem[ram.wXCoord] = 3
    emu.mem[ram.wYCoord] = 7
    assert goto(emu, 5, 5)
    assert (emu.mem[ram.wXCoord], emu.mem[ram.wYCoord]) == (5, 5)
    assert emu.presses.count("right") == 2 and emu.presses.count("up") == 2


def test_goto_gives_up_when_blocked():
    emu = FakeEmulator()
    emu.mem[ram.wXCoord] = 3
    emu.mem[ram.wYCoord] = 7
    emu.step_effects = {}  # presses never move the player
    assert not goto(emu, 3, 5, max_steps=5)
