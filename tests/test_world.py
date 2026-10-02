from jevplays.emulator import ram
from jevplays.executor.world import (
    WALKABLE,
    MapGrid,
    Warp,
    astar,
    blocked_by_sprites,
    build_grid,
    direction_to,
    reachable_edge,
    read_connections,
    read_warps,
    tile_pairs,
    walkable_warps,
    warp_target,
)
from jevplays.state.snapshot import Sprite
from tests.support import FakeEmulator, install_map

ROWS = [
    "......",
    "......",
    "..##..",
    "..##..",
    "......",
    "......",
]


def test_build_grid_reproduces_the_rows():
    emu = FakeEmulator()
    install_map(emu, ROWS)
    grid = build_grid(emu)
    assert (grid.width, grid.height) == (6, 6)
    assert [["." if grid.walkable(x, y) else "#" for x in range(6)] for y in range(6)] == [
        list(r) for r in ROWS
    ]


def test_astar_routes_around_walls_and_returns_none_when_boxed_in():
    emu = FakeEmulator()
    install_map(emu, ROWS)
    grid = build_grid(emu)
    path = astar(grid, (0, 0), (5, 5))
    assert path[-1] == (5, 5) and len(path) == 10
    assert astar(grid, (0, 0), (2, 2)) is None  # a wall
    assert astar(grid, (0, 0), (5, 5), blocked=frozenset({(0, 1), (1, 0)})) is None


def test_sprites_block_cells_and_reachable_edge_finds_the_nearest_exit():
    emu = FakeEmulator()
    install_map(emu, ROWS)
    grid = build_grid(emu)
    blocked = blocked_by_sprites((Sprite(1, 61, 0, 1),))
    assert blocked == {(0, 1)}
    assert reachable_edge(grid, (3, 4), "north", frozenset()) == (4, 0)
    assert reachable_edge(grid, (0, 0), "north", frozenset()) == (0, 0)


def test_warps_connections_and_walkable_warps():
    emu = FakeEmulator()
    install_map(emu, ROWS, warps=[(2, 2, 0, 40), (3, 0, 1, 40)], connections={"north": 12, "south": 0})
    grid = build_grid(emu)
    warps = read_warps(emu.mem)
    assert warps == (Warp(2, 2, 0, 40), Warp(3, 0, 1, 40))
    assert walkable_warps(grid, warps, 40) == [Warp(3, 0, 1, 40)]
    assert read_connections(emu.mem) == {"north": 12, "south": 0}


def test_direction_to():
    assert direction_to((1, 1), (1, 0)) == "up" and direction_to((1, 1), (2, 1)) == "right"


def test_build_grid_reads_a_home_bank_collision_list_through_bank_zero():
    emu = FakeEmulator()
    install_map(emu, ROWS, tileset=(25, 0x4000, 0x1749))  # the bedroom's real collision pointer is 0x1749
    grid = build_grid(emu)
    assert [["." if grid.walkable(x, y) else "#" for x in range(6)] for y in range(6)] == [
        list(r) for r in ROWS
    ]
    # and reading it through the tileset bank would have found nothing walkable
    emu.mem.rom[(25, 0x1749)] = 0xFF
    assert build_grid(emu).walkable(0, 0)


GRASS_ROWS = [
    "..~~..",
    "..~~..",
    "......",
    "..##..",
    "......",
    "......",
]


def test_grass_cells_are_marked_and_are_still_walkable():
    emu = FakeEmulator()
    install_map(emu, GRASS_ROWS)
    grid = build_grid(emu)
    assert grid.grass() == frozenset({(2, 0), (3, 0), (2, 1), (3, 1)})
    assert grid.is_grass(2, 0) and grid.is_grass(3, 1)
    assert not grid.is_grass(0, 0) and not grid.is_grass(2, 3)  # road, and a wall
    assert grid.walkable(2, 0) and grid.walkable(0, 0) and not grid.walkable(2, 3)
    assert astar(grid, (0, 0), (2, 0)) == [(1, 0), (2, 0)]  # grass is routed through like any cell


def test_a_map_without_grass_has_no_grass_cells():
    emu = FakeEmulator()
    install_map(emu, ROWS)
    assert build_grid(emu).grass() == frozenset()


def _grass_block_with(emu, tiles: dict[int, int]) -> None:
    """Overwrite tiles of install_map's grass block (block 2) by index within the 4x4 block."""
    bank, blocks = emu.mem[ram.wTilesetBank], ram.read_u16le(emu.mem, ram.wTilesetBlocksPtr)
    for i, tile in tiles.items():
        emu.mem.rom[(bank, blocks + 32 + i)] = tile


def _bottom(qx: int, qy: int, right: bool) -> int:
    return (qy * 2 + 1) * 4 + qx * 2 + (1 if right else 0)


def test_a_cell_is_grass_only_when_its_bottom_right_tile_is():
    """The wild-encounter check reads the bottom-right tile of the player's cell; a cell whose
    bottom-left tile is grass and bottom-right is not can never start a battle (#100)."""
    emu = FakeEmulator()
    install_map(emu, ["~~", "~~"])
    _grass_block_with(emu, {_bottom(qx, qy, right=True): 1 for qx in range(2) for qy in range(2)})
    grid = build_grid(emu)
    assert grid.grass() == frozenset()
    assert all(grid.walkable(x, y) for x in range(2) for y in range(2))


def test_a_cell_whose_bottom_right_tile_is_grass_is_grass():
    emu = FakeEmulator()
    install_map(emu, ["..", ".."])
    bank, blocks = emu.mem[ram.wTilesetBank], ram.read_u16le(emu.mem, ram.wTilesetBlocksPtr)
    for qx in range(2):
        for qy in range(2):
            emu.mem.rom[(bank, blocks + _bottom(qx, qy, right=True))] = emu.mem[ram.wGrassTile]
    assert build_grid(emu).grass() == frozenset({(0, 0), (1, 0), (0, 1), (1, 1)})


VIRIDIAN_SHELF = [0xFE, 4, 0x04, 0x0B, 0x0F, 0x0C, 0xFF]
"""The Viridian Mart's inventory as the ROM stores it: `script_mart`'s 0xFE, a count, item ids."""


def _shelf(emu, addr, data):
    for i, b in enumerate(data):
        emu.mem.rom[(0, addr + i)] = b


def test_a_marts_inventory_is_read_from_the_rom_in_the_games_item_names():
    from jevplays.executor.world import mart_inventory

    emu = FakeEmulator()
    _shelf(emu, ram.MART_INVENTORIES[42], VIRIDIAN_SHELF)
    assert mart_inventory(emu, 42) == ("POKE BALL", "ANTIDOTE", "PARLYZ HEAL", "BURN HEAL")


def test_a_map_with_no_known_inventory_or_a_malformed_one_has_none():
    from jevplays.executor.world import mart_inventory

    emu = FakeEmulator()
    assert mart_inventory(emu, 1) is None  # not a Mart
    assert mart_inventory(emu, 42) is None  # zeros where the table should be
    _shelf(emu, ram.MART_INVENTORIES[42], [0xFE, 4, 0x04, 0x0B, 0x0F, 0x0C, 0x00])  # no 0xFF end
    assert mart_inventory(emu, 42) is None


def test_warp_target_prefers_the_shortest_walk_then_underfoot_then_the_nearest():
    emu = FakeEmulator()
    install_map(emu, ROWS)
    grid = build_grid(emu)
    walled = Warp(3, 4, 0, 9)  # 3 tiles from (5,5) as the crow flies, boxed in below
    boxed = frozenset({(2, 4), (4, 4), (3, 5)})  # and (3,3) is wall
    far = Warp(5, 0, 0, 9)
    underfoot = Warp(5, 5, 0, 9)
    assert warp_target(grid, (5, 5), (walled, far), 9, boxed) == (5, 0)
    assert warp_target(grid, (5, 5), (walled, underfoot), 9, boxed) == (5, 5)
    assert warp_target(grid, (5, 5), (walled,), 9, boxed) == (3, 4)  # nothing walkable: as before
    assert warp_target(grid, (5, 5), (walled,), 8, boxed) is None


def test_a_door_mat_underfoot_on_the_maps_edge_is_taken_where_it_is():
    """The Viridian Mart's mat is two warp tiles on the bottom edge; aiming at the other one, a
    step away, walked the player back and forth between them (a ROM test caught it)."""
    emu = FakeEmulator()
    install_map(emu, ROWS)
    grid = build_grid(emu)
    mat = (Warp(3, 5, 0, 9), Warp(4, 5, 0, 9))
    assert warp_target(grid, (4, 5), mat, 9, frozenset()) == (4, 5)


CAVE = [[0x20, 0x20, 0x05], [0x20, 0x20, 0x05], [0x20, 0x20, 0x20]]
"""Mt. Moon in miniature: a raised floor (0x05) down the east side, the lower floor (0x20) elsewhere,
walkable both."""


def cave(pairs=frozenset({frozenset((0x20, 0x05))})):
    return MapGrid([[WALKABLE] * 3 for _ in range(3)], CAVE, pairs)


def test_a_step_across_a_refused_tile_pair_is_not_taken():
    grid = cave()
    assert grid.can_step((1, 0), (0, 0)) and not grid.can_step((1, 0), (2, 0))
    assert grid.can_step((2, 0), (2, 1))  # along the raised floor is fine
    assert astar(grid, (0, 0), (2, 0)) is None  # no way up from here
    assert astar(cave(frozenset()), (0, 0), (2, 0)) == [(1, 0), (2, 0)]


def test_reachable_edge_respects_tile_pairs():
    assert reachable_edge(cave(), (0, 0), "east", frozenset()) == (2, 2)  # around, on the lower floor
    assert reachable_edge(cave(frozenset()), (0, 0), "east", frozenset()) == (2, 0)


def test_tile_pairs_are_read_for_the_current_tileset_from_the_games_table():
    emu = FakeEmulator()
    table = [0x11, 0x20, 0x05, 0x03, 0x30, 0x2E, 0x11, 0x05, 0x21, ram.COLLISION_END]
    for i, byte in enumerate(table):
        emu.mem.rom[(0, ram.TILE_PAIR_COLLISIONS_LAND + i)] = byte
    assert tile_pairs(emu, 0x11) == {frozenset((0x20, 0x05)), frozenset((0x05, 0x21))}
    assert tile_pairs(emu, 0x03) == {frozenset((0x30, 0x2E))}
    assert tile_pairs(emu, 0x00) == frozenset()


def test_build_grid_carries_the_tilesets_pairs():
    emu = FakeEmulator()
    install_map(emu, ROWS)
    emu.mem[ram.wCurMapTileset] = 0x11
    for i, byte in enumerate([0x11, 0x01, 0x02, ram.COLLISION_END]):
        emu.mem.rom[(0, ram.TILE_PAIR_COLLISIONS_LAND + i)] = byte
    assert build_grid(emu).pairs == {frozenset((0x01, 0x02))}


def test_town_map_cells_come_from_the_outdoor_table_and_the_indoor_ranges():
    """Pallet Town is entry 0 of the outdoor table; Red's house is in the first indoor range,
    which ends at 41 (exclusive); Mt. Moon's floors share one range (#136)."""
    from jevplays.executor.world import town_map_cell
    from tests.support import install_town_map

    emu = FakeEmulator()
    install_town_map(emu, {0: (2, 11), 2: (2, 3), 3: (10, 2), 37: (2, 11), 54: (2, 3), 60: (6, 2)})
    assert town_map_cell(emu, 0) == (2, 11)
    assert town_map_cell(emu, 3) == (10, 2)
    assert town_map_cell(emu, 37) == (2, 11)
    assert town_map_cell(emu, 54) == (2, 3)
    assert town_map_cell(emu, 60) == (6, 2)


def test_an_indoor_range_covers_every_map_up_to_its_end():
    """The game compares the map id against each range's end and takes the first range it is
    below, so one entry ending at 62 covers 59, 60 and 61 -- all three Mt. Moon floors."""
    from jevplays.emulator import ram as r
    from jevplays.executor.world import town_map_cell

    emu = FakeEmulator()
    rom = emu.mem.rom
    rom[(r.TOWN_MAP_BANK, r.TOWN_MAP_INDOOR)] = 59
    rom[(r.TOWN_MAP_BANK, r.TOWN_MAP_INDOOR + 1)] = (3 << 4) | 2
    rom[(r.TOWN_MAP_BANK, r.TOWN_MAP_INDOOR + 4)] = 62
    rom[(r.TOWN_MAP_BANK, r.TOWN_MAP_INDOOR + 5)] = (2 << 4) | 6
    rom[(r.TOWN_MAP_BANK, r.TOWN_MAP_INDOOR + 8)] = 0xFF
    assert [town_map_cell(emu, m) for m in (58, 59, 60, 61)] == [(2, 3), (6, 2), (6, 2), (6, 2)]


def test_pockets_are_the_walkable_components_in_top_left_order():
    """Mt. Moon B1F is several walled-off pockets under one map id (#129, #137). Ids are the rank
    of each pocket's top-left cell, so a pocket keeps its id across visits and across runs."""
    from jevplays.executor.world import pocket_of, pockets

    emu = FakeEmulator()
    install_map(emu, ["..##..", "..##..", "..##..", "..##..", "######", "######", "..##..", "..##.."])
    grid = build_grid(emu)
    assert [min((y, x) for x, y in p) for p in pockets(grid)] == [(0, 0), (0, 4), (6, 0), (6, 4)]
    assert pocket_of(grid, 1, 1) == 0 and pocket_of(grid, 5, 3) == 1
    assert pocket_of(grid, 0, 7) == 2 and pocket_of(grid, 5, 7) == 3


def test_a_tile_pair_splits_a_pocket():
    """Mt. Moon's raised floor against its lower floor: both walkable, no step between (#126)."""
    from jevplays.executor.world import pockets

    emu = FakeEmulator()
    install_map(emu, ["....", "....", "....", "...."])
    grid = build_grid(emu)
    assert len(pockets(grid)) == 1
    grid.tiles = [[1 if x < 2 else 2 for x in range(4)] for _ in range(4)]
    grid.pairs = frozenset({frozenset((1, 2))})
    assert [min((y, x) for x, y in p) for p in pockets(grid)] == [(0, 0), (0, 2)]


def test_a_cell_the_grid_calls_a_wall_takes_its_neighbours_pocket():
    """A door mat or a ladder tile is often a wall to the grid; the player stands on it all the
    same, and the place must not change name because of it."""
    from jevplays.executor.world import pocket_of

    emu = FakeEmulator()
    install_map(emu, ["..##..", "..##..", "..##..", "..##..", "..##..", "..##.."])
    grid = build_grid(emu)
    assert pocket_of(grid, 2, 2) == 0  # wall, left neighbour is pocket 0
    assert pocket_of(grid, 3, 2) == 1  # wall, right neighbour is pocket 1
    grid.cells = [[0] * 6 for _ in range(6)]
    assert pocket_of(grid, 2, 2) is None
