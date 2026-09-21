"""The current map as code sees it: walkability, warps, connections, sprites, and A*.

Everything is read from the running game. wOverworldMap holds the map's block ids; the tileset's
block table and collision list live in ROM and are read through Emulator.rom. One grid cell is one
player step (a 2x2-tile quadrant), and the quadrant's bottom-left tile decides walkability, the
same rule PyBoy applies to the visible window (verified to agree on every cell of every map probed).
"""

import heapq
from collections import deque
from dataclasses import dataclass

from jevplays.emulator import ram
from jevplays.state.snapshot import Sprite

DIRECTIONS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
EDGE_DIRECTION = {"north": "up", "south": "down", "west": "left", "east": "right"}

BLOCKED, WALKABLE, GRASS = 0, 1, 2
"""What a grid cell holds. Grass is walkable like any other cell -- the distinction is only that
stepping onto it can start a wild battle, which is what `train_nearby` and `train_to_level_12`
are after."""


@dataclass(frozen=True)
class Warp:
    x: int
    y: int
    warp_id: int
    dest: int


class MapGrid:
    def __init__(self, cells: list[list[int]]) -> None:
        self.cells = cells
        self.height = len(cells)
        self.width = len(cells[0]) if cells else 0

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def walkable(self, x: int, y: int) -> bool:
        return self.in_bounds(x, y) and self.cells[y][x] != BLOCKED

    def is_grass(self, x: int, y: int) -> bool:
        return self.in_bounds(x, y) and self.cells[y][x] == GRASS

    def grass(self) -> frozenset[tuple[int, int]]:
        """Every tall-grass cell on the map, as (x, y)."""
        return frozenset(
            (x, y) for y, row in enumerate(self.cells) for x, cell in enumerate(row) if cell == GRASS
        )


def read_warps(mem: ram.Memory) -> tuple[Warp, ...]:
    out = []
    for i in range(mem[ram.wNumberOfWarps]):
        y, x, warp_id, dest = ram.read_bytes(mem, ram.wWarpEntries + i * ram.WARP_ENTRY_SIZE, 4)
        out.append(Warp(x=x, y=y, warp_id=warp_id, dest=dest))
    return tuple(out)


def read_connections(mem: ram.Memory) -> dict[str, int]:
    flags = mem[ram.wMapConnections]
    return {
        d: mem[ram.CONNECTION_MAP_ADDRESSES[d]]
        for d, bit in ram.CONNECTION_BITS.items()
        if flags & (1 << bit)
    }


def _rom_byte(emu, bank: int, addr: int) -> int:
    """Read a ROM byte the way the hardware would: addresses below 0x4000 are always the fixed
    home bank (bank 0), no matter what the switchable bank register (`bank`) currently holds.
    PyBoy's `memory[bank, addr]` takes `bank` literally even below 0x4000, so callers that pass
    the tileset's own bank for a home-bank pointer (as the collision list often is) get garbage."""
    return emu.rom(0 if addr < 0x4000 else bank, addr)


def build_grid(emu) -> MapGrid:
    mem = emu.mem
    width, height = mem[ram.wCurMapWidth], mem[ram.wCurMapHeight]
    stride = width + 2 * ram.MAP_BORDER_BLOCKS
    bank = mem[ram.wTilesetBank]
    blocks = ram.read_u16le(mem, ram.wTilesetBlocksPtr)
    collision = ram.read_u16le(mem, ram.wTilesetCollisionPtr)
    walkable = set()
    for i in range(0x180):
        tile = _rom_byte(emu, bank, collision + i)
        if tile == ram.COLLISION_END:
            break
        walkable.add(tile)
    grass = mem[ram.wGrassTile]
    if grass != 0xFF:
        walkable.add(grass)
    cells = [[0] * (width * 2) for _ in range(height * 2)]
    for by in range(height):
        for bx in range(width):
            block = mem[
                ram.wOverworldMap + (by + ram.MAP_BORDER_BLOCKS) * stride + (bx + ram.MAP_BORDER_BLOCKS)
            ]
            base = blocks + block * 16
            for qy in range(2):
                for qx in range(2):
                    tile = _rom_byte(
                        emu, bank, base + (qy * 2 + 1) * 4 + qx * 2
                    )  # bottom-left tile of the quadrant
                    if tile == grass and grass != 0xFF:
                        cells[by * 2 + qy][bx * 2 + qx] = GRASS
                    else:
                        cells[by * 2 + qy][bx * 2 + qx] = WALKABLE if tile in walkable else BLOCKED
    return MapGrid(cells)


def blocked_by_sprites(sprites: tuple[Sprite, ...]) -> set[tuple[int, int]]:
    return {(s.x, s.y) for s in sprites}


def direction_to(a: tuple[int, int], b: tuple[int, int]) -> str:
    delta = (b[0] - a[0], b[1] - a[1])
    for name, d in DIRECTIONS.items():
        if d == delta:
            return name
    raise ValueError(f"{a} and {b} are not adjacent")


def astar(
    grid: MapGrid, start: tuple[int, int], goal: tuple[int, int], blocked: frozenset = frozenset()
) -> list[tuple[int, int]] | None:
    if start == goal:
        return []
    if not grid.walkable(*goal) or goal in blocked:
        return None
    frontier = [(0, start)]
    came_from: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    cost = {start: 0}
    while frontier:
        _, current = heapq.heappop(frontier)
        if current == goal:
            path = []
            while current != start:
                path.append(current)
                current = came_from[current]
            return path[::-1]
        for dx, dy in DIRECTIONS.values():
            nxt = (current[0] + dx, current[1] + dy)
            if not grid.walkable(*nxt) or nxt in blocked:
                continue
            new_cost = cost[current] + 1
            if new_cost < cost.get(nxt, 1 << 30):
                cost[nxt] = new_cost
                came_from[nxt] = current
                heapq.heappush(frontier, (new_cost + abs(goal[0] - nxt[0]) + abs(goal[1] - nxt[1]), nxt))
    return None


def reachable_edge(
    grid: MapGrid, start: tuple[int, int], direction: str, blocked: frozenset
) -> tuple[int, int] | None:
    """The nearest walkable cell on the map's edge in `direction` reachable from `start`."""

    def on_edge(c):
        return {
            "north": c[1] == 0,
            "south": c[1] == grid.height - 1,
            "west": c[0] == 0,
            "east": c[0] == grid.width - 1,
        }[direction]

    seen = {start}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        if on_edge(cur):
            return cur
        for dx, dy in DIRECTIONS.values():
            nxt = (cur[0] + dx, cur[1] + dy)
            if grid.walkable(*nxt) and nxt not in blocked and nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return None


def walkable_warps(grid: MapGrid, warps: tuple[Warp, ...], dest: int) -> list[Warp]:
    return [w for w in warps if w.dest == dest and grid.walkable(w.x, w.y)]
