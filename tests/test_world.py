from jevplays.executor.world import (
    Warp,
    astar,
    blocked_by_sprites,
    build_grid,
    direction_to,
    reachable_edge,
    read_connections,
    read_warps,
    walkable_warps,
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
