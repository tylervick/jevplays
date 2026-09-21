"""Walking, one tile or one map at a time.

The window functions (`first_step`, `step`, `goto`) walk to a tile on the current map using only
what is on screen: PyBoy's collision window covers the visible 20x18 tiles as a 9x10 grid of
blocks with the player at (4, 4). Each iteration runs a breadth-first search over that window
toward the target, takes the first step, and looks again, so the window scrolls with the player
and NPCs that step into the way are handled by the next search. Targets outside the window are
chased by aiming at the window's edge in their direction. Warps (doors, stairs) end the walk when
the map id changes. `Scripts/make-states.py` and the milestone 2 tests use these directly.

`Navigator` builds on the full-map grid from `executor.world` to run a multi-leg plan: each call
to `step()` moves one tile (or crosses one edge/warp), re-reading the map, sprites, and warps
first so NPCs that wander into the way are routed around. Interruptions (a battle, a dialog)
return "interrupted" with the plan intact; the loop hands control to the brain and calls step()
again when the overworld is back.
"""

from collections import deque
from dataclasses import dataclass, field

from jevplays.emulator import ram
from jevplays.executor import world
from jevplays.state.modes import Mode

PLAYER_ROW = 4
PLAYER_COL = 4
ROWS = 9
COLS = 10
DIRECTIONS = {"up": (-1, 0), "down": (1, 0), "left": (0, -1), "right": (0, 1)}

STUCK_STEPS = 6
STUCK_LEGS = 3


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


def step(emu, direction: str, *, hold: int = 8, settle: int = 0) -> bool:
    """Take one tile step. True when the player's tile or map changed.

    The tile coordinate updates as the walk begins, not when it ends, and a direction held past
    the tile boundary starts the next step: an 18-frame hold used to walk two tiles and report
    one, which is how `talk_to` came to face a wall beside the Mart clerk (#20). So the press is
    short, and the result is read only once the walk counter says the player is standing still."""
    before = (emu.mem[ram.wCurMap], emu.mem[ram.wXCoord], emu.mem[ram.wYCoord])
    emu.press(direction, hold=hold, settle=settle)
    for _ in range(12):  # a 16-frame walk, or a warp or scripted stop that takes a little longer
        if emu.mem[ram.wWalkCounter] == 0:
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


@dataclass
class Leg:
    kind: str  # walk | edge | warp | face
    target: tuple[int, int] | None = None
    direction: str | None = None
    dest_map: int | None = None
    face: str | None = None
    label: str = ""


@dataclass
class Navigator:
    legs: list[Leg] = field(default_factory=list)
    index: int = 0
    blocked: set = field(default_factory=set)
    failed_steps: int = 0
    failed_legs: int = 0
    start_map: int | None = None
    """The map the current leg was begun on."""
    plan_map: int | None = None
    """The map the whole plan was built on, for the dashboard and for debugging a stale plan."""

    @property
    def busy(self) -> bool:
        return self.index < len(self.legs)

    @property
    def current(self) -> Leg | None:
        return self.legs[self.index] if self.busy else None

    def plan(self, emu, state, legs: list[Leg]) -> None:
        self.legs, self.index, self.failed_legs = list(legs), 0, 0
        self.plan_map = emu.mem[ram.wCurMap]
        self._begin_leg(emu)

    def _begin_leg(self, emu) -> None:
        self.blocked, self.failed_steps = set(), 0
        self.start_map = emu.mem[ram.wCurMap]

    def describe(self) -> str:
        leg = self.current
        if leg is None:
            return "idle"
        return leg.label or f"{leg.kind} {leg.target or leg.direction or leg.dest_map}"

    def clear(self) -> None:
        self.legs, self.index = [], 0

    def step(self, emu, state) -> str:
        leg = self.current
        if leg is None:
            return "done"
        if state.mode is not Mode.OVERWORLD:
            return "interrupted"
        mem = emu.mem
        here = (mem[ram.wXCoord], mem[ram.wYCoord])
        if leg.kind == "face":
            emu.press(leg.face, hold=4, settle=12)
            return self._advance(emu)
        if mem[ram.wCurMap] != self.start_map:
            landed = self._after_map_change(emu, leg, mem[ram.wCurMap])
            if landed is not None:
                return landed
        grid = world.build_grid(emu)
        blocked = frozenset(world.blocked_by_sprites(state.sprites) | self.blocked)
        target = self._target(leg, grid, here, mem, blocked)
        if target is None:
            return self._fail_leg(emu)
        if here == target:
            if leg.kind == "walk":
                return self._advance(emu)
            direction = (
                world.EDGE_DIRECTION[leg.direction] if leg.kind == "edge" else self._off_edge(target, grid)
            )
            if direction is None:  # a warp tile inside the map: standing on it should have warped already
                return self._fail_leg(emu)
            # The long hold is deliberate here, unlike the short press every other step uses
            # (#20): off the edge of a map the second step is what carries the player into the
            # connected map, and on a warp tile the map changes on the first step, so the extra
            # one lands harmlessly on the other side.
            step(emu, direction, hold=24, settle=40)
            emu.tick(60)
            if mem[ram.wCurMap] != self.start_map:
                landed = self._after_map_change(emu, leg, mem[ram.wCurMap])
                if landed is not None:
                    return landed
            return self._fail_step(emu, state, None)
        path = world.astar(grid, here, target, blocked)
        if not path:
            if grid.walkable(*target) and target in world.blocked_by_sprites(state.sprites):
                # A sprite is standing on the goal tile, not an unreachable target: wait it out
                # like any other blocked step instead of charging a whole leg failure.
                return self._wait_for_sprite(emu, state)
            return self._fail_leg(emu)
        nxt = path[0]
        if step(emu, world.direction_to(here, nxt)):
            self.blocked.clear()
            self.failed_steps = 0
            if mem[ram.wCurMap] != self.start_map:
                landed = self._after_map_change(emu, leg, mem[ram.wCurMap])
                if landed is not None:
                    return landed
            from jevplays.state.snapshot import snapshot as _snapshot

            if _snapshot(emu).mode is not Mode.OVERWORLD:
                return "interrupted"
            if leg.kind == "walk" and (mem[ram.wXCoord], mem[ram.wYCoord]) == target:
                return self._advance(emu)
            return "moving"
        return self._fail_step(emu, state, nxt)

    def _after_map_change(self, emu, leg, current: int) -> str | None:
        """The map changed while this leg was running. For an edge or a warp leg that is how the
        leg finishes -- as long as we landed where the leg was aiming. A walk leg never changes
        the map on purpose, and a warp that came out somewhere other than its `dest_map` is a
        blackout or a scripted teleport, not an arrival: both leave the rest of the plan pointing
        at a map we are no longer on, so the answer is "lost" and the caller re-plans."""
        if leg.kind == "walk" or self._wrong_map(leg, current):
            return "lost"
        if leg.kind in ("edge", "warp"):
            emu.tick(60)
            return self._advance(emu)
        return None

    @staticmethod
    def _wrong_map(leg: Leg, current: int) -> bool:
        # WARP_LAST_MAP means "back the way you came in", whose id the leg cannot know, and an
        # edge leg built from the map graph only names a direction. Neither can be checked.
        if leg.dest_map is None or leg.dest_map == ram.WARP_LAST_MAP:
            return False
        return current != leg.dest_map

    def _target(self, leg, grid, here, mem, blocked):
        if leg.kind == "walk":
            return leg.target
        if leg.kind == "edge":
            return world.reachable_edge(grid, here, leg.direction, blocked)
        if leg.kind == "warp":
            candidates = world.walkable_warps(grid, world.read_warps(mem), leg.dest_map)
            if not candidates:
                return None
            nearest = min(candidates, key=lambda w: abs(w.x - here[0]) + abs(w.y - here[1]))
            return (nearest.x, nearest.y)
        return None

    @staticmethod
    def _off_edge(cell, grid):
        x, y = cell
        if y == 0:
            return "up"
        if y == grid.height - 1:
            return "down"
        if x == 0:
            return "left"
        if x == grid.width - 1:
            return "right"
        return None

    def _fail_step(self, emu, state, cell) -> str:
        # Something stopped the step. If a battle or dialog began, hand off and keep the plan.
        emu.tick(30)
        from jevplays.state.snapshot import snapshot as _snapshot

        if _snapshot(emu).mode is not Mode.OVERWORLD:
            return "interrupted"
        if cell is not None:
            self.blocked.add(cell)
        self.failed_steps += 1
        if self.failed_steps >= STUCK_STEPS:
            return self._fail_leg(emu)
        return "moving"

    def _wait_for_sprite(self, emu, state) -> str:
        # An NPC is standing on the goal tile. Give it the same patient wait as a blocked step,
        # but never mark the target blocked -- it is still walkable once the sprite moves on.
        emu.tick(30)
        from jevplays.state.snapshot import snapshot as _snapshot

        if _snapshot(emu).mode is not Mode.OVERWORLD:
            return "interrupted"
        self.failed_steps += 1
        if self.failed_steps > STUCK_STEPS:
            return self._fail_leg(emu)
        return "moving"

    def _fail_leg(self, emu) -> str:
        self.failed_legs += 1
        if self.failed_legs >= STUCK_LEGS:
            self.clear()
            return "stuck"
        self._begin_leg(emu)
        return "moving"

    def _advance(self, emu) -> str:
        self.index += 1
        if self.busy:
            self._begin_leg(emu)
            return "leg_done"
        return "done"


def goto_far(emu, x: int, y: int, max_steps: int = 400) -> bool:
    """For scripts: walk to (x, y) on the current map with the full-map navigator."""
    from jevplays.state.snapshot import snapshot as _snapshot

    nav = Navigator()
    nav.plan(emu, _snapshot(emu), [Leg(kind="walk", target=(x, y))])
    for _ in range(max_steps):
        r = nav.step(emu, _snapshot(emu))
        if r == "done":
            return True
        if r in ("stuck", "interrupted", "lost"):
            return False
    return False
