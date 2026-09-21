import pytest

from jevplays.emulator import ram
from jevplays.emulator.pyboy import Emulator
from jevplays.executor.world import astar, build_grid, read_connections
from jevplays.state.events import flags_set


def test_route1_map_header_and_connections(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("route1"))
        m = emu.mem
        assert (m[ram.wCurMapWidth], m[ram.wCurMapHeight]) == (10, 18)
        assert m[ram.wNumberOfWarps] == 0
        flags = m[ram.wMapConnections]
        assert flags & (1 << ram.CONNECTION_BITS["north"]) and m[ram.CONNECTION_MAP_ADDRESSES["north"]] == 1
        assert flags & (1 << ram.CONNECTION_BITS["south"]) and m[ram.CONNECTION_MAP_ADDRESSES["south"]] == 0
        assert emu.rom(m[ram.wTilesetBank], ram.read_u16le(m, ram.wTilesetBlocksPtr)) is not None


def test_bedroom_warp_table_and_flags(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("overworld"))
        m = emu.mem
        assert m[ram.wNumberOfWarps] == 1
        y, x, _, dest = ram.read_bytes(m, ram.wWarpEntries, 4)
        assert (x, y, dest) == (7, 1, 37)
        assert flags_set(m) == frozenset()


def test_route1_flags(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("route1"))
        assert flags_set(emu.mem) >= {"got_starter", "battled_rival_in_oaks_lab", "oak_appeared_in_pallet"}


@pytest.mark.parametrize(
    "name",
    [
        "overworld",
        "route1",
        "battle_wild",
        "viridian",
        "viridian_center",
        "mart_dex",
        "dex",
        "pallet",
    ],
)
def test_full_map_grid_agrees_with_pyboys_window_everywhere(rom, state_path, name):
    with Emulator(rom) as emu:
        emu.load(state_path(name))
        if emu.mem[ram.wIsInBattle]:
            pytest.skip(f"{name} is mid-battle; there is no overworld window to compare")
        grid = build_grid(emu)
        window = emu.collision()
        x, y = emu.mem[ram.wXCoord], emu.mem[ram.wYCoord]
        for r in range(9):
            for c in range(10):
                gx, gy = x + (c - 4), y + (r - 4)
                if grid.in_bounds(gx, gy):
                    assert window[r][c] == int(grid.walkable(gx, gy)), (name, gx, gy)


def test_route1_has_a_path_from_the_south_entry_to_the_north_exit(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("route1"))
        grid = build_grid(emu)
        assert read_connections(emu.mem) == {"north": 1, "south": 0}
        path = astar(grid, (10, 33), (10, 0))
        assert path is not None and path[-1] == (10, 0)
