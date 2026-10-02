# Pocket Places Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A place in the run's walked graph is (map, pocket), so a heal trip from inside Mt. Moon can only be planned from a pocket that has actually left, and a cave ladder can read "visited, leads nowhere new" when everything beyond it has been seen.

**Architecture:** `world.pocket_of` names the connected component of the walkable grid the player stands in; `snapshot` puts the resulting place name on `GameState.place`; `Memory` keys what was offered (`exits`) and where each way out landed (`landings`) by place, and answers `leads_nowhere_new` with a bounded search over indoor places. Everything that used `maps.node_of(map_id, x, y)` for "where are we" reads `state.place` instead, so routes run over pocket names without `maps.route` changing.

**Tech Stack:** Python 3.14, dataclasses, pytest (`mise exec -- uv run pytest`), the fake emulator in `tests/support.py`, PyBoy only under `tests/rom/`.

**Spec:** `docs/superpowers/specs/2026-10-02-pocket-places-design.md`

## Global Constraints

- Jev judges, code executes: nothing new reaches Jev except the reworded gloss of "leads nowhere new"; no coordinates, pocket ids or counts appear in any option text or state field Jev sees.
- `import pyboy` only in `src/jevplays/emulator/pyboy.py`; every unit test runs on `tests.support.FakeEmulator`.
- Never edit a test to make it pass. Tests that encode the old `buildings`/`ladders` model are rewritten to the new model with the same scenario, and the plan names each one.
- A change to the explore question's wording re-records `tests/fixtures/responses/explore_viridian.json` with `mise exec -- uv run Scripts/record-fixtures.py --only explore_viridian` in the same branch.
- Named maps (`maps.NODE_NAMES`) and Route 2 keep their node names; `maps.LINKS` is not touched.
- `memory.json` written before this change must load (`Memory.from_dict`).
- Conventional commits, `feat(executor):` / `feat(state):` / `fix(...)`; run `mise run check` before pushing.
- Work in `.worktrees/pocket-places` on branch `tylervick/pocket-places` (the spec is already committed there; game data copied).

## Review Focus

1. **The player on a tile the grid calls a wall** (a door mat, a ladder tile): `pocket_of` must still name the pocket the tile opens onto, or the same spot gets two names across visits. Task 1 tests a start cell that is not walkable.
2. **A map with no grid at all** (the fake with nothing installed, width 0): the place must be `map_<id>`, never raise. Task 3 tests it.
3. **A pre-change `memory.json`** with `ladders`, `buildings` and map-id `exits`: it must load, old ladders must still read "visited", and the frontier search must not follow them. Task 4 tests it.
4. **A cycle of places** (1F → B1F pocket → B2F pocket → the same B1F pocket): `leads_nowhere_new` must terminate. Task 4 tests a cycle.
5. **A test-built `GameState` with no place** (`tests.support.overworld_state`, `make_state`): `goals.node` must fall back to `maps.node_of`, or every goal and route test silently routes from "". Task 3 tests the fallback.

---

### Task 1: Pockets of a grid

**Files:**
- Modify: `src/jevplays/executor/world.py` (after `MapGrid`, line 73)
- Test: `tests/test_world.py`

**Interfaces:**
- Produces: `world.pockets(grid: MapGrid) -> list[frozenset[tuple[int, int]]]` — the connected components of the walkable cells under `grid.can_step`, sorted by each component's smallest `(y, x)` cell. `world.pocket_of(grid: MapGrid, x: int, y: int) -> int | None` — the index into `pockets(grid)` of the component containing `(x, y)`; for a cell that is not walkable, the component of its first walkable neighbour (up, down, left, right, in that order); `None` when there is none.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_world.py`:

```python
def test_pockets_are_the_walkable_components_in_top_left_order():
    """Mt. Moon B1F is several walled-off pockets under one map id (#129, #137). Ids are the rank
    of each pocket's top-left cell, so a pocket keeps its id across visits and across runs."""
    from jevplays.executor.world import pocket_of, pockets

    emu = FakeEmulator()
    install_map(emu, ["..##..", "..##..", "..##..", "..##..", "######", "..##.."])
    grid = build_grid(emu)
    assert [min((y, x) for x, y in p) for p in pockets(grid)] == [(0, 0), (0, 4), (5, 0), (5, 4)]
    assert pocket_of(grid, 1, 1) == 0 and pocket_of(grid, 5, 3) == 1
    assert pocket_of(grid, 0, 5) == 2 and pocket_of(grid, 5, 5) == 3


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
```

Note: `install_map` pairs 2x2 characters into one block, so the 6x6 fixtures above describe a 6x6 grid where columns 2 and 3 are a wall; `BLOCKED` is `0` in `world.py` (check `grep -n "^BLOCKED" src/jevplays/executor/world.py` and use that constant if it differs).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `mise exec -- uv run pytest tests/test_world.py -q -k "pocket"`
Expected: FAIL with `ImportError: cannot import name 'pockets'`

- [ ] **Step 3: Implement**

Add to `src/jevplays/executor/world.py` after the `MapGrid` class:

```python
def pockets(grid: MapGrid) -> list[frozenset[tuple[int, int]]]:
    """The walled-off parts of a map: the connected components of its walkable cells under
    `can_step`, in order of each one's top-left cell, so a pocket's index is the same on every
    visit and in every run. A cave floor is several of these under one map id (#137)."""
    seen: set[tuple[int, int]] = set()
    found: list[frozenset[tuple[int, int]]] = []
    for y in range(grid.height):
        for x in range(grid.width):
            if (x, y) in seen or not grid.walkable(x, y):
                continue
            component = _flood(grid, (x, y))
            seen |= component
            found.append(frozenset(component))
    return sorted(found, key=lambda p: min((cy, cx) for cx, cy in p))


def _flood(grid: MapGrid, start: tuple[int, int]) -> set[tuple[int, int]]:
    component = {start}
    queue = deque([start])
    while queue:
        cx, cy = queue.popleft()
        for nx, ny in ((cx, cy - 1), (cx, cy + 1), (cx - 1, cy), (cx + 1, cy)):
            if (nx, ny) not in component and grid.can_step((cx, cy), (nx, ny)):
                component.add((nx, ny))
                queue.append((nx, ny))
    return component


def pocket_of(grid: MapGrid, x: int, y: int) -> int | None:
    """Which of `pockets(grid)` holds `(x, y)`. A door mat or a ladder tile is often a wall to the
    grid while the player stands on it; such a cell takes the pocket of its first walkable
    neighbour (up, down, left, right). None when there is no pocket to take."""
    cells = [(x, y)] if grid.walkable(x, y) else [(x, y - 1), (x, y + 1), (x - 1, y), (x + 1, y)]
    for cell in cells:
        if grid.walkable(*cell):
            for i, pocket in enumerate(pockets(grid)):
                if cell in pocket:
                    return i
    return None
```

`deque` is already imported at the top of `world.py` (`from collections import deque`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `mise exec -- uv run pytest tests/test_world.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/executor/world.py tests/test_world.py
git commit -m "feat(executor): the walled-off pockets of a map's grid, in a stable order (#137)"
```

---

### Task 2: Place names

**Files:**
- Modify: `src/jevplays/executor/maps.py:55-70` (`map_id_of`, after `node_of`)
- Test: `tests/test_maps.py`

**Interfaces:**
- Produces: `maps.place_name(map_id: int, x: int, y: int, pocket: int | None, pocket_count: int) -> str` — `node_of(map_id, x, y)` for a map in `NODE_NAMES` or Route 2; otherwise `map_<id>` when `pocket_count <= 1` or `pocket is None`, else `map_<id>_p<pocket>`. `maps.map_id_of` additionally parses `map_<id>_p<k>`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_maps.py`:

```python
def test_place_name_suffixes_the_pocket_only_for_an_unnamed_map_with_several():
    """A cave floor is several places under one id (#137); a town or a building is one place
    whatever its grid says, so LINKS and the Route 2 split are untouched."""
    assert maps.place_name(60, 5, 5, 2, 4) == "map_60_p2"
    assert maps.place_name(60, 5, 5, 0, 1) == "map_60"
    assert maps.place_name(60, 5, 5, None, 4) == "map_60"
    assert maps.place_name(maps.PEWTER_CITY, 5, 5, 1, 3) == "pewter_city"
    assert maps.place_name(ROUTE_2, 8, 71, 1, 3) == "route_2_south"


def test_map_id_of_reads_a_pocket_suffix():
    assert maps.map_id_of("map_60_p2") == 60
    assert maps.map_id_of("map_60_px") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `mise exec -- uv run pytest tests/test_maps.py -q -k "place_name or pocket_suffix"`
Expected: FAIL with `AttributeError: module 'jevplays.executor.maps' has no attribute 'place_name'`

- [ ] **Step 3: Implement**

In `src/jevplays/executor/maps.py`, replace `map_id_of` and add `place_name` after `node_of`:

```python
def map_id_of(node: str) -> int | None:
    """The map id a node name stands for, or None for a name that is neither.

    The inverse of `node_of` and `place_name`: `map_<id>` for a map with no name of its own (#35)
    and `map_<id>_p<k>` for one pocket of it (#137). An edge leg built for such a node still
    carries a `dest_map`, so a blackout mid-walk reads as `lost` rather than as the crossing the
    leg was waiting for."""
    if node in MAP_IDS:
        return MAP_IDS[node]
    if not node.startswith("map_"):
        return None
    rest = node[4:]
    map_part, _, pocket_part = rest.partition("_p")
    if not map_part.isdigit() or (pocket_part and not pocket_part.isdigit()):
        return None
    return int(map_part)


def place_name(map_id: int, x: int, y: int, pocket: int | None, pocket_count: int) -> str:
    """The place the player is standing in. A named map is one place whatever its grid says, so
    `LINKS`, Route 2's split and `CENTERS` stand; a map past the table is one place per walled-off
    pocket when it has several (#137). With no pocket to name (the player on a tile the grid cannot
    place) the map-level name is used, as before."""
    if map_id in NODE_NAMES or map_id == ROUTE_2:
        return node_of(map_id, x, y)
    if pocket is None or pocket_count <= 1:
        return f"map_{map_id}"
    return f"map_{map_id}_p{pocket}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `mise exec -- uv run pytest tests/test_maps.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/executor/maps.py tests/test_maps.py
git commit -m "feat(executor): a place name per pocket for maps past the table (#137)"
```

---

### Task 3: The place on the snapshot

**Files:**
- Modify: `src/jevplays/state/snapshot.py:94-100` (add the field), `:254-304` (`snapshot`)
- Modify: `src/jevplays/executor/goals.py:56-58` (`node`)
- Test: `tests/test_snapshot.py`, `tests/test_goals.py`

**Interfaces:**
- Consumes: `world.pockets`, `world.pocket_of` (Task 1); `maps.place_name` (Task 2).
- Produces: `GameState.place: str` (default `""`), set by `snapshot`. `goals.node(state)` returns `state.place` when set, else `maps.node_of(state.map_id, *state.tile)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_snapshot.py`:

```python
def test_the_snapshot_names_the_place_by_pocket_for_a_map_past_the_table():
    """Two pockets under one id; the player in the right-hand one (#137)."""
    from tests.support import install_map

    emu = FakeEmulator()
    install_map(emu, ["..##..", "..##..", "..##..", "..##..", "..##..", "..##.."])
    emu.mem[ram.wCurMap] = 60
    emu.mem[ram.wXCoord], emu.mem[ram.wYCoord] = 5, 2
    assert snapshot(emu).place == "map_60_p1"
    emu.mem[ram.wXCoord] = 1
    assert snapshot(emu).place == "map_60_p0"


def test_a_named_map_is_one_place_and_a_map_with_no_grid_keeps_its_plain_name():
    from tests.support import install_map

    emu = FakeEmulator()
    install_map(emu, ["..##..", "..##..", "..##..", "..##..", "..##..", "..##.."])
    emu.mem[ram.wCurMap] = 2  # Pewter City, named
    emu.mem[ram.wXCoord], emu.mem[ram.wYCoord] = 5, 2
    assert snapshot(emu).place == "pewter_city"
    bare = FakeEmulator()  # nothing installed: a map of width 0
    bare.mem[ram.wCurMap] = 200
    assert snapshot(bare).place == "map_200"
```

Append to `tests/test_goals.py`:

```python
def test_node_falls_back_to_the_map_level_name_for_a_state_with_no_place():
    """Test-built states carry no place; the goal tables must still route from them."""
    from dataclasses import replace

    from jevplays.executor.goals import node
    from tests.support import overworld_state

    state = overworld_state(map_id=1)
    assert state.place == "" and node(state) == "viridian_city"
    assert node(replace(state, place="map_60_p2")) == "map_60_p2"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `mise exec -- uv run pytest tests/test_snapshot.py tests/test_goals.py -q -k "place"`
Expected: FAIL with `AttributeError: 'GameState' object has no attribute 'place'`

- [ ] **Step 3: Implement**

In `src/jevplays/state/snapshot.py`, add after the `disabled_move` field (line 99):

```python
    place: str = ""
    """Where we stand in the run's walked graph: `maps.node_of` for a named map, one name per
    walled-off pocket for a map past the table (`maps.place_name`, #137). Empty on a state built
    by hand; `goals.node` falls back to the map-level name then."""
```

In `snapshot()`, before `return GameState(`:

```python
    tile = (mem[ram.wXCoord], mem[ram.wYCoord])
    place = _place(emu, map_id, tile)
```

and pass `tile=tile,` and `place=place,` in the constructor (replace the existing `tile=(mem[ram.wXCoord], mem[ram.wYCoord]),` line). Add the helper after `snapshot`:

```python
def _place(emu: EmulatorLike, map_id: int, tile: tuple[int, int]) -> str:
    """Build the grid only for a map that can have pockets: a named map is one place."""
    from jevplays.executor import maps, world

    if map_id in maps.NODE_NAMES or map_id == maps.ROUTE_2:
        return maps.node_of(map_id, *tile)
    grid = world.build_grid(emu)
    found = world.pockets(grid)
    return maps.place_name(map_id, *tile, world.pocket_of(grid, *tile), len(found))
```

The import is local because `executor.world` imports `state.snapshot` (for `Sprite`); a module-level import would be circular. Check `EmulatorLike` is the name of the protocol `snapshot` already takes (line 254); use whatever it is.

In `src/jevplays/executor/goals.py`, replace `node`:

```python
def node(state: GameState) -> str:
    """The place the player is standing in: the snapshot's pocket-aware name, or the map-level
    name for a state built without one (#137)."""
    return state.place or maps.node_of(state.map_id, *state.tile)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `mise exec -- uv run pytest tests/test_snapshot.py tests/test_goals.py tests/test_options.py tests/test_loop.py -q`
Expected: all pass (nothing else reads `place` yet).

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/state/snapshot.py src/jevplays/executor/goals.py tests/test_snapshot.py tests/test_goals.py
git commit -m "feat(state): the snapshot names the place, pocket and all (#137)"
```

---

### Task 4: Memory keyed by place: exits, landings, the frontier search

**Files:**
- Modify: `src/jevplays/executor/options.py:70-232` (`Memory`)
- Test: `tests/test_options.py` (rewrite the five tests named below; add new ones)

**Interfaces:**
- Produces, on `Memory`:
  - `Landing = tuple[str, int, int | str | None]` (module-level alias): `("warp", dest_map, warp_id_or_None)` or `("edge", dest_map, direction)`.
  - `exits: dict[str, set[Landing]]` — place → the landings offered there.
  - `landings: dict[Landing, str | None]` — landing → the place it was found to lead to; `None` for a landing taken before places existed.
  - `note_exits(place: str, options: list[Option]) -> None`
  - `note_landing(landing: Landing, place: str | None) -> None`
  - `leads_nowhere_new(here: str, landing: Landing) -> bool`
  - `word(map_id: int, place: str, option: Option) -> str`
  - `option_landing(option: Option) -> Landing | None` (module-level function).
  - Removed: `buildings`, `ladders`, `note_ladder`, `dead_end`.
- Consumes: `maps.map_id_of` (Task 2), `ram.FIRST_INDOOR_MAP`.

- [ ] **Step 1: Rewrite the tests that encode the old model, and add the new ones**

In `tests/test_options.py` replace these five tests in place (same names where the scenario is the same):

```python
def test_a_ladder_is_visited_only_once_this_run_has_used_it():
    emu, state, memory = town(warps=[(7, 7, 0, 60), (0, 7, 2, 60)], connections={})
    memory.note_map(60)
    memory.note_landing(("warp", 60, 0), "map_60_p0")
    words = {o.id: o.memory for o in generate(emu, state, memory, None)}
    assert words["door_60_0"] == "visited" and words["door_60_2"] == "new"
    assert Memory.from_dict(memory.to_dict()) == memory


def test_generate_remembers_what_this_place_offered_as_landings():
    emu, state, memory = town()
    generate(emu, state, memory, None)
    assert memory.exits == {
        state.place or f"map_{state.map_id}": {
            ("edge", 13, "north"),
            ("edge", 12, "east"),
            ("warp", 41, None),
            ("warp", 42, None),
        }
    }
    emu, state, memory = town(warps=[(7, 7, 0, ram.WARP_LAST_MAP)], connections={})
    emu.mem[ram.wLastMap] = 12
    generate(emu, state, memory, None)
    assert memory.exits == {state.place or f"map_{state.map_id}": {("warp", 12, None)}}
    assert Memory.from_dict(memory.to_dict()) == memory


def test_a_visited_building_whose_only_way_out_is_back_here_leads_nowhere_new():
    """The Pewter Pokémon Center ping-pong past Brock: a building is the one-place case."""
    emu, state, memory = town()
    here = state.place or f"map_{state.map_id}"
    memory.note_map(41)
    memory.note_landing(("warp", 41, None), "viridian_pokecenter")
    memory.exits["viridian_pokecenter"] = {("warp", state.map_id, None)}
    memory.note_landing(("warp", state.map_id, None), here)
    words = {o.id: o.memory for o in generate(emu, state, memory, None)}
    assert words["door_41"] == "visited, leads nowhere new"


def test_a_building_with_an_untaken_way_out_is_plain_visited():
    emu, state, memory = town()
    here = state.place or f"map_{state.map_id}"
    memory.note_map(41)
    memory.note_landing(("warp", 41, None), "viridian_pokecenter")
    memory.exits["viridian_pokecenter"] = {("warp", state.map_id, None), ("warp", 50, None)}  # stairs, say
    memory.note_landing(("warp", state.map_id, None), here)
    words = {o.id: o.memory for o in generate(emu, state, memory, None)}
    assert words["door_41"] == "visited"


def test_a_place_never_asked_on_is_never_called_a_dead_end():
    """Taken, but Jev was never asked there (a cutscene walked us through): nothing is known
    about its ways out, so nothing is claimed."""
    emu, state, memory = town()
    memory.note_map(41)
    memory.note_landing(("warp", 41, None), "viridian_pokecenter")
    words = {o.id: o.memory for o in generate(emu, state, memory, None)}
    assert words["door_41"] == "visited"
```

Then append the new tests:

```python
def test_a_ladder_whose_whole_subtree_is_taken_leads_nowhere_new_and_one_with_more_beyond_does_not():
    """Mt. Moon from 1F: ladder A's B1F pocket goes down to a B2F pocket whose every ladder has
    been taken; ladder B's B2F pocket still has an untaken ladder. Only A is a dead end (#137)."""
    memory = Memory.empty()
    a, b = ("warp", 60, 0), ("warp", 60, 1)
    memory.note_landing(a, "map_60_p0")
    memory.exits["map_60_p0"] = {("warp", 59, 0), ("warp", 61, 0)}
    memory.note_landing(("warp", 59, 0), "map_59")
    memory.note_landing(("warp", 61, 0), "map_61_p0")
    memory.exits["map_61_p0"] = {("warp", 60, 0)}
    memory.note_landing(b, "map_60_p1")
    memory.exits["map_60_p1"] = {("warp", 59, 1), ("warp", 61, 1)}
    memory.note_landing(("warp", 59, 1), "map_59")
    memory.note_landing(("warp", 61, 1), "map_61_p1")
    memory.exits["map_61_p1"] = {("warp", 60, 1), ("warp", 60, 5)}  # 60/5 never taken
    assert memory.leads_nowhere_new("map_59", a) is True
    assert memory.leads_nowhere_new("map_59", b) is False


def test_the_frontier_search_stops_at_the_world_and_at_an_untaken_landing():
    memory = Memory.empty()
    assert memory.leads_nowhere_new("map_59", ("warp", 60, 0)) is False  # never taken
    memory.note_landing(("warp", 15, None), "map_15_p0")  # back outside onto Route 4
    assert memory.leads_nowhere_new("map_59", ("warp", 15, None)) is False  # outdoors: the world
    memory.note_landing(("warp", 60, 0), "map_60_p0")
    memory.exits["map_60_p0"] = {("warp", 61, 0)}
    memory.note_landing(("warp", 61, 0), "map_61_p0")
    memory.exits["map_61_p0"] = {("warp", 15, None)}  # a way out of the cave, taken
    assert memory.leads_nowhere_new("map_59", ("warp", 60, 0)) is False


def test_the_frontier_search_terminates_on_a_cycle_and_never_passes_back_through_here():
    memory = Memory.empty()
    memory.note_landing(("warp", 60, 0), "map_60_p0")
    memory.exits["map_60_p0"] = {("warp", 61, 0), ("warp", 59, 0)}
    memory.note_landing(("warp", 61, 0), "map_61_p0")
    memory.note_landing(("warp", 59, 0), "map_59")
    memory.exits["map_61_p0"] = {("warp", 60, 0)}  # back up to the same pocket: a cycle
    memory.exits["map_59"] = {("warp", 60, 9)}  # an untaken ladder *here* must not count
    assert memory.leads_nowhere_new("map_59", ("warp", 60, 0)) is True


def test_a_memory_written_before_places_existed_still_loads():
    old = {
        "visited_maps": [59, 60],
        "talked": [],
        "tried": [],
        "links": {},
        "exits": {"59": [15, 60]},
        "buildings": [58],
        "ladders": [[59, 60, 0], [60, 59, 0]],
    }
    memory = Memory.from_dict(old)
    assert memory.exits == {} and memory.landings == {("warp", 60, 0): None, ("warp", 59, 0): None}
    assert memory.leads_nowhere_new("map_59", ("warp", 60, 0)) is False
    emu, state, _ = town(warps=[(7, 7, 0, 60)], connections={})
    assert {o.id: o.memory for o in generate(emu, state, memory, None)}["door_60"] == "visited"
```

Note on `door_60` in the last test: with one landing the option id is `door_60` and its leg's `warp_id` is `None`, so its landing is `("warp", 60, None)`; "visited" there comes from `visited_maps`, as today. Keep the assertion as written: it checks the old file does not break the plain door word.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `mise exec -- uv run pytest tests/test_options.py -q`
Expected: the rewritten and new tests FAIL with `AttributeError` on `note_landing` / `landings` / `leads_nowhere_new`.

- [ ] **Step 3: Implement the model**

In `src/jevplays/executor/options.py`, add before `class Memory`:

```python
Landing = tuple[str, int, int | str | None]
"""The identity of a way out as the option generator sees it, before anyone knows where it lands:
("warp", destination map, destination warp id or None) for a door, ("edge", destination map,
direction) for a map connection. `Memory.landings` records the place each one led to."""


def option_landing(option: "Option") -> Landing | None:
    if option.kind not in ("exit", "door") or option.dest_map is None or not option.legs:
        return None
    leg = option.legs[0]
    if option.kind == "exit":
        return ("edge", option.dest_map, leg.direction)
    return ("warp", option.dest_map, leg.warp_id)
```

Replace the `exits`, `buildings` and `ladders` fields with:

```python
    exits: dict[str, set[Landing]] = field(default_factory=dict)
    """place -> the ways out offered there, from every spot in it Jev was asked on (a union: what is
    offered depends on where we stand)."""
    landings: dict[Landing, str | None] = field(default_factory=dict)
    """way out -> the place it was found to lead to, written at the crossing. None for one taken by
    a run from before places existed: still "visited", but the frontier search cannot follow it."""
```

Update `empty`:

```python
    @classmethod
    def empty(cls) -> "Memory":
        return cls(visited_maps=set(), talked=set(), tried=set(), links={}, exits={}, landings={})
```

Replace the `exits`, `buildings` and `ladders` entries in `to_dict` with:

```python
            "exits": {
                place: sorted((list(l) for l in offered), key=str) for place, offered in sorted(self.exits.items())
            },
            "landings": [[list(landing), place] for landing, place in sorted(self.landings.items(), key=str)],
```

and in `from_dict` replace the `exits`, `buildings` and `ladders` arguments with:

```python
            # A memory.json from before places existed keys exits by map id and lists ladders;
            # those exits are dropped (they named maps, not places) and each ladder becomes a
            # landing with no known place (#137).
            exits={
                place: {tuple(l) for l in offered}
                for place, offered in d.get("exits", {}).items()
                if not str(place).isdigit()
            },
            landings={
                **{("warp", dest, warp_id): None for _map, dest, warp_id in d.get("ladders", [])},
                **{tuple(landing): place for landing, place in d.get("landings", [])},
            },
```

Replace `note_exits`, `dead_end` and `note_ladder` with:

```python
    def note_exits(self, place: str, options: "list[Option]") -> None:
        """Remember the ways out this place offered."""
        offered = {landing for o in options if (landing := option_landing(o)) is not None}
        self.exits.setdefault(place, set()).update(offered)

    def note_landing(self, landing: Landing, place: str | None) -> None:
        """Remember where a way out was found to lead, at the moment it was crossed."""
        self.landings[landing] = place

    def leads_nowhere_new(self, here: str, landing: Landing) -> bool:
        """Whether everything beyond `landing` has been seen: every place reachable from where it
        lands, over ways out already taken and never back through `here` nor into an outdoor
        map, has had every way out it offered taken. A building is the one-place case; a cave
        ladder whose pockets below are exhausted is the case this exists for (#137).

        Said only when it is sure: a landing never taken, one whose place is unknown, one that
        opens onto an outdoor map other than here, or a place Jev was never asked on all answer
        False, because any of them may lead somewhere new."""
        start = self.landings.get(landing)
        if start is None or start == here or _outdoors(start):
            return False
        seen = {here}
        stack = [start]
        while stack:
            place = stack.pop()
            if place in seen:
                continue
            seen.add(place)
            if place not in self.exits:
                return False
            for way in self.exits[place]:
                if way not in self.landings:
                    return False
                beyond = self.landings[way]
                if beyond is None:
                    return False
                if beyond in seen:
                    continue
                if _outdoors(beyond):
                    return False
                stack.append(beyond)
        return True
```

and a module-level helper near `option_landing`:

```python
def _outdoors(place: str) -> bool:
    map_id = maps.map_id_of(place)
    return map_id is not None and map_id < ram.FIRST_INDOOR_MAP
```

Replace `word` with:

```python
    def word(self, map_id: int, place: str, option: "Option") -> str:
        if (map_id, option.id) in self.tried:
            return "tried"
        if option.kind == "npc":
            slot = int(option.id.split("_", 1)[1])
            return "talked already" if (map_id, slot) in self.talked else "new"
        landing = option_landing(option)
        if option.kind == "door" and option.legs[0].warp_id is not None:
            # One of several ladders to the same floor: the floor being visited says nothing
            # about where this one lands (#129).
            return "visited" if landing in self.landings else "new"
        if option.kind in ("exit", "door"):
            if option.dest_map not in self.visited_maps:
                return "new"
            # Only the dead end is said. "visited, leads on to new places" was tried and drew Jev
            # harder than "new" did: 4 of 4 probe runs went Pewter <-> Route 2 thousands of times,
            # both ways reading so, with Route 3 "(new)" at 0.20 against 0.72.
            if landing is not None and self.leads_nowhere_new(place, landing):
                return "visited, leads nowhere new"
            return "visited"
        return "new"
```

In `generate` (line 665 on), replace `node = maps.node_of(state.map_id, *state.tile)` with `node = goals_node(state)` where the module imports `from jevplays.executor.goals import Goal, legs_to, node as goals_node`, and replace the last two lines with:

```python
    memory.note_exits(node, drafts)
    drafts = _towards(emu, state, memory, milestone, connections, drafts)
    return [replace(option, memory=memory.word(state.map_id, node, option)) for option in drafts]
```

In `_towards`, replace `not memory.dead_end(state.map_id, o.dest_map)` with
`not ((landing := option_landing(o)) is not None and memory.leads_nowhere_new(goals_node(state), landing))`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `mise exec -- uv run pytest tests/test_options.py tests/test_explore_brain.py tests/test_fixtures.py -q`
Expected: all pass. If `test_a_dead_end_building_never_says_towards_even_when_it_is_the_nearest_way` (from #139) fails, its setup used `memory.buildings`; rewrite its three memory lines to:

```python
    here = state.place or "map_15"
    memory.note_map(68)
    memory.note_landing(("warp", 68, None), "mt_moon_pokecenter")
    memory.exits["mt_moon_pokecenter"] = {("warp", 15, None)}
    memory.note_landing(("warp", 15, None), here)
```

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/executor/options.py tests/test_options.py
git commit -m "feat(executor): memory keys what was offered and where it led by place, and the frontier search follows it (#137)"
```

---

### Task 5: The loop records places and landings

**Files:**
- Modify: `src/jevplays/executor/navigate.py:124-149` (`start_place`)
- Modify: `src/jevplays/loop.py:676-680` (`_walk`), `:711-752` (`_note_crossing`, `_note_ladders`)
- Test: `tests/test_loop.py` (rewrite `test_both_ends_of_a_ladder_the_run_used_are_remembered`), `tests/test_navigator.py`

**Interfaces:**
- Consumes: `GameState.place` (Task 3), `Memory.note_landing`, `Landing` (Task 4).
- Produces: `Navigator.start_place: str | None`, set in `_begin_leg` from the state (`plan` and `step` both receive it; `_begin_leg(emu)` gains a `place` argument). `Loop._note_crossing(leg, from_map, from_tile, from_place)` records links between places and the landing of the leg; `Loop._note_landings(leg, from_place, to_place)` replaces `_note_ladders`.

- [ ] **Step 1: Write the failing tests**

Replace `test_both_ends_of_a_ladder_the_run_used_are_remembered` in `tests/test_loop.py` with:

```python
def test_both_ends_of_a_ladder_the_run_used_are_remembered_as_landings():
    """The ladder taken lands in the place arrived at; the ladder under our feet on arrival
    leads back to the place left (#129, now by place, #137)."""
    emu, bc = (
        explore_emu(sprites=(), connections={}, warps=[(3, 3, 0, ram.WARP_LAST_MAP)]),
        RecordingBroadcaster(),
    )
    loop = Loop(emu, bc, LoopConfig(paced=False))
    loop.memory.note_tried(UNMAPPED_MAP, "grass")
    run(loop, 1)  # takes the only door and plans its warp leg
    emu.mem[ram.wCurMap] = maps.PALLET_TOWN  # the warp lands us there...
    here = (emu.mem[ram.wXCoord], emu.mem[ram.wYCoord])
    emu.mem[ram.wWarpEntries : ram.wWarpEntries + 4] = [here[1], here[0], 5, UNMAPPED_MAP]  # ...on a ladder
    run(loop, 1)
    assert loop.memory.landings[("warp", maps.PALLET_TOWN, None)] == "pallet_town"
    assert loop.memory.landings[("warp", UNMAPPED_MAP, 5)] == f"map_{UNMAPPED_MAP}"
```

Append to `tests/test_navigator.py` (check its imports; it builds a `Navigator` and a fake state already — follow the file's own helper for a state):

```python
def test_a_leg_remembers_the_place_it_began_in():
    from dataclasses import replace

    from jevplays.executor.navigate import Leg, Navigator
    from tests.support import FakeEmulator, overworld_state

    nav = Navigator()
    state = replace(overworld_state(map_id=60), place="map_60_p2")
    nav.plan(FakeEmulator(), state, [Leg(kind="walk", target=(1, 1))])
    assert nav.start_place == "map_60_p2"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `mise exec -- uv run pytest tests/test_loop.py tests/test_navigator.py -q -k "landings or began_in"`
Expected: FAIL (`AttributeError: 'Navigator' object has no attribute 'start_place'`, `KeyError`).

- [ ] **Step 3: Implement**

In `src/jevplays/executor/navigate.py`:

```python
    start_place: str | None = None
    """The place the current leg was begun in (`GameState.place`), so a crossing is recorded
    between places rather than maps (#137)."""
```

after `start_tile`; change `_begin_leg(self, emu)` to `_begin_leg(self, emu, place: str | None = None)` and add `self.start_place = place` in it; in `plan` call `self._begin_leg(emu, state.place)`; find the other `_begin_leg(emu)` call in `_advance` (`grep -n "_begin_leg" src/jevplays/executor/navigate.py`) and pass the current state's place there too (`_advance` is called from `step(self, emu, state)`; thread `state.place` through: `_advance(self, emu, place=None)`).

In `src/jevplays/loop.py` `_walk`, read `from_place = self.navigator.start_place` alongside `from_map, from_tile` and pass it: `self._note_crossing(leg, from_map, from_tile, from_place)`.

Replace `_note_crossing` and `_note_ladders`:

```python
    def _note_crossing(
        self, leg, from_map: int | None, from_tile: tuple[int, int] | None, from_place: str | None = None
    ) -> None:
        """Add a leg the run just walked across a map boundary to its own map graph (#35), between
        the places it left and arrived in (#137), and remember where the way out it took lands.

        Only `edge` and `warp` legs, and only when the map really changed: a `walk` leg finishing
        teaches nothing, and a leg that came back `lost` never got here -- the map changed under
        it -- so this is never reached for one. A warp records the map it actually landed on
        rather than the leg's `dest_map`, which is `WARP_LAST_MAP` for a building's way out and
        names nothing."""
        if leg is None or leg.kind not in ("edge", "warp") or from_map is None or from_tile is None:
            return
        to_map = self.emu.mem[ram.wCurMap]
        if to_map == from_map:
            return
        from_node = from_place or maps.node_of(from_map, *from_tile)
        to_node = snapshot(self.emu).place
        before = len(self.memory.links.get(from_node, ()))
        # The way back is a warp to the map we left when this map has one (a ladder); otherwise it
        # is the building's "back out the way you came in".
        straight_back = any(w.dest == from_map for w in world.read_warps(self.emu.mem))
        self.memory.note_crossing(
            from_node,
            to_node,
            direction=leg.direction if leg.kind == "edge" else None,
            dest_map=None if leg.kind == "edge" else to_map,
            back_dest_map=from_map if straight_back else maps.WARP_LAST_MAP,
        )
        self._note_landings(leg, to_map, from_node, to_node)
        if len(self.memory.links.get(from_node, ())) != before:
            self._save_memory()

    def _note_landings(self, leg, to_map: int, from_place: str, to_place: str) -> None:
        """Where the way out just taken lands, and where the warp under our feet on arrival leads
        back to (#129, #137). The leg's destination is read as the map arrived on, which is what
        the option generator will key the same door by next time (`option_landing`)."""
        if leg.kind == "edge":
            self.memory.note_landing(("edge", to_map, leg.direction), to_place)
        else:
            self.memory.note_landing(("warp", to_map, leg.warp_id), to_place)
            here = (self.emu.mem[ram.wXCoord], self.emu.mem[ram.wYCoord])
            for warp in world.read_warps(self.emu.mem):
                if (warp.x, warp.y) == here:
                    self.memory.note_landing(("warp", warp.dest, warp.warp_id), from_place)
        self._save_memory()
```

`snapshot` is imported in `loop.py` already (check `grep -n "^from jevplays.state.snapshot" src/jevplays/loop.py`). Delete `_note_ladders` and its caller line.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `mise exec -- uv run pytest tests/test_loop.py tests/test_loop_forced.py tests/test_navigator.py tests/test_options.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/executor/navigate.py src/jevplays/loop.py tests/test_loop.py tests/test_navigator.py
git commit -m "feat(executor): crossings and landings are recorded between places (#137)"
```

---

### Task 6: Routes and the heal trip start from the place

**Files:**
- Modify: `src/jevplays/executor/options.py:504-533` (`_heal_option`, no code change expected), `generate`
- Test: `tests/test_options.py`

**Interfaces:**
- Consumes: `goals.node` (Task 3), `Memory.links` keyed by place (Task 5).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_options.py`:

```python
def test_a_heal_trip_is_planned_only_from_a_pocket_that_has_left():
    """Round 11: at critical HP in a Mt. Moon 1F pocket that cannot reach the entrance, "go heal
    at Pewter Pokémon Center" was offered, failed on the spot, and was chosen 4,731 times. With
    places as pockets the crossing out of the cave was recorded from the entrance pocket, so the
    other pocket has no way out and no trip (#137)."""
    from dataclasses import replace as with_fields

    emu = FakeEmulator()
    install_map(emu, ["..##..", "..##..", "..##..", "..##..", "..##..", "..##.."], warps=[(0, 0, 0, 15)])
    emu.mem[ram.wCurMap] = 59
    emu.mem[ram.wXCoord], emu.mem[ram.wYCoord] = 5, 2  # the right-hand pocket; the entrance is left
    hurt_lead(emu)
    walked = Memory.empty()
    walked.note_crossing("pewter_city", "map_14", direction="east")
    walked.note_crossing("map_14", "map_15", direction="north")
    walked.note_crossing("map_15", "map_59_p0", dest_map=59, back_dest_map=15)
    walked.note_crossing("pewter_city", "pewter_pokecenter", dest_map=maps.PEWTER_POKECENTER)
    state = snapshot(emu)
    assert state.place == "map_59_p1"
    assert not any(o.kind == "heal" for o in generate(emu, state, walked, None))
    state = with_fields(state, place="map_59_p0", tile=(1, 1))
    emu.mem[ram.wXCoord] = 1
    heal = next(o for o in generate(emu, snapshot(emu), walked, None) if o.kind == "heal")
    assert heal.text == "go heal at Pewter Pokémon Center"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `mise exec -- uv run pytest tests/test_options.py -q -k "pocket_that_has_left"`
Expected: FAIL only if `generate` still names the node from `maps.node_of` somewhere (grep `node_of(state.map_id` in `src/jevplays/executor/options.py`); after Task 4 it should PASS already. If it passes, keep it: it pins the behaviour the round-11 loop violated.

- [ ] **Step 3: Implement**

Replace any remaining `maps.node_of(state.map_id, *state.tile)` in `src/jevplays/executor/options.py` with `goals_node(state)`. `_heal_option` and `_milestone_option` take `node` as a parameter and are otherwise unchanged.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `mise exec -- uv run pytest tests/test_options.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/executor/options.py tests/test_options.py
git commit -m "fix(executor): a heal trip from inside a cave starts from the pocket the run has left (#137)"
```

---

### Task 7: The question's gloss, and the fixture

**Files:**
- Modify: `src/jevplays/brain/explore.py:74-77`
- Modify: `tests/fixtures/responses/explore_viridian.json` (re-recorded)
- Test: `tests/test_explore_brain.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_explore_brain.py`:

```python
def test_the_question_says_leads_nowhere_new_means_everything_beyond_was_seen():
    instructions = explore_questions(explore_state(overworld_state(), [], milestone=None))["explore"][
        "instructions"
    ]
    assert "a place beyond which everything has already been seen" in instructions
    assert "building whose only way out" not in instructions
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `mise exec -- uv run pytest tests/test_explore_brain.py -q -k "everything_beyond"`
Expected: FAIL on the first assertion.

- [ ] **Step 3: Implement**

In `src/jevplays/brain/explore.py` replace the fragment

```python
                'we have done it before and may not need to again, and "leads nowhere new" '
                "after it means a building whose only way out is back here; "
```

with

```python
                'we have done it before and may not need to again, and "leads nowhere new" '
                "after it means a place beyond which everything has already been seen; "
```

(check the exact current lines with `sed -n 70,80p src/jevplays/brain/explore.py` and replace the two that carry the old gloss).

- [ ] **Step 4: Re-record the fixture and run the tests**

Run: `mise exec -- uv run Scripts/record-fixtures.py --only explore_viridian`
Then: `mise exec -- uv run pytest tests/test_explore_brain.py tests/test_fixtures.py -q`
Expected: all pass; `git diff --stat tests/fixtures` shows one file changed.

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/brain/explore.py tests/test_explore_brain.py tests/fixtures/responses/explore_viridian.json
git commit -m "feat(brain): the explore question says what leads nowhere new means for a cave (#137)"
```

---

### Task 8: ROM test on a real Mt. Moon B1F pocket

**Files:**
- Create: `states/mt_moon_b1f.state` (not committed: `states/` is gitignored; copied by hand)
- Test: `tests/rom/test_world.py`

- [ ] **Step 1: Find a B1F checkpoint among the probe runs and copy it**

```bash
cd /Users/builder/orca/projects/jevplays/.worktrees/pocket-places
mise exec -- uv run python - <<'EOF'
import glob, os
from pathlib import Path
from jevplays.emulator.pyboy import Emulator
from jevplays.emulator import ram
with Emulator(Path(os.environ["JEVPLAYS_ROM"])) as emu:
    for p in sorted(glob.glob("../probe/runs/*/*/checkpoint-*.state"))[::7]:
        emu.load(Path(p))
        if emu.mem[ram.wCurMap] == 60 and not emu.mem[ram.wIsInBattle]:
            print(p); break
EOF
```

Copy the printed path to `states/mt_moon_b1f.state`.

- [ ] **Step 2: Write the test**

Append to `tests/rom/test_world.py`:

```python
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
```

- [ ] **Step 3: Run it**

Run: `mise exec -- uv run pytest tests/rom/test_world.py -q`
Expected: PASS (or SKIP if the state could not be found; then say so in the PR).

- [ ] **Step 4: Commit**

```bash
git add tests/rom/test_world.py
git commit -m "test(executor): a real Mt. Moon B1F floor has several pockets (#137)"
```

---

### Task 9: Full check, push, PR

- [ ] **Step 1: Run the whole check**

Run: `mise run check`
Expected: lint clean, all tests pass (the number grows by about fifteen over main's).

- [ ] **Step 2: Push and open the PR**

```bash
git push -u origin tylervick/pocket-places
gh pr create --title "feat(executor): places are pockets, so routes and the frontier word work inside a cave" --body "..."
```

The body states: what (one paragraph from the spec), the round-11 evidence, the memory.json migration, the re-recorded fixture, the test count, and that round 12 (one fresh + one resumed run, 15 min) follows. Closes #137. Note that this branch also carries the spec commit (PR #143); if #143 has merged, rebase first.

- [ ] **Step 3: Round 12**

From `.worktrees/probe` on this branch's tip (never while a round runs): `probe-round.sh`'s setup, then `round11.sh`'s two runs (copy and rename; 900 s each). Report per the spec's section 9: heal trips offered from a pocket with no way out (expect 0), "leads nowhere new" on exhausted ladders, farthest map reached.
