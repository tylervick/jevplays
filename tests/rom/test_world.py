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


def test_town_map_cells_match_the_games_tables(rom, state_path):
    """Read off the ROM (bank 0x1C): the outdoor table and the indoor ranges. Cerulean lies east
    and north of Pewter; Mt. Moon's three floors share a cell between Route 3 and Route 4; the
    Mt. Moon Pokémon Center sits at Route 4's west end, not on Route 4's own cell (#136)."""
    from jevplays.executor.world import town_map_cell

    with Emulator(rom) as emu:
        emu.load(state_path("route1"))
        cells = {m: town_map_cell(emu, m) for m in (0, 1, 2, 3, 13, 14, 15, 54, 59, 60, 61, 65, 68)}
    assert cells[0] == (2, 11) and cells[1] == (2, 8) and cells[2] == (2, 3) and cells[3] == (10, 2)
    assert cells[13] == (2, 6) and cells[14] == (4, 3) and cells[15] == (8, 2)
    assert cells[54] == (2, 3) and cells[65] == (10, 2)
    assert cells[59] == cells[60] == cells[61] == (6, 2)
    assert cells[68] == (5, 2)


def test_mt_moon_b1f_is_several_pockets_and_the_player_is_in_one(rom, state_path):
    """`states/mt_moon_b1f.state` is a probe-run checkpoint on Mt. Moon B1F, copied by hand (not
    written by make-states.py), so this skips without it. The floor is walled-off pockets under
    one map id; the place name says which one (#137)."""
    from jevplays.executor.world import pocket_of, pockets
    from jevplays.state.snapshot import snapshot

    with Emulator(rom) as emu:
        emu.load(state_path("mt_moon_b1f"))
        grid = build_grid(emu)
        state = snapshot(emu)
    found = pockets(grid)
    assert len(found) > 1
    k = pocket_of(grid, *state.tile)
    assert k is not None and state.place == f"map_60_p{k}"
