# Milestone 3a: Navigation and Goals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The agent plays from the bedroom to Brock on its own: code reads the whole current map from RAM and ROM and paths across it, Jev picks the next goal at overworld decision points and answers prompts and menus, and a goal table carries the early game's story (starter, parcel, Pokédex, old man, Poké Balls, training, Viridian Forest, Pewter Gym).

**Architecture:** `executor/world.py` rebuilds the current map's walkability (one cell per player step) from `wOverworldMap` plus the tileset's block and collision tables in ROM, and reads warps, connections, and sprites from RAM; `executor/navigate.py` becomes a `Navigator` state machine that plans a route across maps with a static link table (`executor/maps.py`) and executes one tile step per loop iteration with A* inside each map, NPC-aware re-planning, interruption hand-off, and stuck detection. `executor/goals.py` is the goal table; `brain/goal.py` and `brain/prompt.py` are the two new decision points (spec 8.2 and 8.3); `executor/shop.py` and `executor/talk.py` are scripted macros for the Mart, the nurse, and talking to sprites. The loop's OVERWORLD branch runs the navigator when a goal is active and asks Jev otherwise; PROMPT and MENU ask Jev.

**Tech Stack:** as milestone 2. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-20-jevplays-design.md`, sections 6, 7, 8.2, 8.3, 9, 12, 13, 14. Deviations recorded in Task 11: (1) section 9's "waypoint-based" navigation with A* inside the visible window is replaced by full-map A* from RAM and ROM plus a static map-link table, because the walkability grid rebuilt from `wOverworldMap` matched PyBoy's window on every cell of every probed map and removes the hand-written waypoints entirely; (2) milestone 3 is delivered as 3a (this plan: navigation, prompts, menus, goals) and 3b (run logging, resume, replay, stream layout); (3) the Mart and Pokémon Center interactions are scripted macros rather than Jev-answered menus, because their screens (quantity box, HEAL/CANCEL) are mechanical; Jev's menu Choice remains for unscripted menus.

## Global Constraints

- Everything from milestones 1 and 2 still binds: Python `>=3.12`; ruff line length 110, `select = ["E", "F", "I", "B"]`, `ignore = ["E501"]`; `import pyboy` only in `src/jevplays/emulator/pyboy.py`; `import typesafe_sdk` only in `src/jevplays/brain/client.py` and `Scripts/record-fixtures.py`; `tests/test_imports.py` enforces both; `tests/rom/` not collected without `JEVPLAYS_ROM`; nothing game-derived committed; `snapshot()` pure; Jev never receives HP, PP, money numbers, coordinates, or screenshots (levels and map names are allowed); one request per decision point; thresholds only in `policy.py`; conventional commits; branch `tylervick/milestone-3-goals` (created from `main` at `03ea1da`).
- Verified RAM facts (measured 2026-09-20 on this ROM): `wOverworldMap 0xC6E8` holds the current map's block ids with a 3-block border on every side, so row stride is `width + 6` and block `(bx, by)` is at `wOverworldMap + (by + 3) * (width + 6) + (bx + 3)`; `wCurMapTileset 0xD367`, `wCurMapHeight 0xD368` and `wCurMapWidth 0xD369` (in blocks); `wMapConnections 0xD370` (bit 3 north, 2 south, 1 west, 0 east) with the connected map ids at `0xD371` north, `0xD37C` south, `0xD387` west, `0xD392` east; `wNumberOfWarps 0xD3AE`, `wWarpEntries 0xD3AF` as 4-byte `(y, x, warp id, destination map)` records where destination `0xFF` means "the map we came from"; `wTilesetBank 0xD52B`, `wTilesetBlocksPtr 0xD52C` (little-endian ROM pointer; each block is 16 tile ids, 4x4 row-major), `wTilesetCollisionPtr 0xD530` (list of walkable tile ids terminated by 0xFF), `wGrassTile 0xD535` (0xFF when none); a step cell `(x, y)` is walkable when the bottom-left tile of its 2x2-tile quadrant is in the walkable list (this reproduced PyBoy's window on 100% of cells for the bedroom, Route 1, Viridian, the gate, and the forest); sprites: slot `i` (1..15) has picture id at `0xC100 + 16 * i` (0 = empty) and map coordinates `x = mem[0xC200 + 16 * i + 5] - 4`, `y = mem[0xC200 + 16 * i + 4] - 4`, matching pokered's `object_event` coordinates exactly; event flags: bit `n` of the table at `wEventFlags 0xD747` (`mem[0xD747 + n // 8] >> (n % 8) & 1`), with `followed_oak_into_lab 0`, `pallet_after_getting_pokeballs 6`, `oak_asked_to_choose_mon 33`, `got_starter 34`, `battled_rival_in_oaks_lab 35`, `got_pokeballs_from_oak 36`, `got_pokedex 37`, `oak_appeared_in_pallet 39`, `oak_got_parcel 56`, `got_oaks_parcel 57`, `beat_brock 119`; `wPlayerMonNumber 0xCC2F`.
- Verified game facts: the bedroom stairs are the walkable warp at (7, 1) to map 37; house exits are door mats at the bottom edge (step `down` off them); Pallet Town warps are Red's house (5, 5), Blue's house (13, 5), Oak's lab (12, 11); walking onto (10, 1) in Pallet before the starter triggers Oak; the lab's balls are at y = 3, x = 6 Charmander, 7 Squirtle, 8 Bulbasaur (interact from (x, 4) facing up); Oak stands at (5, 2) (sprite 3) in the lab after the starter, talked to from (5, 3) facing up; the rival battle triggers on the way to the lab door; Route 1 leads north from Pallet's (10, 0)/(11, 0) and into Viridian at (20, 34); Viridian warps: Center (23, 25) → 41, Mart (29, 19) → 42; entering the Mart before delivery triggers the clerk who hands over Oak's Parcel (item 70, flag `got_oaks_parcel`); talking to Oak with the parcel sets `oak_got_parcel` and `got_pokedex`; Oak gives no Poké Balls in Red (they are bought); the sleeping old man (sprite 72 at (18, 9) in Viridian) blocks the road north until talked to from (18, 10) facing up after the parcel is delivered, and answering the prompt YES clears him; Viridian's north exit is (18, 0) into Route 2 at (8, 71); Route 2's south gate warp is (3, 43) → 50, the gate's forest exit is the walkable warp (5, 0) → 51 (the (4, 0) entry is not enterable), the forest's north exits are (1, 0)/(2, 0) → 47, the north gate's Route 2 exit lands at (3, 11), Route 2's north edge leads to Pewter; Pewter warps: gym (16, 17) → 54, Mart (23, 17) → 56, Center (13, 25) → 58; in the gym Brock (sprite 12, SUPER_NERD) stands at (4, 1) facing down and the Jr Trainer at (3, 6); item balls on the ground are sprites (picture 61) that block a cell; the nurse is sprite slot 1 at (3, 1) in a Center, talked to from (3, 3) facing up, and her prompt is a two-item menu `HEAL`/`CANCEL` at `wTopMenuItemY 8`, `wTopMenuItemX 12`; the Mart clerk is slot 1 at (0, 5), talked to from (2, 5) facing left; the shop menu is `BUY`/`SELL`/`QUIT` at `wTopMenuItemY 1`, `wTopMenuItemX 1`; after BUY the item list shows at `wTopMenuItemY 4`, `wTopMenuItemX 5` with `POKé BALL` first and its price on the next row; A on an item opens a quantity box reading `×01` with the total, `up` increments, A opens a YES/NO prompt, A buys; wild battles on Route 1, Route 2, and the forest interrupt walks and are fought by the existing brain; trainers stop the player before the battle text.
- Milestone 2 interfaces this plan builds on: `Emulator` (`mem`, `tilemap`, `rows`, `press`, `tick`, `save`, `load`), `snapshot`, `GameState`, `Mode`, `skip_dialog`, `answer_prompt`, `cursor_label`, `dialog_lines`, `yes_no_open`, `executor/battle.py`, `Brain.ask`, `Decision`, `Loop`, `decision_event`.

---

## File structure

```
src/jevplays/emulator/ram.py            + map, warp, connection, tileset, sprite, event-flag addresses; flag helpers (Task 1)
src/jevplays/emulator/pyboy.py          + rom(bank, addr) (Task 1)
src/jevplays/state/data/events.json     event flag name -> bit index, 507 entries (Task 1)
src/jevplays/state/events.py            TRACKED_FLAGS, flag_index(), flags_set(mem) (Task 1)
src/jevplays/state/snapshot.py          + Sprite, GameState.flags, .sprites, .map_size (Task 2)
src/jevplays/executor/world.py          MapGrid (RAM+ROM walkability), warps, connections, astar, walkable_warps (Task 3)
src/jevplays/executor/maps.py           LINKS: static map graph for the early game; segment_of() (Task 4)
src/jevplays/executor/navigate.py       Navigator: legs, route planning, one step per call, interruptions, stuck detection (Task 4)
src/jevplays/executor/talk.py           talk_to(emu, x, y, face): walk adjacent, face, A, skip_dialog with an answer policy (Task 5)
src/jevplays/executor/shop.py           heal_at_nurse, buy_pokeballs (scripted macros) (Task 5)
src/jevplays/executor/goals.py          Goal table: availability, completion, legs (Task 6)
src/jevplays/brain/goal.py              goal_state, goal_questions, decide_goal (Task 7)
src/jevplays/brain/prompt.py            prompt_state/questions/decide, menu_state/questions/decide (Task 7)
src/jevplays/brain/policy.py            + HEAL_FIRST_THRESHOLD, PROMPT_YES_THRESHOLD, MENU_CLOSE_THRESHOLD, NEVER_NICKNAME (Task 7)
src/jevplays/loop.py                    + navigator, goal/prompt/menu branches, goal hold (Task 8)
Scripts/make-states.py                  + pallet, viridian, mart_parcel, dex states (Task 9)
Scripts/record-fixtures.py              + goal and prompt fixtures (Task 9)
src/jevplays/dashboard/static/app.js    + route/leg readout, decision kinds in the log (Task 10)
docs, README, CLAUDE.md, spec amendments, PR (Task 11)
```

---

### Task 1: Map, sprite, and event-flag addresses; ROM reads

**Files:**
- Modify: `src/jevplays/emulator/ram.py`, `src/jevplays/emulator/pyboy.py`
- Create: `src/jevplays/state/data/events.json` (copy from `/private/tmp/claude-503/-Users-builder-orca-projects-jevplays/cef7ae7f-42b5-46cc-8fab-57ac894a688b/scratchpad/gen1_events.json`), `src/jevplays/state/events.py`
- Test: `tests/test_ram.py`, `tests/test_events.py`, `tests/rom/test_ram.py`, `tests/rom/test_world.py` (created here, extended in Task 3)

**Interfaces:**
- `ram.py` adds: `wOverworldMap = 0xC6E8`, `MAP_BORDER_BLOCKS = 3`, `wSpriteStateData1 = 0xC100`, `wSpriteStateData2 = 0xC200`, `SPRITE_SLOT_SIZE = 16`, `SPRITE_SLOTS = 15`, `SPRITE_COORD_OFFSET = 4`, `wPlayerMonNumber` (exists), `wCurMapTileset = 0xD367`, `wCurMapHeight = 0xD368`, `wCurMapWidth = 0xD369`, `wMapConnections = 0xD370`, `CONNECTION_MAP_ADDRESSES = {"north": 0xD371, "south": 0xD37C, "west": 0xD387, "east": 0xD392}`, `CONNECTION_BITS = {"north": 3, "south": 2, "west": 1, "east": 0}`, `wNumberOfWarps = 0xD3AE`, `wWarpEntries = 0xD3AF`, `WARP_ENTRY_SIZE = 4`, `WARP_LAST_MAP = 0xFF`, `wTilesetBank = 0xD52B`, `wTilesetBlocksPtr = 0xD52C`, `wTilesetCollisionPtr = 0xD530`, `wGrassTile = 0xD535`, `COLLISION_END = 0xFF`; `read_u16le(mem, addr) -> int`; `flag_bit(mem, index) -> bool`.
- `Emulator.rom(bank: int, addr: int) -> int` reads one ROM byte through PyBoy's `memory[bank, addr]`; `Memory` protocol documents that a `(bank, addr)` tuple key reads ROM. `FakeMemory` gains `rom: dict[tuple[int, int], int]` and returns `self.rom.get(key, 0)` for tuple keys.
- `events.py`: `EVENTS: dict[str, int]` loaded from `data/events.json`; `TRACKED_FLAGS: tuple[str, ...] = ("oak_appeared_in_pallet", "followed_oak_into_lab", "oak_asked_to_choose_mon", "got_starter", "battled_rival_in_oaks_lab", "got_oaks_parcel", "oak_got_parcel", "got_pokedex", "got_pokeballs_from_oak", "got_town_map", "beat_brock")`; `flag_index(name) -> int`; `flags_set(mem) -> frozenset[str]` (the tracked flags that are set).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ram.py`:

```python
def test_map_and_sprite_addresses():
    assert ram.wOverworldMap == 0xC6E8 and ram.MAP_BORDER_BLOCKS == 3
    assert (ram.wCurMapWidth, ram.wCurMapHeight) == (0xD369, 0xD368)
    assert ram.wNumberOfWarps == 0xD3AE and ram.wWarpEntries == 0xD3AF and ram.WARP_LAST_MAP == 0xFF
    assert ram.CONNECTION_MAP_ADDRESSES["north"] == 0xD371 and ram.CONNECTION_BITS["north"] == 3
    assert (ram.wTilesetBank, ram.wTilesetBlocksPtr, ram.wTilesetCollisionPtr, ram.wGrassTile) == (0xD52B, 0xD52C, 0xD530, 0xD535)
    assert ram.wSpriteStateData1 == 0xC100 and ram.wSpriteStateData2 == 0xC200 and ram.SPRITE_COORD_OFFSET == 4


def test_read_u16le_and_flag_bit():
    mem = FakeMemory()
    mem[0xD52C] = 0x34
    mem[0xD52D] = 0x12
    assert ram.read_u16le(mem, 0xD52C) == 0x1234
    mem[ram.wEventFlags + 4] = 0b0000_0100  # bit index 34 = byte 4, bit 2
    assert ram.flag_bit(mem, 34) is True
    assert ram.flag_bit(mem, 35) is False


def test_fake_memory_serves_rom_reads():
    mem = FakeMemory()
    mem.rom[(25, 0x4000)] = 0x77
    assert mem[25, 0x4000] == 0x77
    assert mem[25, 0x4001] == 0
```

`tests/test_events.py`:

```python
from jevplays.emulator import ram
from jevplays.state.events import EVENTS, TRACKED_FLAGS, flag_index, flags_set
from tests.support import FakeMemory


def test_event_table_has_the_story_flags_at_the_measured_bits():
    assert len(EVENTS) == 507
    assert flag_index("got_starter") == 34 and flag_index("oak_got_parcel") == 56
    assert flag_index("got_pokedex") == 37 and flag_index("beat_brock") == 119


def test_flags_set_reads_only_tracked_flags():
    mem = FakeMemory()
    for name in ("got_starter", "battled_rival_in_oaks_lab"):
        n = flag_index(name)
        mem[ram.wEventFlags + n // 8] = mem[ram.wEventFlags + n // 8] | (1 << (n % 8))
    assert flags_set(mem) == frozenset({"got_starter", "battled_rival_in_oaks_lab"})
    assert set(TRACKED_FLAGS) >= flags_set(mem)
```

`tests/rom/test_world.py` (this task's part):

```python
from jevplays.emulator import ram
from jevplays.emulator.pyboy import Emulator
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_ram.py tests/test_events.py -q`
Expected: FAIL (`AttributeError: ... wOverworldMap`, `ModuleNotFoundError: jevplays.state.events`).

- [ ] **Step 3: Implement**

`ram.py` additions (address-ordered, with the comments below):

```python
# Sprites (NPCs, item balls, the player in slot 0). Slot i has its picture id at
# wSpriteStateData1 + 16 * i (0 = empty) and its map position in the second table:
# x = mem[wSpriteStateData2 + 16 * i + 5] - 4, y = mem[... + 4] - 4. Matches pokered's object_event coordinates.
wSpriteStateData1 = 0xC100
wSpriteStateData2 = 0xC200
SPRITE_SLOT_SIZE = 16
SPRITE_SLOTS = 15
SPRITE_COORD_OFFSET = 4

# The current map's block ids, with a 3-block border on every side, so a row is width + 6 blocks.
wOverworldMap = 0xC6E8
MAP_BORDER_BLOCKS = 3

wCurMapTileset = 0xD367
wCurMapHeight = 0xD368  # blocks
wCurMapWidth = 0xD369  # blocks
wMapConnections = 0xD370  # bit 3 north, 2 south, 1 west, 0 east
CONNECTION_BITS = {"north": 3, "south": 2, "west": 1, "east": 0}
CONNECTION_MAP_ADDRESSES = {"north": 0xD371, "south": 0xD37C, "west": 0xD387, "east": 0xD392}
wNumberOfWarps = 0xD3AE
wWarpEntries = 0xD3AF  # 4 bytes each: y, x, warp id, destination map
WARP_ENTRY_SIZE = 4
WARP_LAST_MAP = 0xFF  # destination "the map we came from"

# Tileset tables in ROM: blocks are 16 tile ids (4x4, row-major); the collision list is the
# walkable tile ids, 0xFF-terminated; the grass tile is walkable too when it is not 0xFF.
wTilesetBank = 0xD52B
wTilesetBlocksPtr = 0xD52C  # little-endian ROM address
wTilesetCollisionPtr = 0xD530
wGrassTile = 0xD535
COLLISION_END = 0xFF


def read_u16le(mem: Memory, addr: int) -> int:
    return mem[addr] | (mem[addr + 1] << 8)


def flag_bit(mem: Memory, index: int) -> bool:
    return bool((mem[wEventFlags + index // 8] >> (index % 8)) & 1)
```

Update the `Memory` protocol docstring: "an int key reads WRAM; a `(bank, addr)` tuple reads ROM". `Emulator.rom(bank, addr)` returns `int(self._py.memory[bank, addr])`. `FakeMemory.__getitem__` gains `if isinstance(key, tuple): return self.rom.get(key, 0)` with `self.rom = {}` in `__init__`.

`events.py`:

```python
"""Story progress flags. The table is pokered's event list; the tracked subset is what goals read."""

import json
from pathlib import Path

from jevplays.emulator import ram

EVENTS: dict[str, int] = json.loads((Path(__file__).parent / "data" / "events.json").read_text(encoding="utf-8"))

TRACKED_FLAGS: tuple[str, ...] = (
    "oak_appeared_in_pallet", "followed_oak_into_lab", "oak_asked_to_choose_mon", "got_starter",
    "battled_rival_in_oaks_lab", "got_oaks_parcel", "oak_got_parcel", "got_pokedex",
    "got_pokeballs_from_oak", "got_town_map", "beat_brock",
)


def flag_index(name: str) -> int:
    return EVENTS[name]


def flags_set(mem: ram.Memory) -> frozenset[str]:
    return frozenset(name for name in TRACKED_FLAGS if ram.flag_bit(mem, EVENTS[name]))
```

Copy `events.json` into `src/jevplays/state/data/` and add a line to that directory's README (`events.json`: event flag name to bit index in `wEventFlags`, 507 entries, from PyBoy's Gen 1 constants).

- [ ] **Step 4: Run all of it**

Run: `uv run pytest tests/test_ram.py tests/test_events.py -q` then `mise exec -- uv run pytest tests/rom/test_ram.py tests/rom/test_world.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/emulator/ram.py src/jevplays/emulator/pyboy.py src/jevplays/state/data src/jevplays/state/events.py tests/support.py tests/test_ram.py tests/test_events.py tests/rom/test_ram.py tests/rom/test_world.py
git commit -m "feat(emulator): map, warp, sprite, tileset, and event-flag addresses with ROM reads"
```

---

### Task 2: Flags, sprites, and map size in GameState

**Files:**
- Modify: `src/jevplays/state/snapshot.py`, `tests/support.py`
- Test: `tests/test_snapshot.py`, `tests/rom/test_snapshot.py`

**Interfaces:**
- `@dataclass(frozen=True) class Sprite(slot: int, picture: int, x: int, y: int)`; `read_sprites(mem) -> tuple[Sprite, ...]` (slots 1..15 with picture != 0); `GameState` gains `flags: frozenset[str]`, `sprites: tuple[Sprite, ...]`, `map_size: tuple[int, int]` (width, height in steps = blocks * 2); `to_dict()` turns `flags` into a sorted list. `tests.support.FakeEmulator.set_sprites([(slot, picture, x, y), ...])` writes the two sprite tables.

- [ ] **Step 1: Failing tests**

Append to `tests/test_snapshot.py`:

```python
from jevplays.state.snapshot import Sprite


def test_sprites_flags_and_map_size_are_parsed():
    emu = FakeEmulator()
    bedroom(emu)
    emu.mem[ram.wCurMapWidth] = 10
    emu.mem[ram.wCurMapHeight] = 18
    emu.set_sprites([(1, 72, 18, 9), (5, 3, 5, 2)])
    n = flag_index("got_starter")
    emu.mem[ram.wEventFlags + n // 8] = 1 << (n % 8)
    state = snapshot(emu)
    assert state.map_size == (20, 36)
    assert state.sprites == (Sprite(slot=1, picture=72, x=18, y=9), Sprite(slot=5, picture=3, x=5, y=2))
    assert state.flags == frozenset({"got_starter"})
    assert state.to_dict()["flags"] == ["got_starter"]
```

(import `flag_index` from `jevplays.state.events`.) Append to `tests/rom/test_snapshot.py`:

```python
def test_route1_state_carries_flags_and_size(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("route1"))
        state = snapshot(emu)
        assert state.map_size == (20, 36)
        assert "got_starter" in state.flags and "got_pokedex" not in state.flags
        assert all(0 <= s.x < 20 and 0 <= s.y < 36 for s in state.sprites)
```

- [ ] **Step 2: Implement**

```python
@dataclass(frozen=True)
class Sprite:
    slot: int
    picture: int
    x: int
    y: int


def read_sprites(mem: ram.Memory) -> tuple[Sprite, ...]:
    out = []
    for slot in range(1, ram.SPRITE_SLOTS + 1):
        picture = mem[ram.wSpriteStateData1 + ram.SPRITE_SLOT_SIZE * slot]
        if picture == 0:
            continue
        base = ram.wSpriteStateData2 + ram.SPRITE_SLOT_SIZE * slot
        out.append(Sprite(slot=slot, picture=picture, x=mem[base + 5] - ram.SPRITE_COORD_OFFSET, y=mem[base + 4] - ram.SPRITE_COORD_OFFSET))
    return tuple(out)
```

In `snapshot()`: `flags=flags_set(mem)`, `sprites=read_sprites(mem)`, `map_size=(mem[ram.wCurMapWidth] * 2, mem[ram.wCurMapHeight] * 2)`. In `to_dict()`, after `_listify`, set `d["flags"] = sorted(self.flags)`. `FakeEmulator.set_sprites(specs)` clears both tables for slots 1..15 then writes picture at `0xC100 + 16*slot` and `x + 4` / `y + 4` at `0xC200 + 16*slot + 5` / `+ 4`.

- [ ] **Step 3: Run and commit**

Run: `uv run pytest tests/test_snapshot.py -q` and `mise exec -- uv run pytest tests/rom/test_snapshot.py -q`; expected all pass.

```bash
git add src/jevplays/state/snapshot.py tests/support.py tests/test_snapshot.py tests/rom/test_snapshot.py
git commit -m "feat(state): story flags, sprites, and map size in GameState"
```

---

### Task 3: The world model: full-map walkability, warps, connections, A*

**Files:**
- Create: `src/jevplays/executor/world.py`
- Test: `tests/test_world.py`, `tests/rom/test_world.py` (extend)

**Interfaces:**
- `@dataclass(frozen=True) class Warp(x: int, y: int, warp_id: int, dest: int)`; `read_warps(mem) -> tuple[Warp, ...]`; `read_connections(mem) -> dict[str, int]` (direction → map id, only those present); `class MapGrid` with `width`, `height` (steps), `cells: list[list[int]]` (1 walkable), `walkable(x, y) -> bool`, `in_bounds(x, y)`; `build_grid(emu) -> MapGrid` (from `wOverworldMap` + ROM tables via `emu.mem` and `emu.rom`); `blocked_by_sprites(sprites) -> set[tuple[int,int]]`; `astar(grid, start, goal, blocked=frozenset()) -> list[tuple[int,int]] | None` (path excluding start, including goal; the goal must be walkable and not blocked); `reachable_edge(grid, start, direction, blocked) -> tuple[int,int] | None` (nearest by BFS); `walkable_warps(grid, warps, dest) -> list[Warp]`; `DIRECTIONS = {"up": (0,-1), "down": (0,1), "left": (-1,0), "right": (1,0)}`; `direction_to(a, b) -> str`.
- `tests.support` gains `install_map(emu, rows: list[str], warps=(), connections=None, tileset=(bank, blocks_addr, collision_addr))`: writes a synthetic map into the fake so `build_grid` works without a ROM: it defines two blocks in the fake ROM (block 0 all-walkable tile 1, block 1 all-wall tile 2), a collision list `[1, 0xFF]`, and lays out `wOverworldMap` from the rows (`.` walkable, `#` wall), padding the border with block 1.

- [ ] **Step 1: Failing tests**

```python
# tests/test_world.py
from jevplays.emulator import ram
from jevplays.executor.world import Warp, astar, blocked_by_sprites, build_grid, direction_to, reachable_edge, read_connections, read_warps, walkable_warps
from jevplays.state.snapshot import Sprite
from tests.support import FakeEmulator, install_map

ROWS = [
    "....",
    ".##.",
    ".#..",
    "....",
]


def test_build_grid_reproduces_the_rows():
    emu = FakeEmulator()
    install_map(emu, ROWS)
    grid = build_grid(emu)
    assert (grid.width, grid.height) == (4, 4)
    assert [["." if grid.walkable(x, y) else "#" for x in range(4)] for y in range(4)] == [list(r) for r in ROWS]


def test_astar_routes_around_walls_and_returns_none_when_boxed_in():
    emu = FakeEmulator()
    install_map(emu, ROWS)
    grid = build_grid(emu)
    path = astar(grid, (0, 0), (3, 3))
    assert path[-1] == (3, 3) and len(path) == 6
    assert astar(grid, (0, 0), (1, 1)) is None  # a wall
    assert astar(grid, (0, 0), (3, 3), blocked=frozenset({(0, 1), (1, 0)})) is None


def test_sprites_block_cells_and_reachable_edge_finds_the_nearest_exit():
    emu = FakeEmulator()
    install_map(emu, ROWS)
    grid = build_grid(emu)
    blocked = blocked_by_sprites((Sprite(1, 61, 0, 1),))
    assert blocked == {(0, 1)}
    assert reachable_edge(grid, (2, 2), "north", frozenset()) == (3, 0) or reachable_edge(grid, (2, 2), "north", frozenset()) == (0, 0)
    assert reachable_edge(grid, (0, 0), "north", frozenset()) == (0, 0)


def test_warps_connections_and_walkable_warps():
    emu = FakeEmulator()
    install_map(emu, ROWS, warps=[(1, 1, 0, 40), (3, 0, 1, 40)], connections={"north": 12, "south": 0})
    grid = build_grid(emu)
    warps = read_warps(emu.mem)
    assert warps == (Warp(1, 1, 0, 40), Warp(3, 0, 1, 40))
    assert walkable_warps(grid, warps, 40) == [Warp(3, 0, 1, 40)]
    assert read_connections(emu.mem) == {"north": 12, "south": 0}


def test_direction_to():
    assert direction_to((1, 1), (1, 0)) == "up" and direction_to((1, 1), (2, 1)) == "right"
```

Append to `tests/rom/test_world.py`:

```python
from jevplays.executor.world import astar, build_grid, read_connections, read_warps, walkable_warps


def test_full_map_grid_agrees_with_pyboys_window_everywhere(rom, state_path):
    for name in ("overworld", "route1", "battle_wild"):
        with Emulator(rom) as emu:
            emu.load(state_path(name))
            if emu.mem[ram.wIsInBattle]:
                continue
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
```

- [ ] **Step 2: Implement `world.py`**

```python
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
        return self.in_bounds(x, y) and self.cells[y][x] == 1


def read_warps(mem: ram.Memory) -> tuple[Warp, ...]:
    out = []
    for i in range(mem[ram.wNumberOfWarps]):
        y, x, warp_id, dest = ram.read_bytes(mem, ram.wWarpEntries + i * ram.WARP_ENTRY_SIZE, 4)
        out.append(Warp(x=x, y=y, warp_id=warp_id, dest=dest))
    return tuple(out)


def read_connections(mem: ram.Memory) -> dict[str, int]:
    flags = mem[ram.wMapConnections]
    return {d: mem[ram.CONNECTION_MAP_ADDRESSES[d]] for d, bit in ram.CONNECTION_BITS.items() if flags & (1 << bit)}


def build_grid(emu) -> MapGrid:
    mem = emu.mem
    width, height = mem[ram.wCurMapWidth], mem[ram.wCurMapHeight]
    stride = width + 2 * ram.MAP_BORDER_BLOCKS
    bank = mem[ram.wTilesetBank]
    blocks = ram.read_u16le(mem, ram.wTilesetBlocksPtr)
    collision = ram.read_u16le(mem, ram.wTilesetCollisionPtr)
    walkable = set()
    for i in range(0x180):
        tile = emu.rom(bank, collision + i)
        if tile == ram.COLLISION_END:
            break
        walkable.add(tile)
    grass = mem[ram.wGrassTile]
    if grass != 0xFF:
        walkable.add(grass)
    cells = [[0] * (width * 2) for _ in range(height * 2)]
    for by in range(height):
        for bx in range(width):
            block = mem[ram.wOverworldMap + (by + ram.MAP_BORDER_BLOCKS) * stride + (bx + ram.MAP_BORDER_BLOCKS)]
            base = blocks + block * 16
            for qy in range(2):
                for qx in range(2):
                    tile = emu.rom(bank, base + (qy * 2 + 1) * 4 + qx * 2)  # bottom-left tile of the quadrant
                    cells[by * 2 + qy][bx * 2 + qx] = 1 if tile in walkable else 0
    return MapGrid(cells)


def blocked_by_sprites(sprites: tuple[Sprite, ...]) -> set[tuple[int, int]]:
    return {(s.x, s.y) for s in sprites}


def direction_to(a: tuple[int, int], b: tuple[int, int]) -> str:
    delta = (b[0] - a[0], b[1] - a[1])
    for name, d in DIRECTIONS.items():
        if d == delta:
            return name
    raise ValueError(f"{a} and {b} are not adjacent")


def astar(grid: MapGrid, start: tuple[int, int], goal: tuple[int, int], blocked: frozenset = frozenset()) -> list[tuple[int, int]] | None:
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


def reachable_edge(grid: MapGrid, start: tuple[int, int], direction: str, blocked: frozenset) -> tuple[int, int] | None:
    """The nearest walkable cell on the map's edge in `direction` reachable from `start`."""
    def on_edge(c):
        return {"north": c[1] == 0, "south": c[1] == grid.height - 1, "west": c[0] == 0, "east": c[0] == grid.width - 1}[direction]

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
```

`tests.support.install_map(emu, rows, warps=(), connections=None)`:

```python
def install_map(emu, rows, warps=(), connections=None):
    """A synthetic map for the fake: '.' walkable, '#' wall; two blocks in the fake ROM."""
    bank, blocks_addr, collision_addr = 25, 0x4000, 0x5000
    m = emu.mem
    m[wTilesetBank] = bank
    m[wTilesetBlocksPtr] = blocks_addr & 0xFF
    m[wTilesetBlocksPtr + 1] = blocks_addr >> 8
    m[wTilesetCollisionPtr] = collision_addr & 0xFF
    m[wTilesetCollisionPtr + 1] = collision_addr >> 8
    m[wGrassTile] = 0xFF
    for i in range(16):
        m.rom[(bank, blocks_addr + i)] = 1       # block 0: every tile is 1 (walkable)
        m.rom[(bank, blocks_addr + 16 + i)] = 2  # block 1: every tile is 2 (wall)
    m.rom[(bank, collision_addr)] = 1
    m.rom[(bank, collision_addr + 1)] = COLLISION_END
    height, width = len(rows) // 2, len(rows[0]) // 2
    m[wCurMapWidth], m[wCurMapHeight] = width, height
    stride = width + 2 * MAP_BORDER_BLOCKS
    for by in range(-MAP_BORDER_BLOCKS, height + MAP_BORDER_BLOCKS):
        for bx in range(-MAP_BORDER_BLOCKS, width + MAP_BORDER_BLOCKS):
            inside = 0 <= bx < width and 0 <= by < height
            # a block is walkable only when all four of its cells are '.', which is what the fixtures use
            block = 0 if inside and all(rows[by * 2 + qy][bx * 2 + qx] == "." for qy in range(2) for qx in range(2)) else 1
            m[wOverworldMap + (by + MAP_BORDER_BLOCKS) * stride + (bx + MAP_BORDER_BLOCKS)] = block
    m[wNumberOfWarps] = len(warps)
    for i, (x, y, wid, dest) in enumerate(warps):
        m[wWarpEntries + 4 * i : wWarpEntries + 4 * i + 4] = [y, x, wid, dest]
    flags = 0
    for d, mid in (connections or {}).items():
        flags |= 1 << CONNECTION_BITS[d]
        m[CONNECTION_MAP_ADDRESSES[d]] = mid
    m[wMapConnections] = flags
```

The fixture rows in the tests are laid out so every 2x2 block is uniform (`ROWS` above: blocks (0,0)=`..`/`.#`? — no). Adjust `ROWS` to block-uniform rows so the synthetic map is faithful:

```python
ROWS = [
    "......",
    "......",
    "..##..",
    "..##..",
    "......",
    "......",
]
```

and update the test expectations accordingly: grid 6x6; `astar((0,0),(5,5))` has length 10; `astar((0,0),(2,2))` is None; the sprite test blocks `(0, 2)` etc. Keep the assertions consistent with a 6x6 map whose centre 2x2 block is wall.

- [ ] **Step 3: Run and commit**

Run: `uv run pytest tests/test_world.py -q` and `mise exec -- uv run pytest tests/rom/test_world.py -q`; expected all pass (the ROM grid test compares hundreds of cells).

```bash
git add src/jevplays/executor/world.py tests/support.py tests/test_world.py tests/rom/test_world.py
git commit -m "feat(executor): full-map walkability from RAM and ROM, warps, connections, and A*"
```

---

### Task 4: The map graph and the Navigator

**Files:**
- Create: `src/jevplays/executor/maps.py`
- Rewrite: `src/jevplays/executor/navigate.py` (keep `step`, `first_step`, `goto` for the state script and tests; add the Navigator)
- Test: `tests/test_maps.py`, `tests/test_navigator.py`, `tests/rom/test_navigate.py` (extend)

**Interfaces:**
- `maps.py`: map id constants (`PALLET_TOWN = 0, VIRIDIAN_CITY = 1, PEWTER_CITY = 2, ROUTE_1 = 12, ROUTE_2 = 13, ROUTE_22 = 33, REDS_HOUSE_1F = 37, REDS_HOUSE_2F = 38, BLUES_HOUSE = 39, OAKS_LAB = 40, VIRIDIAN_POKECENTER = 41, VIRIDIAN_MART = 42, VIRIDIAN_FOREST_NORTH_GATE = 47, VIRIDIAN_FOREST_SOUTH_GATE = 50, VIRIDIAN_FOREST = 51, PEWTER_GYM = 54, PEWTER_MART = 56, PEWTER_POKECENTER = 58`); nodes are strings: a map's name, except Route 2 which is `"route_2_south"` (y >= 25) and `"route_2_north"` (y < 25); `node_of(map_id, x, y) -> str`; `LINKS: dict[str, list[Link]]` where `Link(kind: "edge"|"warp", dest_node: str, direction: str | None, dest_map: int | None)`; `route(from_node, to_node) -> list[Link] | None` (BFS over LINKS). Links (from pokered's map data and the walks): `reds_house_2f` –warp 37→ `reds_house_1f` –warp 0 (door mat, exit)→ `pallet_town`; `pallet_town` –edge north→ `route_1`, –warp 40→ `oaks_lab`, –warp 37→ `reds_house_1f`; `oaks_lab` –warp exit→ `pallet_town`; `route_1` –edge north→ `viridian_city`, –edge south→ `pallet_town`; `viridian_city` –edge south→ `route_1`, –edge north→ `route_2_south`, –edge west→ `route_22`, –warp 41→ `viridian_pokecenter`, –warp 42→ `viridian_mart`; interiors –warp exit→ their city; `route_2_south` –edge south→ `viridian_city`, –warp 50→ `viridian_forest_south_gate`; `viridian_forest_south_gate` –warp 51→ `viridian_forest`, –warp exit→ `route_2_south`; `viridian_forest` –warp 47→ `viridian_forest_north_gate`, –warp 50→ `viridian_forest_south_gate`; `viridian_forest_north_gate` –warp 13→ `route_2_north`, –warp 51→ `viridian_forest`; `route_2_north` –edge north→ `pewter_city`, –warp 47→ `viridian_forest_north_gate`; `pewter_city` –edge south→ `route_2_north`, –warp 54→ `pewter_gym`, –warp 56→ `pewter_mart`, –warp 58→ `pewter_pokecenter`; interiors exit to `pewter_city`. An interior's exit warp has `dest_map = WARP_LAST_MAP` and the Navigator resolves it to any warp whose `dest` is `0xFF`.
- `navigate.py`: `@dataclass class Leg(kind: str, target: tuple[int,int] | None = None, direction: str | None = None, dest_map: int | None = None, face: str | None = None, label: str = "")` with kinds `walk` (to a tile), `edge` (walk to the nearest reachable edge in `direction` and step across), `warp` (walk onto a walkable warp to `dest_map`, stepping across if it sits on an edge), `face` (turn without moving); `class Navigator` with `plan(emu, state, legs: list[Leg])`, `busy: bool`, `current: Leg | None`, `step(emu, state) -> str` returning one of `"moving"`, `"leg_done"`, `"done"`, `"interrupted"`, `"stuck"`; `describe() -> str`; it re-reads the grid, sprites, and warps every step, treats sprite cells as blocked, blocks a cell after a failed step and re-plans, counts `STUCK_STEPS = 6` failed steps per leg and `STUCK_LEGS = 3` failed legs before returning `"stuck"`, and returns `"interrupted"` when after a failed step the mode is no longer OVERWORLD (a battle or a dialog started), leaving the plan intact so `step` can resume when the mode returns. Warp legs land by checking the map id changed; after a warp or edge crossing it ticks 60 frames.
- Keep the existing `goto(emu, x, y)` (window BFS) for `Scripts/make-states.py`; add `goto_far(emu, x, y, max_steps=400) -> bool` built on the Navigator for scripts.

- [ ] **Step 1: Failing tests**

```python
# tests/test_maps.py
from jevplays.executor.maps import LINKS, ROUTE_2, VIRIDIAN_CITY, node_of, route


def test_node_of_splits_route_2_by_row():
    assert node_of(ROUTE_2, 8, 71) == "route_2_south" and node_of(ROUTE_2, 3, 11) == "route_2_north"
    assert node_of(VIRIDIAN_CITY, 20, 34) == "viridian_city"


def test_route_from_bedroom_to_the_gym_goes_through_the_forest():
    legs = route("reds_house_2f", "pewter_gym")
    nodes = [link.dest_node for link in legs]
    assert nodes == ["reds_house_1f", "pallet_town", "route_1", "viridian_city", "route_2_south", "viridian_forest_south_gate", "viridian_forest", "viridian_forest_north_gate", "route_2_north", "pewter_city", "pewter_gym"]


def test_every_link_destination_is_a_known_node():
    for node, links in LINKS.items():
        for link in links:
            assert link.dest_node in LINKS, (node, link)
```

```python
# tests/test_navigator.py
from jevplays.emulator import ram
from jevplays.executor.navigate import Leg, Navigator
from jevplays.state.snapshot import snapshot
from tests.support import FakeEmulator, install_map

ROWS = ["......", "......", "..##..", "..##..", "......", "......"]


def walker():
    emu = FakeEmulator()
    install_map(emu, ROWS, warps=[(5, 0, 0, 99)], connections={"north": 7})
    emu.mem[ram.wCurMap] = 1
    emu.mem[ram.wXCoord] = 0
    emu.mem[ram.wYCoord] = 5
    return emu


def test_walk_leg_reaches_the_tile_one_step_per_call():
    emu = walker()
    nav = Navigator()
    nav.plan(emu, snapshot(emu), [Leg(kind="walk", target=(5, 5), label="corner")])
    results = []
    for _ in range(10):
        results.append(nav.step(emu, snapshot(emu)))
        if results[-1] == "done":
            break
    assert results[-1] == "done" and results.count("moving") == 4
    assert (emu.mem[ram.wXCoord], emu.mem[ram.wYCoord]) == (5, 5)
    assert not nav.busy


def test_sprite_in_the_way_is_routed_around():
    emu = walker()
    emu.set_sprites([(1, 61, 1, 5)])  # item ball on the direct path
    nav = Navigator()
    nav.plan(emu, snapshot(emu), [Leg(kind="walk", target=(2, 5))])
    for _ in range(10):
        if nav.step(emu, snapshot(emu)) == "done":
            break
    assert (emu.mem[ram.wXCoord], emu.mem[ram.wYCoord]) == (2, 5)
    assert "up" in emu.presses  # went around


def test_failed_steps_mark_the_cell_and_a_stuck_leg_gives_up():
    emu = walker()
    emu.step_effects = {}  # nothing ever moves
    nav = Navigator()
    nav.plan(emu, snapshot(emu), [Leg(kind="walk", target=(1, 5))])
    results = [nav.step(emu, snapshot(emu)) for _ in range(30)]
    assert "stuck" in results
    assert not nav.busy


def test_interruption_keeps_the_plan_for_later():
    emu = walker()
    nav = Navigator()
    nav.plan(emu, snapshot(emu), [Leg(kind="walk", target=(3, 5))])
    original = emu.press

    def press(button, **kw):
        emu.mem[ram.wIsInBattle] = 1  # a wild battle starts on the first step
        return original(button, **kw)

    emu.press = press
    assert nav.step(emu, snapshot(emu)) == "interrupted"
    assert nav.busy and nav.current.target == (3, 5)


def test_edge_leg_walks_to_the_north_edge_and_crosses():
    emu = walker()
    nav = Navigator()
    nav.plan(emu, snapshot(emu), [Leg(kind="edge", direction="north", dest_map=7)])
    for _ in range(20):
        r = nav.step(emu, snapshot(emu))
        if r in ("done", "stuck"):
            break
        if emu.mem[ram.wYCoord] == 0 and emu.presses[-1] == "up":
            emu.mem[ram.wCurMap] = 7  # the fake crosses when it steps off the edge
    assert r == "done" and emu.mem[ram.wCurMap] == 7
```

(The fake's `press` moves the player even off the top edge, so the test emulates the map change itself.) Extend `tests/rom/test_navigate.py`:

```python
from jevplays.executor.navigate import Leg, Navigator, goto_far
from jevplays.state.snapshot import snapshot


def test_navigator_crosses_route_1_into_viridian(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("route1"))
        nav = Navigator()
        nav.plan(emu, snapshot(emu), [Leg(kind="edge", direction="north", dest_map=1)])
        for _ in range(400):
            r = nav.step(emu, snapshot(emu))
            if r == "interrupted":
                # a wild battle: play it out with the first move, as the state script does
                from Scripts_helpers import finish_battle  # replaced below
            if r in ("done", "stuck"):
                break
        assert r == "done" and emu.mem[ram.wCurMap] == 1
```

Replace the interruption branch with a local helper copied from `Scripts/make-states.py`'s `finish_battle` (import it: `Scripts/make-states.py` is a script, so move `fight_menu_open`, `wait_for_fight_menu`, `play_one_turn`, `finish_battle` into `src/jevplays/executor/autoplay.py` in this task and import them from there in both the script and the test).

- [ ] **Step 2: Implement `maps.py`**

```python
"""The early game's map graph: how to get from one map to the next. Warps and edges are read from
the running game; this table only says which neighbour to take. Route 2 is two nodes because the
forest splits it and its map id is the same on both sides."""

from dataclasses import dataclass

from jevplays.emulator.ram import WARP_LAST_MAP

PALLET_TOWN, VIRIDIAN_CITY, PEWTER_CITY = 0, 1, 2
ROUTE_1, ROUTE_2, ROUTE_22 = 12, 13, 33
REDS_HOUSE_1F, REDS_HOUSE_2F, BLUES_HOUSE, OAKS_LAB = 37, 38, 39, 40
VIRIDIAN_POKECENTER, VIRIDIAN_MART = 41, 42
VIRIDIAN_FOREST_NORTH_GATE, VIRIDIAN_FOREST_SOUTH_GATE, VIRIDIAN_FOREST = 47, 50, 51
PEWTER_GYM, PEWTER_MART, PEWTER_POKECENTER = 54, 56, 58

NODE_NAMES = {
    PALLET_TOWN: "pallet_town", VIRIDIAN_CITY: "viridian_city", PEWTER_CITY: "pewter_city", ROUTE_1: "route_1",
    ROUTE_22: "route_22", REDS_HOUSE_1F: "reds_house_1f", REDS_HOUSE_2F: "reds_house_2f", BLUES_HOUSE: "blues_house",
    OAKS_LAB: "oaks_lab", VIRIDIAN_POKECENTER: "viridian_pokecenter", VIRIDIAN_MART: "viridian_mart",
    VIRIDIAN_FOREST_NORTH_GATE: "viridian_forest_north_gate", VIRIDIAN_FOREST_SOUTH_GATE: "viridian_forest_south_gate",
    VIRIDIAN_FOREST: "viridian_forest", PEWTER_GYM: "pewter_gym", PEWTER_MART: "pewter_mart", PEWTER_POKECENTER: "pewter_pokecenter",
}
ROUTE_2_SPLIT_ROW = 25


def node_of(map_id: int, x: int, y: int) -> str:
    if map_id == ROUTE_2:
        return "route_2_south" if y >= ROUTE_2_SPLIT_ROW else "route_2_north"
    return NODE_NAMES.get(map_id, f"map_{map_id}")


@dataclass(frozen=True)
class Link:
    kind: str  # "edge" | "warp"
    dest_node: str
    direction: str | None = None
    dest_map: int | None = None


def edge(direction, node):
    return Link("edge", node, direction=direction)


def warp(dest_map, node):
    return Link("warp", node, dest_map=dest_map)


EXIT = WARP_LAST_MAP

LINKS: dict[str, list[Link]] = {
    "reds_house_2f": [warp(REDS_HOUSE_1F, "reds_house_1f")],
    "reds_house_1f": [warp(EXIT, "pallet_town"), warp(REDS_HOUSE_2F, "reds_house_2f")],
    "blues_house": [warp(EXIT, "pallet_town")],
    "oaks_lab": [warp(EXIT, "pallet_town")],
    "pallet_town": [edge("north", "route_1"), warp(OAKS_LAB, "oaks_lab"), warp(REDS_HOUSE_1F, "reds_house_1f"), warp(BLUES_HOUSE, "blues_house")],
    "route_1": [edge("north", "viridian_city"), edge("south", "pallet_town")],
    "viridian_city": [edge("south", "route_1"), edge("north", "route_2_south"), edge("west", "route_22"),
                      warp(VIRIDIAN_POKECENTER, "viridian_pokecenter"), warp(VIRIDIAN_MART, "viridian_mart")],
    "route_22": [edge("east", "viridian_city")],
    "viridian_pokecenter": [warp(EXIT, "viridian_city")],
    "viridian_mart": [warp(EXIT, "viridian_city")],
    "route_2_south": [edge("south", "viridian_city"), warp(VIRIDIAN_FOREST_SOUTH_GATE, "viridian_forest_south_gate")],
    "viridian_forest_south_gate": [warp(VIRIDIAN_FOREST, "viridian_forest"), warp(EXIT, "route_2_south")],
    "viridian_forest": [warp(VIRIDIAN_FOREST_NORTH_GATE, "viridian_forest_north_gate"), warp(VIRIDIAN_FOREST_SOUTH_GATE, "viridian_forest_south_gate")],
    "viridian_forest_north_gate": [warp(EXIT, "route_2_north"), warp(VIRIDIAN_FOREST, "viridian_forest")],
    "route_2_north": [edge("north", "pewter_city"), warp(VIRIDIAN_FOREST_NORTH_GATE, "viridian_forest_north_gate")],
    "pewter_city": [edge("south", "route_2_north"), warp(PEWTER_GYM, "pewter_gym"), warp(PEWTER_MART, "pewter_mart"), warp(PEWTER_POKECENTER, "pewter_pokecenter")],
    "pewter_gym": [warp(EXIT, "pewter_city")],
    "pewter_mart": [warp(EXIT, "pewter_city")],
    "pewter_pokecenter": [warp(EXIT, "pewter_city")],
}


def route(from_node: str, to_node: str) -> list[Link] | None:
    """Breadth-first over LINKS; the list of links to follow, or None."""
    from collections import deque

    if from_node == to_node:
        return []
    came: dict[str, tuple[str, Link] | None] = {from_node: None}
    queue = deque([from_node])
    while queue:
        node = queue.popleft()
        for link in LINKS.get(node, []):
            if link.dest_node in came:
                continue
            came[link.dest_node] = (node, link)
            if link.dest_node == to_node:
                path = []
                cur = to_node
                while came[cur] is not None:
                    prev, l = came[cur]
                    path.append(l)
                    cur = prev
                return path[::-1]
            queue.append(link.dest_node)
    return None
```

Note the north-gate exit lands on the *north* side of Route 2 (verified: (3, 11)), and the south gate's exit on the south side, which is why the two gates map to different Route 2 nodes.

- [ ] **Step 3: Implement the Navigator**

```python
# in src/jevplays/executor/navigate.py (keep first_step/step/goto; add the following)
"""Multi-map navigation. A plan is a list of legs; each call to step() moves one tile (or crosses
one edge/warp), re-reading the map, sprites, and warps first so NPCs that wander into the way are
routed around. Interruptions (a battle, a dialog) return "interrupted" with the plan intact;
the loop hands control to the brain and calls step() again when the overworld is back."""

from dataclasses import dataclass, field

from jevplays.emulator import ram
from jevplays.executor import world
from jevplays.state.modes import Mode

STUCK_STEPS = 6
STUCK_LEGS = 3


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

    @property
    def busy(self) -> bool:
        return self.index < len(self.legs)

    @property
    def current(self) -> Leg | None:
        return self.legs[self.index] if self.busy else None

    def plan(self, emu, state, legs: list[Leg]) -> None:
        self.legs, self.index, self.failed_legs = list(legs), 0, 0
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
        if leg.kind in ("edge", "warp") and mem[ram.wCurMap] != self.start_map:
            emu.tick(60)
            return self._advance(emu)
        grid = world.build_grid(emu)
        blocked = frozenset(world.blocked_by_sprites(state.sprites) | self.blocked)
        target = self._target(leg, grid, here, mem, blocked)
        if target is None:
            return self._fail_leg(emu)
        if here == target:
            if leg.kind == "walk":
                return self._advance(emu)
            direction = world.EDGE_DIRECTION[leg.direction] if leg.kind == "edge" else self._off_edge(target, grid)
            if direction is None:  # a warp tile inside the map: standing on it should have warped already
                return self._fail_leg(emu)
            moved = step(emu, direction, hold=24, settle=40)
            emu.tick(60)
            if mem[ram.wCurMap] != self.start_map:
                return self._advance(emu)
            return self._fail_step(emu, state, None)
        path = world.astar(grid, here, target, blocked)
        if not path:
            return self._fail_leg(emu)
        nxt = path[0]
        if step(emu, world.direction_to(here, nxt)):
            self.blocked.clear()
            self.failed_steps = 0
            if leg.kind in ("edge", "warp") and mem[ram.wCurMap] != self.start_map:
                emu.tick(60)
                return self._advance(emu)
            return "moving"
        return self._fail_step(emu, state, nxt)

    def _target(self, leg, grid, here, mem, blocked):
        if leg.kind == "walk":
            return leg.target
        if leg.kind == "edge":
            return world.reachable_edge(grid, here, leg.direction, blocked)
        if leg.kind == "warp":
            candidates = world.walkable_warps(grid, world.read_warps(mem), leg.dest_map)
            candidates.sort(key=lambda w: abs(w.x - here[0]) + abs(w.y - here[1]))
            return (candidates[0].x, candidates[0].y) if candidates else None
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
        if r in ("stuck", "interrupted"):
            return False
    return False
```

Move `fight_menu_open`, `wait_for_fight_menu`, `play_one_turn`, `finish_battle` from `Scripts/make-states.py` into `src/jevplays/executor/autoplay.py` (module docstring: "Play a battle with the first move, for scripts and tests that need to get past a fight without the brain") and import them back into the script; the ROM test's interruption branch calls `finish_battle(emu)` then continues.

- [ ] **Step 4: Run and commit**

Run: `uv run pytest tests/test_maps.py tests/test_navigator.py tests/test_navigate.py -q` and `mise exec -- uv run pytest tests/rom/test_navigate.py -q` and `mise run states` (to prove the script still works after the autoplay move; it rewrites all eight states, which is fine).

```bash
git add src/jevplays/executor/maps.py src/jevplays/executor/navigate.py src/jevplays/executor/autoplay.py Scripts/make-states.py tests/test_maps.py tests/test_navigator.py tests/rom/test_navigate.py
git commit -m "feat(executor): map graph and a multi-map navigator with NPC-aware A* and stuck detection"
```

---

### Task 5: Talking and the scripted Mart and Center macros

**Files:**
- Create: `src/jevplays/executor/talk.py`, `src/jevplays/executor/shop.py`
- Test: `tests/test_talk.py`, `tests/rom/test_shop.py` (uses states from Task 9; write the tests now, they skip until the states exist)

**Interfaces:**
- `talk.py`: `find_sprite(state, picture: int | None = None, slot: int | None = None) -> Sprite | None`; `adjacent_tile(sprite, face) -> tuple[int, int]` (the tile the player stands on to face the sprite: `face="up"` means the player stands at `(x, y+1)`); `talk_to(emu, x, y, face, *, answer=None, patience=60) -> bool` (walks with `goto_far`, faces, presses A, runs `skip_dialog(emu, answer=answer, patience=patience)`; True when a dialog happened).
- `shop.py`: `NURSE_TILE = (3, 3)`, `NURSE_FACE = "up"`, `CLERK_TILE = (2, 5)`, `CLERK_FACE = "left"`; `heal_at_nurse(emu) -> bool` (talk, wait for a menu whose cursor label starts with `HEAL`, press A, skip the rest; True when the party's first member has full HP afterwards); `buy_pokeballs(emu, count: int) -> int` (talk to the clerk, wait for the `BUY` cursor, A, wait for a cursor label starting with `POKé BALL` (press `down` up to 6 times to find it), A, wait for a `×0` quantity box (any row whose text contains `×0`), press `up` `count - 1` times, A, answer YES, skip the rest, press B twice; returns the number of Poké Balls now in the bag). Both use `rows_of(emu.tilemap())`, `cursor_label`, `yes_no_open`, `answer_prompt`, and a bounded `wait_for(emu, predicate, frames)` helper defined in `shop.py`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_talk.py
from jevplays.executor.talk import adjacent_tile, find_sprite
from jevplays.state.snapshot import Sprite, snapshot
from tests.support import FakeEmulator


def test_find_sprite_by_picture_and_slot():
    emu = FakeEmulator()
    emu.set_sprites([(1, 41, 3, 1), (5, 3, 5, 2)])
    state = snapshot(emu)
    assert find_sprite(state, picture=3) == Sprite(5, 3, 5, 2)
    assert find_sprite(state, slot=1) == Sprite(1, 41, 3, 1)
    assert find_sprite(state, picture=99) is None


def test_adjacent_tile_is_where_the_player_stands_to_face_the_sprite():
    oak = Sprite(5, 3, 5, 2)
    assert adjacent_tile(oak, "up") == (5, 3)
    assert adjacent_tile(oak, "left") == (6, 2)
```

```python
# tests/rom/test_shop.py
from jevplays.emulator import ram
from jevplays.emulator.pyboy import Emulator
from jevplays.executor.shop import buy_pokeballs, heal_at_nurse
from jevplays.state.snapshot import snapshot


def test_heal_at_the_viridian_nurse(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("viridian_center"))
        assert heal_at_nurse(emu)
        s = snapshot(emu)
        assert s.party[0].hp == s.party[0].max_hp


def test_buy_three_pokeballs(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("mart_dex"))
        before = snapshot(emu).money
        assert buy_pokeballs(emu, 3) >= 3
        s = snapshot(emu)
        assert any(item.name == "POKE BALL" and item.quantity >= 3 for item in s.bag)
        assert s.money == before - 600
```

- [ ] **Step 2: Implement**

`talk.py`:

```python
"""Walk up to a sprite, face it, press A, and read through what it says."""

from jevplays.executor.dialog import skip_dialog
from jevplays.executor.navigate import goto_far
from jevplays.state.snapshot import GameState, Sprite

FACING_OFFSET = {"up": (0, 1), "down": (0, -1), "left": (1, 0), "right": (-1, 0)}
"""Where the player stands relative to the sprite for each facing direction."""


def find_sprite(state: GameState, picture: int | None = None, slot: int | None = None) -> Sprite | None:
    for s in state.sprites:
        if (picture is None or s.picture == picture) and (slot is None or s.slot == slot):
            return s
    return None


def adjacent_tile(sprite: Sprite, face: str) -> tuple[int, int]:
    dx, dy = FACING_OFFSET[face]
    return sprite.x + dx, sprite.y + dy


def talk_to(emu, x: int, y: int, face: str, *, answer=None, patience: int = 60) -> bool:
    if not goto_far(emu, x, y):
        return False
    emu.press(face, hold=4, settle=12)
    emu.press("a", settle=60)
    return skip_dialog(emu, answer=answer, patience=patience) or True
```

`shop.py`:

```python
"""The two scripted counters: the nurse and the Mart clerk. Their screens are mechanical (a HEAL
menu, a quantity box), so code drives them; Jev decides whether to go there, not what to press."""

from jevplays.emulator import ram
from jevplays.executor.dialog import answer_prompt, cursor_label, skip_dialog, yes_no_open
from jevplays.executor.talk import talk_to
from jevplays.state.snapshot import rows_of, snapshot

NURSE_TILE, NURSE_FACE = (3, 3), "up"
CLERK_TILE, CLERK_FACE = (2, 5), "left"


def wait_for(emu, predicate, frames: int = 900) -> bool:
    for _ in range(0, frames, 10):
        rows = rows_of(emu.tilemap())
        if predicate(rows):
            return True
        if rows[16][18] == "▼":
            emu.press("a", settle=30)
        else:
            emu.tick(10)
    return False


def _label_starts(rows, prefix: str) -> bool:
    label = cursor_label(rows)
    return label is not None and label.startswith(prefix)


def heal_at_nurse(emu) -> bool:
    talk_to(emu, *NURSE_TILE, NURSE_FACE, patience=0)
    if not wait_for(emu, lambda rows: _label_starts(rows, "HEAL")):
        return False
    emu.press("a", settle=60)
    skip_dialog(emu, patience=60)
    s = snapshot(emu)
    return bool(s.party) and s.party[0].hp == s.party[0].max_hp


def buy_pokeballs(emu, count: int) -> int:
    talk_to(emu, *CLERK_TILE, CLERK_FACE, patience=0)
    if not wait_for(emu, lambda rows: _label_starts(rows, "BUY")):
        return _balls(emu)
    emu.press("a", settle=60)
    if not wait_for(emu, lambda rows: cursor_label(rows) is not None and "BALL" in "".join("".join(r) for r in rows)):
        return _balls(emu)
    for _ in range(6):
        if _label_starts(rows_of(emu.tilemap()), "POKé BALL"):
            break
        emu.press("down", settle=16)
    emu.press("a", settle=60)
    if not wait_for(emu, lambda rows: any("×0" in "".join(r) for r in rows)):
        return _balls(emu)
    for _ in range(max(0, count - 1)):
        emu.press("up", settle=16)
    emu.press("a", settle=60)
    if wait_for(emu, yes_no_open, frames=300):
        answer_prompt(emu, True)
    skip_dialog(emu, patience=40)
    emu.press("b", settle=30)
    emu.press("b", settle=30)
    emu.press("b", settle=30)
    return _balls(emu)


def _balls(emu) -> int:
    return sum(item.quantity for item in snapshot(emu).bag if item.name == "POKE BALL")
```

- [ ] **Step 3: Run and commit**

Run: `uv run pytest tests/test_talk.py -q` (passes); `mise exec -- uv run pytest tests/rom/test_shop.py -q` skips until Task 9 writes the states (expected `2 skipped`).

```bash
git add src/jevplays/executor/talk.py src/jevplays/executor/shop.py tests/test_talk.py tests/rom/test_shop.py
git commit -m "feat(executor): talk to sprites, heal at the nurse, and buy Poké Balls"
```

---

### Task 6: The goal table

**Files:**
- Create: `src/jevplays/executor/goals.py`
- Test: `tests/test_goals.py`

**Interfaces:**
- `@dataclass(frozen=True) class Goal(id: str, description: str, available: Callable[[GameState], bool], done: Callable[[GameState], bool], legs: Callable[[GameState], list[Leg]], after: str | None = None)` where `after` names a scripted macro to run when the legs finish: `"talk_oak"`, `"talk_old_man"`, `"choose_charmander"`, `"heal"`, `"buy_pokeballs"`, `"talk_brock"`, `"wander"`, or `None`; `GOALS: list[Goal]`; `available_goals(state) -> list[Goal]`; `goal_by_id(id) -> Goal`; `legs_to(state, node: str) -> list[Leg]` (converts `maps.route(node_of(state), node)` into legs); `ALWAYS = ("heal_at_center", "train_nearby")`.
- Goals, in table order (availability uses `state.flags`, `state.party`, `state.bag`, `state.money`, `state.map_id`):
  1. `get_starter`: available always until done; done when `"got_starter"` in flags; legs to `pallet_town` then walk to (10, 1) (Oak appears; the cutscene is dialog the loop skips; the lab and the ball are then handled by `after="choose_charmander"` when the map is the lab: walk to (6, 4), face up, A, answer the choose prompt YES and any nickname prompt NO). Since the cutscene moves the player into the lab, the goal's legs are re-planned each time it becomes active: in Pallet, walk to (10, 1); in the lab, the ball.
  2. `deliver_parcel`: available when `got_starter` and not `got_pokedex`; done when `got_pokedex`; legs: if `got_oaks_parcel` not in flags → to `viridian_mart` (entering triggers the clerk); else → to `oaks_lab` then `after="talk_oak"` (talk from (5, 3) facing up).
  3. `wake_old_man`: available when `oak_got_parcel` in flags and the map is Viridian and a sprite with picture 72 is present; done when no sprite 72 is on the map (he has moved); legs: to `viridian_city`, walk to (18, 10), `after="talk_old_man"` (face up, A, answer YES).
  4. `buy_pokeballs`: available when `got_pokedex` and money >= 600 and Poké Balls in bag < 3; done when Poké Balls >= 3 or money < 200; legs to `viridian_mart`, `after="buy_pokeballs"` (count = min(5, money // 200)).
  5. `train_to_level_12`: available when `got_pokedex` and the lead's level < 12; done when level >= 12; legs to `route_2_south` (grass just north of Viridian) then `after="wander"` (walk up/down inside the grass patch until a battle interrupts; the loop's battle branch fights it).
  6. `cross_viridian_forest`: available when lead level >= 12 and map node is not in `{"pewter_city", "pewter_gym", ...}` and not `beat_brock`; done when the node is `pewter_city` or beyond; legs to `pewter_city`.
  7. `beat_brock`: available when node in Pewter and lead level >= 12 and not `beat_brock`; done when `beat_brock`; legs to `pewter_gym` then walk to (4, 2), `after="talk_brock"` (face up, A; the battle follows).
  8. `heal_at_center` (always available when a Pokémon Center is known on the route and the lead's HP < 50%): legs to the nearest known center node (`viridian_pokecenter` or `pewter_pokecenter` by route length), `after="heal"`; done when the lead's HP == max.
  9. `train_nearby` (always): wander on the current map if it has grass (Route 1, Route 2, forest); done never (it yields when a battle interrupts).

- [ ] **Step 1: Failing tests**

```python
# tests/test_goals.py
from jevplays.executor.goals import GOALS, available_goals, goal_by_id, legs_to
from jevplays.executor.maps import OAKS_LAB, PALLET_TOWN, ROUTE_1, VIRIDIAN_CITY
from jevplays.state.modes import Mode
from jevplays.state.snapshot import BagItem, GameState, Mon, Move, Sprite

CHAR = Mon(name="CHARMANDER", nickname="CHARMANDER", level=5, types=("Fire",), hp=19, max_hp=19, status="none", moves=(Move("SCRATCH", "Normal", 40, 35, 35),))


def state(map_id=PALLET_TOWN, x=5, y=6, flags=(), party=(CHAR,), bag=(), money=3000, sprites=()):
    return GameState(mode=Mode.OVERWORLD, map_id=map_id, map="x", tile=(x, y), player_name="RED", party_count=len(party),
                     badges=0, money=money, bag_count=len(bag), bag=tuple(bag), in_battle=False, text="", menu_items=(), cursor=None,
                     party=tuple(party), active=None, active_slot=None, enemy=None, battle=None, flags=frozenset(flags),
                     sprites=tuple(sprites), map_size=(20, 18))


def test_fresh_game_offers_only_the_starter_and_the_always_goals():
    ids = [g.id for g in available_goals(state(party=()))]
    assert ids[0] == "get_starter" and "deliver_parcel" not in ids


def test_after_the_starter_the_parcel_is_next_and_goes_to_the_mart_first():
    s = state(flags={"got_starter"})
    ids = [g.id for g in available_goals(s)]
    assert "deliver_parcel" in ids and "get_starter" not in ids
    legs = goal_by_id("deliver_parcel").legs(s)
    assert legs[-1].kind == "warp" and legs[-1].dest_map == 42


def test_with_the_parcel_in_hand_the_goal_returns_to_oak():
    s = state(map_id=VIRIDIAN_CITY, x=29, y=20, flags={"got_starter", "got_oaks_parcel"}, bag=(BagItem("OAKS PARCEL", 1),))
    legs = goal_by_id("deliver_parcel").legs(s)
    assert legs[-1].dest_map == OAKS_LAB and goal_by_id("deliver_parcel").after == "talk_oak"


def test_old_man_goal_needs_the_sprite_and_the_delivered_parcel():
    s = state(map_id=VIRIDIAN_CITY, x=29, y=20, flags={"got_starter", "got_pokedex", "oak_got_parcel"}, sprites=(Sprite(5, 72, 18, 9),))
    assert "wake_old_man" in [g.id for g in available_goals(s)]
    assert goal_by_id("wake_old_man").done(state(map_id=VIRIDIAN_CITY, flags={"oak_got_parcel"}, sprites=()))


def test_buying_and_training_gates():
    rich = state(flags={"got_starter", "got_pokedex"}, money=3000)
    assert "buy_pokeballs" in [g.id for g in available_goals(rich)]
    stocked = state(flags={"got_starter", "got_pokedex"}, bag=(BagItem("POKE BALL", 5),))
    assert "buy_pokeballs" not in [g.id for g in available_goals(stocked)]
    assert "train_to_level_12" in [g.id for g in available_goals(stocked)]
    strong = state(flags={"got_starter", "got_pokedex"}, party=(Mon(**{**CHAR.__dict__, "level": 12}),))
    assert "train_to_level_12" not in [g.id for g in available_goals(strong)]
    assert "cross_viridian_forest" in [g.id for g in available_goals(strong)]


def test_heal_goal_appears_when_the_lead_is_hurt_and_routes_to_a_center():
    hurt = state(map_id=ROUTE_1, x=10, y=20, party=(Mon(**{**CHAR.__dict__, "hp": 5}),), flags={"got_starter"})
    goal = next(g for g in available_goals(hurt) if g.id == "heal_at_center")
    legs = goal.legs(hurt)
    assert legs[-1].dest_map == 41 and goal.after == "heal"


def test_legs_to_builds_edge_and_warp_legs_from_the_route():
    legs = legs_to(state(map_id=PALLET_TOWN, x=5, y=6), "viridian_mart")
    assert [leg.kind for leg in legs] == ["edge", "edge", "warp"]
    assert legs[0].direction == "north" and legs[-1].dest_map == 42
```

- [ ] **Step 2: Implement `goals.py`** with the table above. Helper details: `lead(state)` is `state.party[0]` when present; `balls(state)` sums `POKE BALL` quantities; `node(state)` is `maps.node_of(state.map_id, *state.tile)`; `legs_to(state, node)` maps each `Link` to `Leg(kind="edge", direction=..., dest_map=None)` or `Leg(kind="warp", dest_map=link.dest_map)`, labelling each leg `"to <dest_node>"`; the Oak lab leg list for `deliver_parcel` appends `Leg(kind="walk", target=(5, 3), label="in front of Oak")`; `wake_old_man` appends `Leg(kind="walk", target=(18, 10))`; `beat_brock` appends `Leg(kind="walk", target=(4, 2))`; `get_starter` returns `[Leg(kind="walk", target=(10, 1), label="the edge of Pallet Town")]` when the node is `pallet_town`, `[Leg(kind="walk", target=(6, 4), label="Charmander's ball")]` when the node is `oaks_lab`, and `legs_to(state, "pallet_town")` otherwise; `heal_at_center` picks the center node with the shorter `maps.route`. Descriptions are one sentence each and are what Jev reads (e.g. "Get a starter Pokémon from Professor Oak", "Deliver Oak's Parcel: fetch it from the Viridian Mart, then bring it to Oak", "Wake the old man who is blocking the road north out of Viridian City", "Buy Poké Balls at the Viridian Mart", "Train on Route 2 until CHARMANDER reaches level 12", "Cross Viridian Forest to Pewter City", "Challenge Brock at the Pewter Gym", "Heal at the nearest Pokémon Center", "Train in the grass nearby").

- [ ] **Step 3: Run and commit**

Run: `uv run pytest tests/test_goals.py -q`; expected `7 passed`.

```bash
git add src/jevplays/executor/goals.py tests/test_goals.py
git commit -m "feat(executor): the early-game goal table through Brock"
```

---

### Task 7: Goal, prompt, and menu decision points in the brain

**Files:**
- Create: `src/jevplays/brain/goal.py`, `src/jevplays/brain/prompt.py`
- Modify: `src/jevplays/brain/policy.py`, `src/jevplays/brain/decision.py` (a generic `Action` for these kinds: `GoalAction(goal_id)`, `PromptAction(yes: bool)`, `MenuAction(item: str | None)` — `None` means close)
- Test: `tests/test_goal_brain.py`, `tests/test_prompt_brain.py`

**Interfaces:**
- `policy.py` adds `HEAL_FIRST_THRESHOLD = 0.7`, `PROMPT_YES_THRESHOLD = 0.5`, `MENU_CLOSE_THRESHOLD = 0.6`, `NEVER_NICKNAME = True`; `choose_goal(answers, available_ids) -> tuple[str, list[str]]` (heal first if `needs_heal` > threshold and `heal_at_center` is available, else the `goal` choice); `choose_prompt(answers, text) -> tuple[bool, list[str]]` (NO without asking when `NEVER_NICKNAME` and "nickname" in text lower; else `prompt` noul > threshold); `choose_menu(answers) -> tuple[str | None, list[str]]` (close if `close` > threshold else `menu` choice).
- `brain/goal.py`: `goal_state(state, goals) -> dict` (map name, party as `[{name, level, hp bucket}]`, badges, money bucket (`broke < 500, some < 2000, comfortable < 10000, rich`), bag summary as names with quantities bucketed (`none/few/plenty`), the available goals as `{id: description}`), `goal_questions(sj) -> dict` (`goal` Choice over ids with descriptions as criteria; `needs_heal` Noul with criteria), `decide_goal(sj, questions, response, available_ids, *, model, input_tokens, latency_ms) -> Decision` (kind `goal`, action text `"pursue <id>"`, `action_value=GoalAction`).
- `brain/prompt.py`: `prompt_state(state, goal_description) -> dict` (`{"prompt": text, "goal": description}`), `prompt_questions(sj)`, `decide_prompt(...)` (kind `prompt`, action `"answer YES"`/`"answer NO"`); `menu_state(state, goal_description) -> dict` (`{"menu_items": [...], "screen_text": text, "goal": ...}`), `menu_questions(sj)` (`menu` Choice over the items; `close` Noul), `decide_menu(...)` (kind `menu`, action `"select <item>"` or `"close the menu"`). The `NEVER_NICKNAME` guard is applied inside `decide_prompt` before consulting the answer and marks the decision `fallback=False` with `fallback_reason="policy: never nickname"` recorded in `state_summary["policy_note"]`.
- Number-leak tests for both state builders (levels allowed; money and HP as words only).

- [ ] **Step 1: Failing tests** — mirror `tests/test_battle_brain.py`'s style: build states with the Task 6 `state()` helper (move it to `tests/support.py` as `overworld_state(...)`), assert the JSON shapes, the question inclusion rules (`needs_heal` always; `goal` lists exactly the available ids), the policy order (heal-first only when available and above threshold), the nickname guard, the menu close rule, and `Decision` fields. Include a regex number-leak assertion for `goal_state` and `menu_state` allowing only levels.

- [ ] **Step 2: Implement**, following `brain/battle.py`'s structure (`_question_record`, `_answer_record`, `applied` marks, `Decision` with `action_value`). Money bucket and bag buckets live in `brain/buckets.py` (`money_bucket(money)`, `quantity_bucket(n)`: `none` 0, `few` <= 3, `plenty`).

- [ ] **Step 3: Run and commit**

Run: `uv run pytest tests/test_goal_brain.py tests/test_prompt_brain.py tests/test_buckets.py -q`.

```bash
git add src/jevplays/brain tests/support.py tests/test_goal_brain.py tests/test_prompt_brain.py tests/test_buckets.py
git commit -m "feat(brain): goal, prompt, and menu decision points"
```

---

### Task 8: The loop plays the overworld

**Files:**
- Modify: `src/jevplays/loop.py`, `src/jevplays/cli.py`, `src/jevplays/dashboard/events.py`
- Test: `tests/test_loop.py`, `tests/rom/test_loop_overworld.py`

**Interfaces:**
- `Loop` gains `navigator: Navigator`, `goal: Goal | None`, `goal_started_at: float`, and per-mode branches: OVERWORLD → if a goal is active and its `done(state)` → clear it and publish `status_event("running", f"goal done: {id}")`; elif the navigator is busy → `navigator.step`; on `"done"` run the goal's `after` macro (Task 5 macros; `"wander"` takes one grass step alternating up/down; `"choose_charmander"` does the ball interaction with `skip_dialog(answer=lambda text: "nickname" not in text.lower())`); on `"stuck"` mark the goal blocked for this run (`self.blocked_goals: set[str]`) and clear it; elif no goal → ask the brain (`decide_goal` over `available_goals(state)` minus blocked ones; without a brain, take the first available goal), set `self.goal`, plan `goal.legs(state)`; PROMPT → `decide_prompt` then `answer_prompt` (without a brain: YES unless nickname); MENU → `decide_menu` then press: find the item's row via `cursor_label` and `down` presses (bounded by the item count), A; or B to close; BATTLE_MENU as before; DIALOG/BATTLE_WAIT/TRANSITION as before. Every decision goes through `self.decisions` and `decision_event`. `status_event("running", navigator.describe())` on each leg change. Re-plan the active goal's legs when the map changes and the navigator is idle (the starter cutscene moves the player).
- `cli.py`: `--goal` becomes the free-text goal for battles only (rename to `--battle-goal`), and `run` prints the goal id whenever it changes.
- `events.py`: `status_event` unchanged; `state_event` unchanged (the page reads `state.flags` in Task 10).

- [ ] **Step 1: Failing tests** in `tests/test_loop.py` using `FakeEmulator` + `install_map` + `FakeBrain` returning canned goal/prompt/menu responses: (a) an overworld state with no goal asks the brain once, sets `loop.goal.id`, and starts moving (presses contain a direction); (b) a PROMPT state routes through `decide_prompt` and presses `a` (YES) or `down, a` (NO); (c) a nickname prompt never asks the brain and presses `down, a`; (d) a MENU state selects the chosen item; (e) a stuck navigator blocks the goal and the next iteration asks the brain again. ROM test `tests/rom/test_loop_overworld.py`: from `states/route1.state` with no brain and `max_iterations=600`, the loop's first goal is `deliver_parcel` and the player ends on a different map than Route 1 (it walked into Viridian or a battle interrupted and the loop fought it; either way `emu.mem[ram.wCurMap] != 12` or `loop.decisions` is non-empty).

- [ ] **Step 2: Implement** per the interface. Keep `_battle_turn` as is. Factor the decision plumbing (`ask`, `record`, `publish`) into one `_decide(kind, sj, questions, decoder)` coroutine so the three new branches stay short.

- [ ] **Step 3: Run it for real**

`mise exec -- uv run jevplays run --state states/route1.state --port 8765`: watch the status pill walk through "to viridian_city", a battle or two, "to viridian_mart", the clerk, "to oaks_lab", and "goal done: deliver_parcel"; stop it. Record the sequence of goal ids and statuses from the websocket in the report.

- [ ] **Step 4: Commit**

```bash
git add src/jevplays/loop.py src/jevplays/cli.py src/jevplays/dashboard/events.py tests/test_loop.py tests/rom/test_loop_overworld.py
git commit -m "feat(loop): goals, navigation, prompts, and menus in the overworld"
```

---

### Task 9: States and fixtures for the new decision points

**Files:**
- Modify: `Scripts/make-states.py`, `Scripts/record-fixtures.py`
- Test: `tests/rom/test_snapshot.py`, `tests/test_fixtures.py`

**Interfaces:**
- New states, all produced by continuing the milestone 2 route with the navigator: `pallet.state` (outside the house, before the starter), `viridian.state` (arrived from Route 1 after the rival battle), `viridian_center.state` (inside the Center, lead damaged by Route 1 fights or at least not full: if full, this state is still saved and the heal test asserts equality), `mart_parcel.state` (inside the Mart right after the clerk), `dex.state` (in the lab after the Pokédex), `mart_dex.state` (inside the Mart after the Pokédex, before buying), `viridian_oldman.state` (in Viridian after the Pokédex, old man still asleep). The script uses `goto_far`, `Navigator`, `finish_battle` from `executor/autoplay`, and `talk_to`.
- Fixtures: `goal_route1.json` (route1 state, available goals: deliver_parcel + always goals), `goal_hurt.json` (a route1-derived state with the lead below half HP if reachable, else skip), `prompt_starter.json` (the choose-Charmander prompt: derive from the lab route by saving `prompt_starter.state` at the YES/NO box), `menu_start.json` (the START menu from `menu.state`). Tests replay them through the three decoders and assert sensible actions (deliver_parcel chosen or heal when hurt; YES to the starter prompt; a menu item chosen).

- [ ] **Steps:** extend the script (guarded by `--only` groups `story` and `battle`), run `mise run states` and `mise exec -- uv run Scripts/record-fixtures.py`, extend the ROM mode test with the new states (`viridian` OVERWORLD, `viridian_center` OVERWORLD, `mart_parcel` OVERWORLD, `prompt_starter` PROMPT), run `tests/rom/test_shop.py` (now unskipped), commit.

```bash
git commit -m "feat(states): story states through the Pokédex and recorded goal, prompt, and menu responses"
```

---

### Task 10: Dashboard readout for goals and navigation

**Files:**
- Modify: `src/jevplays/dashboard/static/{index.html,app.js,styles.css}`

The goal line shows the active goal's description (from the `goal` decision's `state_summary`) and a second line with the navigator's leg from the latest `status`; decision-log entries prefix the kind (`goal:`, `prompt:`, `menu:`, `battle:`); the collapsed State block lists `flags`. No new tests beyond `tests/test_server.py`; the controller does the browser check.

```bash
git commit -m "feat(dashboard): show the active goal, the navigator's leg, and story flags"
```

---

### Task 11: Spec amendments, docs, full check, PR

- Spec section 9: replace the waypoint paragraph with the full-map approach (grid from `wOverworldMap` + ROM tables, sprites as blockers, warps and connections from RAM, a static link table for the route, stuck detection as before). Section 8.3: note the scripted counters. Section 14: milestone 3 becomes 3a (this) and 3b (logging, resume, replay, stream layout). Section 6: `GameState` gains `flags`, `sprites`, `map_size`.
- README: status milestone 3a; Quick start's quickest demo: `mise exec -- uv run jevplays run --state states/route1.state`. CLAUDE.md: "story facts live in `executor/goals.py`; RAM facts in `ram.py`; never hand-write map waypoints, read the map".
- Checks: `mise run check`; `env -u JEVPLAYS_ROM .venv/bin/python -m pytest -q`; `mise exec -- uv run pytest -q`; the tracked-files grep.
- Push and PR: title "Milestone 3a: navigation and goals", body listing what landed, the live run's goal sequence, and deferred items.

---

## Self-review

**Spec coverage:** 8.2 goal decision point (Task 7, 8); 8.3 prompts and menus (Task 7, 8) with the scripted counters recorded as a deviation (Task 11); 9 navigation, stuck detection, battle interruption/resume (Tasks 3, 4, 8) with the full-map deviation recorded; 6 GameState growth (Task 2); 12 error handling (Task 8 reuses the API backoff; stuck goals are marked and re-asked); 13 tests: unit on fakes with a synthetic map, ROM on saved states, fixtures recorded once (Task 9); 14 milestone 3 split into 3a/3b (Task 11).

**Placeholder scan:** Tasks 7, 9, and 10 give interfaces and behaviors rather than full listings because they mirror milestone 2's `battle.py`, `make-states.py`, and `app.js` patterns line for line; each names the exact functions, fields, thresholds, states, and assertions. No "TBD".

**Type consistency:** `Sprite` (Task 2) consumed by `blocked_by_sprites`, `find_sprite`, and the goal table; `Leg`/`Navigator` (Task 4) consumed by `goals.py` and the loop; `Warp` and `walkable_warps` (Task 3) consumed by the navigator; `flags_set` (Task 1) feeds `GameState.flags` (Task 2) read by `goals.py` (Task 6); `GoalAction/PromptAction/MenuAction` (Task 7) consumed by the loop (Task 8); `finish_battle` moves to `executor/autoplay.py` in Task 4 and is imported by the script and the ROM tests.
