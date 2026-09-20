"""Walk to a tile on the current map using only what is on screen.

PyBoy's collision window covers the visible 20x18 tiles as a 9x10 grid of blocks with the player
at (4, 4). Each iteration runs a breadth-first search over that window toward the target, takes
the first step, and looks again, so the window scrolls with the player and NPCs that step into
the way are handled by the next search. Targets outside the window are chased by aiming at the
window's edge in their direction. Warps (doors, stairs) end the walk when the map id changes.
"""

from collections import deque

from jevplays.emulator import ram

PLAYER_ROW = 4
PLAYER_COL = 4
ROWS = 9
COLS = 10
DIRECTIONS = {"up": (-1, 0), "down": (1, 0), "left": (0, -1), "right": (0, 1)}


class NavigationError(RuntimeError):
    pass


def first_step(grid: list[list[int]], target: tuple[int, int]) -> str | None:
    """Direction of the first move on a shortest walkable path from the player to `target`."""
    start = (PLAYER_ROW, PLAYER_COL)
    if start == target:
        return None
    came_from: dict[tuple[int, int], tuple[tuple[int, int], str] | None] = {start: None}
    queue = deque([start])
    while queue:
        cell = queue.popleft()
        if cell == target:
            break
        r, c = cell
        for direction, (dr, dc) in DIRECTIONS.items():
            nxt = (r + dr, c + dc)
            if 0 <= nxt[0] < ROWS and 0 <= nxt[1] < COLS and grid[nxt[0]][nxt[1]] and nxt not in came_from:
                came_from[nxt] = (cell, direction)
                queue.append(nxt)
    if target not in came_from:
        return None
    node, direction = target, None
    while came_from[node] is not None:
        node, direction = came_from[node]
    return direction


def step(emu, direction: str, *, hold: int = 18, settle: int = 8) -> bool:
    """Hold a direction for one tile's walk. True when the player's tile or map changed."""
    before = (emu.mem[ram.wCurMap], emu.mem[ram.wXCoord], emu.mem[ram.wYCoord])
    emu.press(direction, hold=hold, settle=settle)
    for _ in range(6):  # a warp or scripted stop can take a few more frames to land
        after = (emu.mem[ram.wCurMap], emu.mem[ram.wXCoord], emu.mem[ram.wYCoord])
        if after != before:
            return True
        emu.tick(4)
    return False


def goto(emu, x: int, y: int, *, max_steps: int = 80) -> bool:
    """Walk to tile (x, y) on the current map. True when reached, or when a warp changed the map."""
    start_map = emu.mem[ram.wCurMap]
    for _ in range(max_steps):
        px, py = emu.mem[ram.wXCoord], emu.mem[ram.wYCoord]
        if (px, py) == (x, y):
            return True
        grid = emu.collision()
        grid[PLAYER_ROW][PLAYER_COL] = 1
        tr = min(max(PLAYER_ROW + (y - py), 0), ROWS - 1)
        tc = min(max(PLAYER_COL + (x - px), 0), COLS - 1)
        direction = first_step(grid, (tr, tc))
        if direction is None:
            # The collision map does not know about door mats and warp tiles; try the direct move.
            dy, dx = y - py, x - px
            direction = "down" if dy > 0 else "up" if dy < 0 else "right" if dx > 0 else "left"
        if not step(emu, direction):
            return False
        if emu.mem[ram.wCurMap] != start_map:
            return True
    return False
