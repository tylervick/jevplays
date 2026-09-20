# Milestone 2: Battles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jev fights. At every battle command menu the loop sends TypeSafe one request with the battle questions, applies the policy, presses the buttons, and the dashboard shows the probability bars for that decision.

**Architecture:** Three new packages on top of the milestone 1 harness. `brain/` is pure: it turns a `GameState` into the JSON state and questions Jev sees, and a TypeSafe response into a `Decision`; buckets live here, so raw numbers never leave the brain. `executor/` presses buttons: battle macros that verify the cursor label on screen before every A, a dialog skipper, and a minimal window navigator the state script needs to reach a battle. `loop.py` gains an async `advance` that calls the brain at `BATTLE_MENU` and publishes a `decision` event; the dashboard renders it as bars. `GameState` grows the party, the active battle Pokémon, the enemy, and the bag, all as raw numbers.

**Tech Stack:** as milestone 1 plus `typesafe-sdk>=0.7` (pydantic models; `AsyncTypeSafeClient.system_one(state, questions)`).

**Spec:** `docs/superpowers/specs/2026-09-20-jevplays-design.md`, sections 6, 8 (8.1, 8.4), 9 (macros), 10 (`decision` event and the panel), 12, 13, 14 (milestone 2). Two deliberate deviations, recorded in Task 11's spec amendment: (1) section 6 puts HP/PP buckets in `GameState`; this plan keeps `GameState` raw and buckets in `brain/buckets.py`, with a test that the JSON sent to Jev carries no HP, PP, or money numbers (levels are allowed, as in the spec's own example); (2) section 14 puts navigation in milestone 3; this plan ships `executor/navigate.py`'s window pathfinder now because `Scripts/make-states.py` needs it to reach a battle, and milestone 3's waypoint graph builds on it.

## Global Constraints

- Everything in milestone 1's plan still binds: Python `>=3.12`; ruff line length 110, `select = ["E", "F", "I", "B"]`, `ignore = ["E501"]`; `import pyboy` only in `src/jevplays/emulator/pyboy.py`; `tests/rom/` not collected without `JEVPLAYS_ROM`; nothing game-derived committed; conventional commits; branch `tylervick/milestone-2-battles` (already created from `main` at `af53e62`).
- `import typesafe_sdk` only inside `src/jevplays/brain/client.py` and `Scripts/record-fixtures.py`. Builders, policy, and decoders work on plain dicts and the SDK's pydantic answer models; unit tests replay recorded responses from `tests/fixtures/responses/*.json` and never call the API. `TYPESAFE_API_KEY` is read only by the SDK.
- Jev never receives coordinates, screenshots, HP, PP, or money numbers. The state JSON built by the brain carries names, types, levels, and bucket words. A unit test enforces this.
- ROM facts verified 2026-09-20 on this ROM (Charmander vs the rival's Squirtle in Oak's lab, then a wild Rattata on Route 1). Battle Pokémon: `wBattleMonNick 0xD009` (11 bytes), `wBattleMonSpecies 0xD014`, `wBattleMonHP 0xD015` (u16 big-endian), `wBattleMonStatus 0xD018`, `wBattleMonType1/2 0xD019/0xD01A`, `wBattleMonMoves 0xD01C` (4 bytes), `wBattleMonLevel 0xD022`, `wBattleMonMaxHP 0xD023` (u16), `wBattleMonPP 0xD02D` (4 bytes). Enemy: `wEnemyMonNick 0xCFDA`, `wEnemyMonSpecies 0xCFE5`, `wEnemyMonHP 0xCFE6`, `wEnemyMonStatus 0xCFE9`, `wEnemyMonType1/2 0xCFEA/0xCFEB`, `wEnemyMonMoves 0xCFED`, `wEnemyMonLevel 0xCFF3`, `wEnemyMonMaxHP 0xCFF4`. `wIsInBattle 0xD057` is 1 wild, 2 trainer. `wTrainerClass 0xD031` (25 = RIVAL1). Party slot `i` at `0xD16B + 0x2C * i`: species +0, HP +1 (u16), status +4, type1 +5, type2 +6, moves +8..+11, PP +29..+32, level +33, max HP +34 (u16); nicknames at `0xD2B5 + 11 * i`. Bag: `wNumBagItems 0xD31D`, then `wBagItems 0xD31E` as (item id, quantity) pairs terminated by 0xFF. Species ids are internal (Charmander 176, Squirtle 177, Rattata 165). Type ids: 0 Normal, 1 Fighting, 2 Flying, 3 Poison, 4 Ground, 5 Rock, 6 Bird, 7 Bug, 8 Ghost, 20 Fire, 21 Water, 22 Grass, 23 Electric, 24 Psychic, 25 Ice, 26 Dragon. Move ids: Scratch 10, Growl 45, Tackle 33, Tail Whip 39, Ember 52.
- Battle menu geometry: at the command menu `wTopMenuItemY == 14`, `wTopMenuItemX == 9` (left column: FIGHT then ITEM) or `15` (right column: PKMN then RUN), `wMaxMenuItem == 1`; row 14 reads `▶FIGHT` and `PK MN`, row 16 `ITEM` and `RUN`; `right` moves to the right column, `down` to the second row. After FIGHT, the move list occupies rows 13 to 16 with the cursor at column 5 and `wMaxMenuItem == 3`; `wCurrentMenuItem` is the move index. Selecting RUN in a wild battle printed "Got away safely!".
- The route to a battle from `states/overworld.state`, all verified: 2F stairs at (7, 1) warp to 1F; 1F door mat at (3, 7), step `down` to exit; Pallet Town (map 0) spawn (5, 6); walking to (10, 1) triggers Oak ("OAK: Hey! Wait!"), then a cutscene with a silent text box ("Here, come with me!") that needs an A press after a short idle; the lab (map 40) leaves the player at (5, 3); the starter balls sit at y=3, x=6 Charmander, 7 Squirtle, 8 Bulbasaur, interacted with from (x, 4) facing up; the choose prompt is answered YES and the nickname prompt ("Do you want to give a nickname") NO; walking to the door at (4, 11) triggers the rival ("BLUE: Wait!") and a trainer battle; after the battle the lab exit at (4, 11) plus `down` leaves the player at (12, 12) in Pallet Town directly below the lab door, so step `left` twice before heading to (10, 1) and `up` twice onto Route 1 (map 12, arriving at (10, 33)); wandering up through the grass gave a wild battle within a few dozen steps.
- TypeSafe SDK shapes (0.7.0): `Choice(instructions=..., criteria={option: description | None})`, `Noul(instructions=..., criteria={"true": ..., "false": ...} | None)`; `await AsyncTypeSafeClient().system_one(state, questions)` returns a `SystemOneResponse` with `.model` (str), `.usage.input_tokens`, `.request_id`, `.choices[id]` (`.choice`, `.probabilities: dict[str, float]`, `.confidence`), `.nouls[id]` (`.noul: float`), and `.model_dump()`; `SystemOneResponse.model_validate(dict)` rebuilds one. A real call with the battle state below took 394 ms and 719 input tokens and answered EMBER 0.65, SCRATCH 0.32, GROWL 0.03 against a Grass type. Errors: `TypeSafeAPIError` (`.status`, `.request_id`), `TypeSafeRateLimitError`, `TypeSafeAPIConnectionError`, `TypeSafeAPITimeoutError`; `RetryPolicy(max_retries=..., backoff_max=..., timeout=...)`.

---

## File structure

```
src/jevplays/state/data/{species,moves,items,trainers}.json   Gen 1 tables (Task 1)
src/jevplays/state/names.py                                   + species/move/type/item/trainer lookups (Task 1)
src/jevplays/emulator/ram.py                                  + battle, party, bag addresses; read_u16; status_name (Task 4)
src/jevplays/emulator/pyboy.py                                + collision() (Task 2)
src/jevplays/executor/__init__.py
src/jevplays/executor/navigate.py                             step, first_step (BFS), goto over the collision window (Task 2)
src/jevplays/executor/dialog.py                               skip_dialog, answer_prompt, cursor_label re-export (Task 2)
src/jevplays/executor/battle.py                               select_command, select_move, run_away, apply (Task 8)
Scripts/make-states.py                                        + battle_trainer, battle_wait, route1, battle_wild states (Task 3)
src/jevplays/state/snapshot.py                                + Move, Mon, Battle, BagItem; party, active, enemy, battle, bag (Task 5)
src/jevplays/brain/__init__.py
src/jevplays/brain/buckets.py                                 hp_bucket, pp_bucket, power_bucket (Task 6)
src/jevplays/brain/decision.py                                Decision, BattleAction (Task 6)
src/jevplays/brain/policy.py                                  thresholds and the ordered rules (Task 6)
src/jevplays/brain/battle.py                                  battle_state, battle_questions, decide_battle (Task 6)
src/jevplays/brain/client.py                                  Brain: the one AsyncTypeSafeClient wrapper (Task 7)
Scripts/record-fixtures.py                                    calls the API once per battle state, writes fixtures (Task 7)
tests/fixtures/responses/{battle_trainer,battle_wild}.json    recorded (Task 7)
src/jevplays/loop.py                                          async advance, brain at BATTLE_MENU, decision publish, API backoff (Task 9)
src/jevplays/cli.py                                           brain wiring, --no-brain (Task 9)
src/jevplays/dashboard/events.py                              decision_event (Task 9)
src/jevplays/dashboard/static/{index.html,app.js,styles.css}  decision panel, party strip, decision log (Task 10)
docs/superpowers/specs/2026-09-20-jevplays-design.md          amendments (Task 11)
```

---

### Task 1: Name tables for species, moves, types, items, and trainers

**Files:**
- Create: `src/jevplays/state/data/species.json`, `moves.json`, `items.json`, `trainers.json` (copied from `/private/tmp/claude-503/-Users-builder-orca-projects-jevplays/cef7ae7f-42b5-46cc-8fab-57ac894a688b/scratchpad/data/`), `src/jevplays/state/data/README.md`
- Modify: `src/jevplays/state/names.py`
- Test: `tests/test_names.py`

**Interfaces:**
- Produces: `MoveData(name: str, type: str, power: int, pp: int)` frozen dataclass; `species_name(id) -> str`, `move_data(id) -> MoveData | None`, `type_name(id) -> str`, `item_name(id) -> str`, `trainer_class_name(id) -> str`; `TYPES: dict[int, str]`. Unknown ids fall back to `"Species 12"`, `None`, `"Type 9"`, `"Item 200"`, `"Trainer 60"`.

- [ ] **Step 1: Copy the data files and write the README**

```bash
mkdir -p src/jevplays/state/data
cp /private/tmp/claude-503/-Users-builder-orca-projects-jevplays/cef7ae7f-42b5-46cc-8fab-57ac894a688b/scratchpad/data/*.json src/jevplays/state/data/
```

`src/jevplays/state/data/README.md`:

```markdown
Gen 1 lookup tables, keyed by the game's internal ids as JSON strings.

- `species.json`: internal species id (not Pokédex number) to display name. 154 entries.
- `moves.json`: move id to `{name, type, power, pp}`. 165 entries, from pokered's `data/moves/moves.asm`.
- `items.json`: item id to display name. 81 entries.
- `trainers.json`: trainer class id to name (`RIVAL1` is 25). 48 entries.

Names come from PyBoy's Gen 1 constants (which follow pokered) with underscores replaced by
spaces so they match what the game prints. Type ids are few enough to live in `names.py`.
```

- [ ] **Step 2: Write the failing tests** (append to `tests/test_names.py`)

```python
from jevplays.state.names import (
    MoveData,
    item_name,
    move_data,
    species_name,
    trainer_class_name,
    type_name,
)


def test_species_use_internal_ids():
    assert species_name(176) == "CHARMANDER"
    assert species_name(177) == "SQUIRTLE"
    assert species_name(165) == "RATTATA"
    assert species_name(0) == "Species 0"


def test_move_data_carries_type_power_and_pp():
    assert move_data(10) == MoveData(name="SCRATCH", type="Normal", power=40, pp=35)
    assert move_data(45) == MoveData(name="GROWL", type="Normal", power=0, pp=40)
    assert move_data(52).type == "Fire"
    assert move_data(0) is None


def test_type_item_and_trainer_names():
    assert type_name(20) == "Fire" and type_name(0) == "Normal" and type_name(9) == "Type 9"
    assert item_name(4) == "POKE BALL" and item_name(200) == "Item 200"
    assert trainer_class_name(25) == "RIVAL1" and trainer_class_name(60) == "Trainer 60"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_names.py -q`
Expected: FAIL with `ImportError: cannot import name 'MoveData'`

- [ ] **Step 4: Extend `names.py`**

Append to `src/jevplays/state/names.py`:

```python
import json
from dataclasses import dataclass
from pathlib import Path

_DATA = Path(__file__).parent / "data"


def _load(name: str) -> dict:
    return json.loads((_DATA / name).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class MoveData:
    name: str
    type: str
    power: int
    pp: int


SPECIES: dict[int, str] = {int(k): v for k, v in _load("species.json").items()}
MOVES: dict[int, MoveData] = {int(k): MoveData(**v) for k, v in _load("moves.json").items()}
ITEMS: dict[int, str] = {int(k): v for k, v in _load("items.json").items()}
TRAINER_CLASSES: dict[int, str] = {int(k): v for k, v in _load("trainers.json").items()}

# pokered constants/type_constants.asm. Ids 9..19 are unused in the game.
TYPES: dict[int, str] = {
    0: "Normal", 1: "Fighting", 2: "Flying", 3: "Poison", 4: "Ground", 5: "Rock", 6: "Bird",
    7: "Bug", 8: "Ghost", 20: "Fire", 21: "Water", 22: "Grass", 23: "Electric", 24: "Psychic",
    25: "Ice", 26: "Dragon",
}


def species_name(species_id: int) -> str:
    return SPECIES.get(species_id, f"Species {species_id}")


def move_data(move_id: int) -> MoveData | None:
    return MOVES.get(move_id)


def type_name(type_id: int) -> str:
    return TYPES.get(type_id, f"Type {type_id}")


def item_name(item_id: int) -> str:
    return ITEMS.get(item_id, f"Item {item_id}")


def trainer_class_name(class_id: int) -> str:
    return TRAINER_CLASSES.get(class_id, f"Trainer {class_id}")
```

Move the two existing imports-free lines (`_CITIES`, `_EARLY_GAME`, `MAP_NAMES`, `map_name`) above or below as ruff's import ordering requires; the module's public surface is `map_name` plus the names above.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_names.py -q`
Expected: `6 passed`

- [ ] **Step 6: Commit**

```bash
git add src/jevplays/state/data src/jevplays/state/names.py tests/test_names.py
git commit -m "feat(state): Gen 1 species, move, type, item, and trainer name tables"
```

---

### Task 2: Window navigator and dialog helpers

**Files:**
- Modify: `src/jevplays/emulator/pyboy.py` (add `collision()`)
- Create: `src/jevplays/executor/__init__.py` (empty), `src/jevplays/executor/navigate.py`, `src/jevplays/executor/dialog.py`
- Modify: `tests/support.py` (add `collision` to `FakeEmulator`)
- Test: `tests/test_navigate.py`, `tests/test_dialog.py`, `tests/rom/test_navigate.py`

**Interfaces:**
- Produces: `Emulator.collision() -> list[list[int]]` (9 rows x 10 columns, 1 = walkable, the player at row 4 column 4); `PLAYER_ROW = 4`, `PLAYER_COL = 4`; `first_step(grid, target: tuple[int, int]) -> str | None` (BFS from the player cell; returns `"up"|"down"|"left"|"right"`); `step(emu, direction, *, hold=18, settle=8) -> bool` (True when the map or tile changed); `goto(emu, x, y, *, max_steps=80) -> bool` (True when reached or warped off the map); `class NavigationError(RuntimeError)`. `dialog.py`: `skip_dialog(emu, *, answer: Callable[[str], bool] | None = None, patience=80, nudge_after=15, stop_when=None, max_iters=600) -> bool`, `answer_prompt(emu, yes: bool)`, `dialog_lines(rows) -> list[str]`, `yes_no_open(rows) -> bool`, `cursor_label` (re-exported from `jevplays.emulator.intro`).
- `FakeEmulator.collision()` returns `self.grid` (a 9x10 list, default all walkable) so `first_step` and `goto` are unit-testable; `FakeEmulator.step_effects: dict[str, tuple[int, int]]` optional map from direction to the tile delta applied on `press` so `goto` can be tested without a ROM.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_navigate.py
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
```

```python
# tests/test_dialog.py
from jevplays.executor.dialog import dialog_lines, yes_no_open
from tests.support import rows_from

DIALOG = rows_from([""] * 12 + ["····················", "·                  ·", "·Hello there!      ·", "·                  ·", "·Welcome to the   ▼·"])
PROMPT = rows_from(["·▶YES·", "·    ·", "· NO ·"])


def test_dialog_lines_strip_borders_and_arrow():
    assert dialog_lines(DIALOG) == ["Hello there!", "Welcome to the"]


def test_yes_no_open():
    assert yes_no_open(PROMPT)
    assert not yes_no_open(DIALOG)
```

```python
# tests/rom/test_navigate.py
from jevplays.emulator import ram
from jevplays.emulator.pyboy import Emulator
from jevplays.executor.navigate import goto


def test_collision_window_has_the_expected_shape(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("overworld"))
        grid = emu.collision()
        assert len(grid) == 9 and all(len(row) == 10 for row in grid)
        assert all(cell in (0, 1) for row in grid for cell in row)


def test_goto_reaches_the_bedroom_stairs_and_warps_downstairs(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("overworld"))
        assert goto(emu, 7, 1)
        emu.tick(60)
        assert emu.mem[ram.wCurMap] == 37  # REDS_HOUSE_1F
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_navigate.py tests/test_dialog.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'jevplays.executor'`

- [ ] **Step 3: Write the implementation**

Add to `src/jevplays/emulator/pyboy.py` (method on `Emulator`):

```python
    def collision(self) -> list[list[int]]:
        """Walkable map of the visible screen as 9 rows x 10 columns of 16x16 blocks; the player
        stands at row 4, column 4. 1 is walkable. PyBoy's Gen 1 wrapper derives it from the
        tileset's collision table, so NPCs are not marked."""
        area = self._py.game_wrapper.game_area_collision()
        return [[int(area[r][c]) for c in range(0, 20, 2)] for r in range(0, 18, 2)]
```

Add to `FakeEmulator` in `tests/support.py` (inside `__init__`: `self.grid = [[1] * 10 for _ in range(9)]` and `self.step_effects = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}`; and in `press`, after recording the button, apply the effect if the button is in `step_effects`):

```python
    def collision(self) -> list[list[int]]:
        return [row[:] for row in self.grid]

    def press(self, button: str, *, hold: int = 8, settle: int = 8) -> int:
        self.presses.append(button)
        if button in self.step_effects:
            dx, dy = self.step_effects[button]
            self.mem[wXCoord] = self.mem[wXCoord] + dx
            self.mem[wYCoord] = self.mem[wYCoord] + dy
        return self.tick(hold + settle)
```

(import `wXCoord`, `wYCoord` from `jevplays.emulator.ram` at the top of `tests/support.py`.)

```python
# src/jevplays/executor/navigate.py
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
```

```python
# src/jevplays/executor/dialog.py
"""Pressing through text, and answering yes/no boxes, by reading the screen buffer."""

from collections.abc import Callable

from jevplays.emulator.intro import ARROW_COL, ARROW_ROW, cursor_label
from jevplays.emulator.text import ARROW, NON_TEXT, row_text
from jevplays.state.modes import DIALOG_ROWS, yes_no_at
from jevplays.state.snapshot import rows_of

__all__ = ["answer_prompt", "cursor_label", "dialog_lines", "skip_dialog", "yes_no_open"]


def dialog_lines(rows: list[list[str]]) -> list[str]:
    lines = []
    for r in DIALOG_ROWS:
        line = row_text(c for c in rows[r] if c != ARROW).strip(" " + NON_TEXT)
        if line:
            lines.append(line)
    return lines


def yes_no_open(rows: list[list[str]]) -> bool:
    return yes_no_at(rows) is not None


def answer_prompt(emu, yes: bool) -> None:
    """With a YES/NO box open and the cursor on YES, pick one."""
    if not yes:
        emu.press("down")
    emu.press("a", settle=40)


def skip_dialog(
    emu,
    *,
    answer: Callable[[str], bool] | None = None,
    patience: int = 80,
    nudge_after: int = 15,
    stop_when: Callable[[list[list[str]]], bool] | None = None,
    max_iters: int = 600,
) -> bool:
    """Press A through dialog until it ends. `answer(text)` decides each YES/NO box from the
    dialog text on screen (default: YES). After `nudge_after` idle ticks with text still showing,
    press A anyway (some boxes end without the arrow). Returns True if `stop_when` fired."""
    idle = 0
    for _ in range(max_iters):
        rows = rows_of(emu.tilemap())
        if stop_when is not None and stop_when(rows):
            return True
        if yes_no_open(rows):
            yes = True if answer is None else answer(" ".join(dialog_lines(rows)))
            answer_prompt(emu, yes)
            idle = 0
            continue
        if rows[ARROW_ROW][ARROW_COL] == ARROW:
            emu.press("a", settle=30)
            idle = 0
            continue
        emu.tick(10)
        idle += 1
        if dialog_lines(rows) and idle >= nudge_after:
            emu.press("a", settle=30)
            idle = 0
            continue
        if idle > patience:
            return False
    return False
```

Note `rows_of` is imported from `jevplays.state.snapshot` (it exists there since milestone 1).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_navigate.py tests/test_dialog.py -q` then `mise exec -- uv run pytest tests/rom/test_navigate.py -q`
Expected: `7 passed` then `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/emulator/pyboy.py src/jevplays/executor tests/support.py tests/test_navigate.py tests/test_dialog.py tests/rom/test_navigate.py
git commit -m "feat(executor): window pathfinder and dialog helpers that read the screen"
```

---

### Task 3: Save states for both battle kinds

**Files:**
- Modify: `Scripts/make-states.py`
- Test: `tests/rom/test_snapshot.py` (extend the mode parametrization), `tests/rom/test_ram.py` (battle addresses, Task 4 adds the constants; here only the state files)

**Interfaces:**
- Produces: `states/battle_trainer.state` (rival battle, FIGHT menu open), `states/battle_wait.state` (mid-turn text after choosing SCRATCH), `states/route1.state` (Route 1, overworld, Charmander in party), `states/battle_wild.state` (wild battle, FIGHT menu open). `Scripts/make-states.py` gains `--only NAME` to regenerate one state.

- [ ] **Step 1: Extend the state script**

Add these helpers and the battle route to `Scripts/make-states.py` (keep the four milestone 1 states as they are; the new ones run after them from `overworld.state`):

```python
from jevplays.emulator import ram
from jevplays.executor.dialog import cursor_label, skip_dialog
from jevplays.executor.navigate import goto, step
from jevplays.state.snapshot import rows_of


def fight_menu_open(emu) -> bool:
    rows = rows_of(emu.tilemap())
    return "FIGHT" in "".join(rows[14]) and rows[16][18] != "▼"


def wait_for_fight_menu(emu, frames: int = 3000) -> None:
    for _ in range(0, frames, 10):
        if emu.mem[ram.wIsInBattle] == 0 or fight_menu_open(emu):
            return
        rows = rows_of(emu.tilemap())
        if rows[16][18] == "▼" or any("".join(r).strip("· ") for r in rows[13:17]):
            emu.press("a", settle=30)
        else:
            emu.tick(10)
    raise SystemExit("the FIGHT menu never opened")


def play_one_turn(emu) -> None:
    """At the FIGHT menu: FIGHT, then the first move."""
    emu.press("a", settle=40)
    emu.press("a", settle=20)


def finish_battle(emu, max_turns: int = 40) -> None:
    for _ in range(max_turns):
        if emu.mem[ram.wIsInBattle] == 0:
            return
        wait_for_fight_menu(emu)
        if emu.mem[ram.wIsInBattle] == 0:
            return
        play_one_turn(emu)
        emu.tick(30)
    raise SystemExit("the battle did not end")


def starter_answer(text: str) -> bool:
    return "nickname" not in text.lower()


def make_battle_states(rom: Path, out: Path) -> None:
    with Emulator(rom) as emu:
        emu.load(out / "overworld.state")
        assert goto(emu, 7, 1), "bedroom stairs"
        emu.tick(30)
        assert goto(emu, 3, 7), "front door mat"
        step(emu, "down", settle=30)
        emu.tick(60)
        assert emu.mem[ram.wCurMap] == 0, "Pallet Town"
        assert goto(emu, 10, 1), "route 1 edge"
        emu.tick(90)
        skip_dialog(emu, patience=150, stop_when=lambda rows: emu.mem[ram.wCurMap] == 40 and not any("".join(r).strip("· ") for r in rows[13:17]))
        emu.tick(120)
        skip_dialog(emu, patience=60)
        assert emu.mem[ram.wCurMap] == 40, "Oak's lab"
        assert goto(emu, 6, 4), "below Charmander's ball"
        emu.press("up", hold=4, settle=12)
        emu.press("a", settle=60)
        skip_dialog(emu, answer=starter_answer, patience=40, stop_when=lambda rows: emu.mem[ram.wPartyCount] == 1)
        skip_dialog(emu, answer=starter_answer, patience=40)
        assert emu.mem[ram.wPartyCount] == 1, "took Charmander"
        goto(emu, 4, 11)  # the rival interrupts before the door is reached
        skip_dialog(emu, patience=60, stop_when=lambda rows: emu.mem[ram.wIsInBattle] != 0)
        wait_for_fight_menu(emu)
        assert emu.mem[ram.wIsInBattle] == 2, "trainer battle"
        emu.save(out / "battle_trainer.state")
        play_one_turn(emu)
        emu.tick(30)
        emu.save(out / "battle_wait.state")
        finish_battle(emu)
        skip_dialog(emu, answer=lambda text: False, patience=60)
        assert goto(emu, 4, 11), "lab door"
        step(emu, "down", settle=30)
        emu.tick(30)
        step(emu, "left")
        step(emu, "left")
        assert goto(emu, 10, 2) and goto(emu, 10, 1), "pallet north"
        step(emu, "up", settle=30)
        step(emu, "up", settle=30)
        emu.tick(60)
        assert emu.mem[ram.wCurMap] == 12, "Route 1"
        emu.save(out / "route1.state")
        pattern = ["up", "up", "left", "up", "right", "up", "left", "up", "right", "up"]
        for i in range(300):
            if emu.mem[ram.wIsInBattle] == 1:
                break
            direction = pattern[i % len(pattern)]
            if not step(emu, direction, settle=12):
                step(emu, "right" if direction == "left" else "left", settle=12)
        else:
            raise SystemExit("no wild encounter on Route 1")
        wait_for_fight_menu(emu)
        emu.save(out / "battle_wild.state")
```

Wire it into `main`: after the existing states, `make_battle_states(Path(rom), args.out)`, and print the four new `wrote ...` lines. Add `--only NAME` (choices: the eight state names) that runs just the group containing that state; the battle group always regenerates all four battle-route states because each depends on the previous.

- [ ] **Step 2: Run it and check the states**

Run: `mise run states`
Expected: eight `wrote states/....state` lines. Then:

```bash
mise exec -- uv run jevplays state states/battle_trainer.state | head -5
mise exec -- uv run jevplays state states/battle_wild.state | head -5
```

Expected: `"mode": "battle_menu"` and `"in_battle": true` in both.

- [ ] **Step 3: Extend the ROM mode test**

In `tests/rom/test_snapshot.py`, extend the parametrize list:

```python
        ("battle_trainer", Mode.BATTLE_MENU),
        ("battle_wild", Mode.BATTLE_MENU),
        ("battle_wait", Mode.BATTLE_WAIT),
        ("route1", Mode.OVERWORLD),
```

Run: `mise exec -- uv run pytest tests/rom/test_snapshot.py -q`
Expected: all pass (8 parametrized plus the 4 detail tests).

- [ ] **Step 4: Commit**

```bash
git add Scripts/make-states.py tests/rom/test_snapshot.py
git commit -m "feat(states): script the walk to the rival battle and a wild battle, and save both"
```

---

### Task 4: Battle, party, and bag addresses

**Files:**
- Modify: `src/jevplays/emulator/ram.py`
- Test: `tests/test_ram.py`, `tests/rom/test_ram.py`

**Interfaces:**
- Produces: constants `wBattleMonNick, wBattleMonSpecies, wBattleMonHP, wBattleMonStatus, wBattleMonType1, wBattleMonType2, wBattleMonMoves, wBattleMonLevel, wBattleMonMaxHP, wBattleMonPP, wEnemyMonNick, wEnemyMonSpecies, wEnemyMonHP, wEnemyMonStatus, wEnemyMonType1, wEnemyMonType2, wEnemyMonMoves, wEnemyMonLevel, wEnemyMonMaxHP, wTrainerClass, wPartyMons, PARTY_MON_SIZE, wPartyMonNicks, MON_SPECIES, MON_HP, MON_STATUS, MON_TYPE1, MON_TYPE2, MON_MOVES, MON_PP, MON_LEVEL, MON_MAX_HP, BAG_END`; `read_u16(mem, addr) -> int`; `status_name(byte) -> str` in `{"none","asleep","poisoned","burned","frozen","paralyzed"}`; `pp_current(byte) -> int` (low 6 bits; the top two are PP Up counts).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ram.py`:

```python
def test_battle_and_party_addresses():
    assert ram.wBattleMonSpecies == 0xD014 and ram.wBattleMonHP == 0xD015 and ram.wBattleMonPP == 0xD02D
    assert ram.wEnemyMonSpecies == 0xCFE5 and ram.wEnemyMonHP == 0xCFE6 and ram.wEnemyMonLevel == 0xCFF3
    assert ram.wPartyMons == 0xD16B and ram.PARTY_MON_SIZE == 0x2C and ram.wPartyMonNicks == 0xD2B5
    assert (ram.MON_HP, ram.MON_MOVES, ram.MON_PP, ram.MON_LEVEL, ram.MON_MAX_HP) == (1, 8, 29, 33, 34)


def test_read_u16_is_big_endian():
    mem = FakeMemory()
    mem[0xD015] = 0x01
    mem[0xD016] = 0x2C
    assert ram.read_u16(mem, 0xD015) == 300


def test_status_name_and_pp_current():
    assert ram.status_name(0) == "none"
    assert ram.status_name(0b0000_0011) == "asleep"
    assert ram.status_name(0b0000_1000) == "poisoned"
    assert ram.status_name(0b0001_0000) == "burned"
    assert ram.status_name(0b0010_0000) == "frozen"
    assert ram.status_name(0b0100_0000) == "paralyzed"
    assert ram.pp_current(35) == 35
    assert ram.pp_current(0b1100_0000 | 20) == 20
```

Append to `tests/rom/test_ram.py`:

```python
def test_trainer_battle_addresses(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("battle_trainer"))
        m = emu.mem
        assert m[ram.wIsInBattle] == 2
        assert m[ram.wTrainerClass] == 25  # RIVAL1
        assert m[ram.wBattleMonSpecies] == 176 and m[ram.wEnemyMonSpecies] == 177
        assert ram.read_u16(m, ram.wBattleMonHP) == ram.read_u16(m, ram.wBattleMonMaxHP) == 19
        assert ram.read_u16(m, ram.wEnemyMonMaxHP) == 20 and m[ram.wEnemyMonLevel] == 5
        assert (m[ram.wBattleMonType1], m[ram.wEnemyMonType1]) == (20, 21)  # Fire, Water
        assert ram.read_bytes(m, ram.wBattleMonMoves, 4) == bytes([10, 45, 0, 0])
        assert ram.read_bytes(m, ram.wBattleMonPP, 4) == bytes([35, 40, 0, 0])
        assert ram.read_name(m, ram.wEnemyMonNick) == "SQUIRTLE"
        slot = ram.wPartyMons
        assert m[slot + ram.MON_SPECIES] == 176 and m[slot + ram.MON_LEVEL] == 5
        assert ram.read_u16(m, slot + ram.MON_MAX_HP) == 19
        assert ram.read_name(m, ram.wPartyMonNicks) == "CHARMANDER"


def test_wild_battle_addresses(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("battle_wild"))
        m = emu.mem
        assert m[ram.wIsInBattle] == 1
        assert m[ram.wEnemyMonSpecies] == 165  # RATTATA
        assert (m[ram.wEnemyMonType1], m[ram.wEnemyMonType2]) == (0, 0)
        assert m[ram.wNumBagItems] == 0
```

- [ ] **Step 2: Run the unit tests to verify they fail**

Run: `uv run pytest tests/test_ram.py -q`
Expected: FAIL with `AttributeError: module 'jevplays.emulator.ram' has no attribute 'wBattleMonSpecies'`

- [ ] **Step 3: Extend `ram.py`**

Append (keeping the address-ordered style):

```python
# The two Pokémon in a battle. Ours is a copy of the party slot that is out; the enemy's is
# built when the battle starts. Both use the same in-battle record layout.
wEnemyMonNick = 0xCFDA
wEnemyMonSpecies = 0xCFE5
wEnemyMonHP = 0xCFE6  # u16
wEnemyMonStatus = 0xCFE9
wEnemyMonType1 = 0xCFEA
wEnemyMonType2 = 0xCFEB
wEnemyMonMoves = 0xCFED  # 4 bytes
wEnemyMonLevel = 0xCFF3
wEnemyMonMaxHP = 0xCFF4  # u16
wBattleMonNick = 0xD009
wBattleMonSpecies = 0xD014
wBattleMonHP = 0xD015  # u16
wBattleMonStatus = 0xD018
wBattleMonType1 = 0xD019
wBattleMonType2 = 0xD01A
wBattleMonMoves = 0xD01C  # 4 bytes
wBattleMonLevel = 0xD022
wBattleMonMaxHP = 0xD023  # u16
wBattleMonPP = 0xD02D  # 4 bytes
wTrainerClass = 0xD031

# Party records, 0x2C bytes each, six slots. Offsets within a record:
wPartyMons = 0xD16B
PARTY_MON_SIZE = 0x2C
MON_SPECIES = 0
MON_HP = 1  # u16
MON_STATUS = 4
MON_TYPE1 = 5
MON_TYPE2 = 6
MON_MOVES = 8  # 4 bytes
MON_PP = 29  # 4 bytes; low 6 bits are current PP, top 2 bits PP Ups used
MON_LEVEL = 33
MON_MAX_HP = 34  # u16
wPartyMonNicks = 0xD2B5  # NAME_LENGTH bytes each

BAG_END = 0xFF
"""Terminates the (item id, quantity) pairs at wBagItems."""


def read_u16(mem: Memory, addr: int) -> int:
    return (mem[addr] << 8) | mem[addr + 1]


def status_name(status: int) -> str:
    """The Gen 1 status byte: bits 0-2 sleep turns, 3 poison, 4 burn, 5 freeze, 6 paralysis."""
    if status & 0b0000_0111:
        return "asleep"
    if status & 0b0000_1000:
        return "poisoned"
    if status & 0b0001_0000:
        return "burned"
    if status & 0b0010_0000:
        return "frozen"
    if status & 0b0100_0000:
        return "paralyzed"
    return "none"


def pp_current(pp: int) -> int:
    return pp & 0b0011_1111
```

- [ ] **Step 4: Run all ram tests**

Run: `uv run pytest tests/test_ram.py -q` then `mise exec -- uv run pytest tests/rom/test_ram.py -q`
Expected: `7 passed` then `6 passed`

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/emulator/ram.py tests/test_ram.py tests/rom/test_ram.py
git commit -m "feat(emulator): battle, party, and bag addresses, verified against both battle kinds"
```

---

### Task 5: Party, active Pokémon, enemy, and bag in GameState

**Files:**
- Modify: `src/jevplays/state/snapshot.py`
- Test: `tests/test_snapshot.py`, `tests/rom/test_snapshot.py`
- Modify: `tests/support.py` (add `write_mon` helper)

**Interfaces:**
- Produces: frozen dataclasses `Move(name: str, type: str, power: int, pp: int, max_pp: int)`, `Mon(name: str, nickname: str, level: int, types: tuple[str, ...], hp: int, max_hp: int, status: str, moves: tuple[Move, ...])`, `Battle(kind: str, trainer_class: str | None)` (kind `"wild"` or `"trainer"`), `BagItem(name: str, quantity: int)`; `GameState` gains `party: tuple[Mon, ...]`, `active: Mon | None` (the battle Pokémon while in battle), `enemy: Mon | None`, `battle: Battle | None`, `bag: tuple[BagItem, ...]`; `read_mon(mem, base, nick_addr, *, in_battle_layout: bool) -> Mon`; `to_dict()` serializes all of them (dataclasses to dicts, tuples to lists). `tests.support.write_mon(mem, base, nick_addr, *, species, level, hp, max_hp, types, moves, pps, status=0)` and `write_battle_mon(mem, ours: bool, **same)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/support.py`:

```python
def write_mon(mem, base, nick_addr, *, species, level, hp, max_hp, types, moves, pps, status=0, nickname=None, layout="party"):
    """Write a Pokémon record. layout "party" uses the 0x2C party offsets; "battle" uses the
    in-battle record offsets relative to its species byte (HP at +1, status +4, types +5/+6,
    moves +8, level +14, max HP +15, PP +25) — see ram.py for why the two differ."""
    from jevplays.emulator.text import TERMINATOR

    if layout == "party":
        off = dict(hp=MON_HP, status=MON_STATUS, t1=MON_TYPE1, t2=MON_TYPE2, moves=MON_MOVES, pp=MON_PP, level=MON_LEVEL, max_hp=MON_MAX_HP)
    else:
        off = dict(hp=1, status=4, t1=5, t2=6, moves=8, pp=25, level=14, max_hp=15)
    mem[base] = species
    mem[base + off["hp"]] = hp >> 8
    mem[base + off["hp"] + 1] = hp & 0xFF
    mem[base + off["status"]] = status
    mem[base + off["t1"]] = types[0]
    mem[base + off["t2"]] = types[1] if len(types) > 1 else types[0]
    for i in range(4):
        mem[base + off["moves"] + i] = moves[i] if i < len(moves) else 0
        mem[base + off["pp"] + i] = pps[i] if i < len(pps) else 0
    mem[base + off["level"]] = level
    mem[base + off["max_hp"]] = max_hp >> 8
    mem[base + off["max_hp"] + 1] = max_hp & 0xFF
    name = encode(nickname or "MON") + [TERMINATOR]
    mem[nick_addr : nick_addr + len(name)] = name
```

(import `MON_*` names from `jevplays.emulator.ram` at the top of `tests/support.py`.)

Append to `tests/test_snapshot.py`:

```python
from jevplays.state.snapshot import BagItem, Battle, Mon, Move
from tests.support import write_mon


def charmander(emu, *, in_battle=False):
    write_mon(emu.mem, ram.wPartyMons, ram.wPartyMonNicks, species=176, level=5, hp=19, max_hp=19,
              types=(20, 20), moves=(10, 45), pps=(35, 40), nickname="CHARMANDER")
    emu.mem[ram.wPartyCount] = 1
    if in_battle:
        write_mon(emu.mem, ram.wBattleMonSpecies, ram.wBattleMonNick, species=176, level=5, hp=12, max_hp=19,
                  types=(20, 20), moves=(10, 45), pps=(34, 40), nickname="CHARMANDER", layout="battle")
        write_mon(emu.mem, ram.wEnemyMonSpecies, ram.wEnemyMonNick, species=177, level=5, hp=20, max_hp=20,
                  types=(21, 21), moves=(33, 39), pps=(35, 30), nickname="SQUIRTLE", layout="battle")


def test_party_is_parsed_from_the_party_records():
    emu = FakeEmulator()
    bedroom(emu)
    charmander(emu)
    state = snapshot(emu)
    assert state.party == (
        Mon(name="CHARMANDER", nickname="CHARMANDER", level=5, types=("Fire",), hp=19, max_hp=19, status="none",
            moves=(Move(name="SCRATCH", type="Normal", power=40, pp=35, max_pp=35),
                   Move(name="GROWL", type="Normal", power=0, pp=40, max_pp=40))),
    )
    assert state.active is None and state.enemy is None and state.battle is None


def test_battle_fields_when_in_a_trainer_battle():
    emu = FakeEmulator()
    bedroom(emu)
    charmander(emu, in_battle=True)
    emu.mem[ram.wIsInBattle] = 2
    emu.mem[ram.wTrainerClass] = 25
    emu.set_rows([""] * 14 + ["·       ·▶FIGHT PK·", "", "·       · ITEM RUN·"])
    state = snapshot(emu)
    assert state.mode is Mode.BATTLE_MENU
    assert state.battle == Battle(kind="trainer", trainer_class="RIVAL1")
    assert state.active.hp == 12 and state.active.moves[0].pp == 34
    assert state.enemy.name == "SQUIRTLE" and state.enemy.types == ("Water",)


def test_wild_battle_has_no_trainer():
    emu = FakeEmulator()
    bedroom(emu)
    charmander(emu, in_battle=True)
    emu.mem[ram.wIsInBattle] = 1
    assert snapshot(emu).battle == Battle(kind="wild", trainer_class=None)


def test_bag_items_are_parsed_until_the_terminator():
    emu = FakeEmulator()
    bedroom(emu)
    emu.mem[ram.wNumBagItems] = 2
    emu.mem[ram.wBagItems : ram.wBagItems + 5] = [4, 5, 20, 2, ram.BAG_END]  # 5 POKE BALL, 2 POTION
    state = snapshot(emu)
    assert state.bag == (BagItem(name="POKE BALL", quantity=5), BagItem(name="POTION", quantity=2))
    assert state.bag_count == 2


def test_to_dict_serializes_nested_records():
    emu = FakeEmulator()
    bedroom(emu)
    charmander(emu)
    d = snapshot(emu).to_dict()
    assert d["party"][0]["moves"][0] == {"name": "SCRATCH", "type": "Normal", "power": 40, "pp": 35, "max_pp": 35}
    assert d["active"] is None and d["bag"] == []
```

Note: `bedroom()` sets `wNumBagItems` to 2 in milestone 1's test; the bag test overrides the items. `item_name(20)` must be `POTION`; verify against `items.json` and adjust the id in the test if the table says otherwise (the ROM's POTION id is 20).

Append to `tests/rom/test_snapshot.py`:

```python
def test_trainer_battle_state(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("battle_trainer"))
        state = snapshot(emu)
        assert state.battle == Battle(kind="trainer", trainer_class="RIVAL1")
        assert state.active.name == "CHARMANDER" and state.active.types == ("Fire",)
        assert [m.name for m in state.active.moves] == ["SCRATCH", "GROWL"]
        assert state.enemy.name == "SQUIRTLE" and state.enemy.level == 5
        assert state.party[0].nickname == "CHARMANDER"


def test_wild_battle_state(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("battle_wild"))
        state = snapshot(emu)
        assert state.battle.kind == "wild"
        assert state.enemy.name == "RATTATA" and state.enemy.types == ("Normal",)
```

- [ ] **Step 2: Run the unit tests to verify they fail**

Run: `uv run pytest tests/test_snapshot.py -q`
Expected: FAIL with `ImportError: cannot import name 'BagItem'`

- [ ] **Step 3: Extend `snapshot.py`**

Add the records and readers, and the new fields:

```python
from jevplays.state.names import item_name, move_data, species_name, trainer_class_name, type_name


@dataclass(frozen=True)
class Move:
    name: str
    type: str
    power: int
    pp: int
    max_pp: int


@dataclass(frozen=True)
class Mon:
    name: str
    nickname: str
    level: int
    types: tuple[str, ...]
    hp: int
    max_hp: int
    status: str
    moves: tuple[Move, ...]


@dataclass(frozen=True)
class Battle:
    kind: str
    trainer_class: str | None


@dataclass(frozen=True)
class BagItem:
    name: str
    quantity: int


# In-battle records (wBattleMon*, wEnemyMon*) are laid out differently from party records:
# the offsets below are relative to the species byte.
_BATTLE_OFFSETS = dict(hp=1, status=4, type1=5, type2=6, moves=8, level=14, max_hp=15, pp=25)
_PARTY_OFFSETS = dict(hp=ram.MON_HP, status=ram.MON_STATUS, type1=ram.MON_TYPE1, type2=ram.MON_TYPE2,
                      moves=ram.MON_MOVES, level=ram.MON_LEVEL, max_hp=ram.MON_MAX_HP, pp=ram.MON_PP)


def read_mon(mem: ram.Memory, base: int, nick_addr: int, *, in_battle_layout: bool) -> Mon:
    off = _BATTLE_OFFSETS if in_battle_layout else _PARTY_OFFSETS
    t1, t2 = mem[base + off["type1"]], mem[base + off["type2"]]
    types = (type_name(t1),) if t1 == t2 else (type_name(t1), type_name(t2))
    moves = []
    for i in range(4):
        move_id = mem[base + off["moves"] + i]
        data = move_data(move_id)
        if move_id == 0 or data is None:
            continue
        moves.append(Move(name=data.name, type=data.type, power=data.power,
                          pp=ram.pp_current(mem[base + off["pp"] + i]), max_pp=data.pp))
    return Mon(
        name=species_name(mem[base]),
        nickname=ram.read_name(mem, nick_addr),
        level=mem[base + off["level"]],
        types=types,
        hp=ram.read_u16(mem, base + off["hp"]),
        max_hp=ram.read_u16(mem, base + off["max_hp"]),
        status=ram.status_name(mem[base + off["status"]]),
        moves=tuple(moves),
    )


def read_party(mem: ram.Memory) -> tuple[Mon, ...]:
    count = min(mem[ram.wPartyCount], 6)
    return tuple(
        read_mon(mem, ram.wPartyMons + i * ram.PARTY_MON_SIZE, ram.wPartyMonNicks + i * ram.NAME_LENGTH, in_battle_layout=False)
        for i in range(count)
    )


def read_bag(mem: ram.Memory) -> tuple[BagItem, ...]:
    items = []
    addr = ram.wBagItems
    for _ in range(min(mem[ram.wNumBagItems], 20)):
        item_id = mem[addr]
        if item_id in (0, ram.BAG_END):  # 0 is an empty slot (a fake or a fresh game), 0xFF the terminator
            break
        items.append(BagItem(name=item_name(item_id), quantity=mem[addr + 1]))
        addr += 2
    return tuple(items)
```

Verify the in-battle offsets against the constants: `wBattleMonSpecies 0xD014` + 1 = `wBattleMonHP 0xD015` ✓, + 4 = `0xD018` status ✓, + 5/6 types ✓, + 8 = `0xD01C` moves ✓, + 14 = `0xD022` level ✓, + 15 = `0xD023` max HP ✓, + 25 = `0xD02D` PP ✓; enemy: `0xCFE5` + 1 = `0xCFE6` ✓, + 4 = `0xCFE9` ✓, + 5/6 = `0xCFEA/B` ✓, + 8 = `0xCFED` ✓, + 14 = `0xCFF3` ✓, + 15 = `0xCFF4` ✓ (enemy PP at `0xCFFE` is not read).

In `GameState` add fields `party: tuple[Mon, ...]`, `active: Mon | None`, `enemy: Mon | None`, `battle: Battle | None`, `bag: tuple[BagItem, ...]` (after `bag_count`), and in `snapshot()`:

```python
    party = read_party(mem)
    battle = active = enemy = None
    if in_battle:
        kind = "trainer" if mem[ram.wIsInBattle] == 2 else "wild"
        trainer = trainer_class_name(mem[ram.wTrainerClass]) if kind == "trainer" else None
        battle = Battle(kind=kind, trainer_class=trainer)
        active = read_mon(mem, ram.wBattleMonSpecies, ram.wBattleMonNick, in_battle_layout=True)
        enemy = read_mon(mem, ram.wEnemyMonSpecies, ram.wEnemyMonNick, in_battle_layout=True)
```

`to_dict()`: `asdict` already recurses into nested dataclasses but keeps tuples; replace the method with:

```python
    def to_dict(self) -> dict:
        d = _listify(asdict(self))
        d["mode"] = str(self.mode)
        return d


def _listify(value):
    if isinstance(value, dict):
        return {k: _listify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_listify(v) for v in value]
    return value
```

(`_listify` is a module-level function defined after the dataclass; the method body references it at call time.)

- [ ] **Step 4: Run all snapshot tests**

Run: `uv run pytest tests/test_snapshot.py -q` then `mise exec -- uv run pytest tests/rom/test_snapshot.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/state/snapshot.py tests/support.py tests/test_snapshot.py tests/rom/test_snapshot.py
git commit -m "feat(state): party, active and enemy Pokémon, battle kind, and bag in GameState"
```

---

### Task 6: The battle brain: buckets, questions, decision, policy

**Files:**
- Create: `src/jevplays/brain/__init__.py` (empty), `src/jevplays/brain/buckets.py`, `src/jevplays/brain/decision.py`, `src/jevplays/brain/policy.py`, `src/jevplays/brain/battle.py`
- Test: `tests/test_buckets.py`, `tests/test_battle_brain.py`

**Interfaces:**
- `buckets.py`: `hp_bucket(hp, max_hp) -> str` (`full` at 100%, `healthy` > 60%, `hurt` > 30%, `low` > 10%, else `critical`); `pp_bucket(pp) -> str` (`out` 0, `low` <= 5, else `plenty`); `power_bucket(power) -> str` (`none` 0, `weak` < 50, `medium` < 80, else `strong`).
- `decision.py`: `@dataclass(frozen=True) BattleAction(kind: str, move: str | None = None, target: str | None = None)` with kinds `move`, `run`, `switch`, `heal`, `catch`; `@dataclass Decision(id: str, ts: float, kind: str, state_summary: dict, questions: dict[str, dict], answers: dict[str, dict], action: str, fallback: bool, fallback_reason: str, model: str, input_tokens: int, latency_ms: int)` with `to_dict()`. `answers[id]` is `{"primitive": "choice", "choice": ..., "probabilities": {...}, "confidence": ..., "applied": bool}` or `{"primitive": "noul", "noul": ..., "applied": bool}`. `questions[id]` is `{"primitive": ..., "instructions": str, "options": [..] }` (options empty for a Noul).
- `policy.py`: `HEAL_THRESHOLD = 0.7`, `CATCH_THRESHOLD = 0.6`, `RUN_THRESHOLD = 0.7`, `SWITCH_THRESHOLD = 0.7`; `choose_battle_action(answers: dict[str, dict], state_json: dict) -> tuple[BattleAction, list[str]]` returning the action and the ids of the answers it consumed.
- `battle.py`: `battle_state(state: GameState, goal: str) -> dict` (the JSON Jev sees), `battle_questions(state_json: dict) -> dict[str, dict]` (plain dicts in the SDK's `{"type": "choice", "instructions": ..., "criteria": {...}}` / `{"type": "noul", ...}` shape so no SDK import is needed), `decide_battle(state: GameState, state_json: dict, questions: dict, response: dict, *, model: str, input_tokens: int, latency_ms: int, supported: frozenset[str] = frozenset({"move", "run"})) -> Decision`. `response` is a `SystemOneResponse.model_dump()` dict: `{"model", "usage", "answers": {id: {"type": "choice"|"noul", ...}}}`. Unsupported action kinds fall back to the `move` answer with `fallback=True` and a reason.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_buckets.py
from jevplays.brain.buckets import hp_bucket, power_bucket, pp_bucket


def test_hp_buckets_follow_the_spec_thresholds():
    assert hp_bucket(19, 19) == "full"
    assert hp_bucket(12, 19) == "healthy"  # 63%
    assert hp_bucket(8, 19) == "hurt"  # 42%
    assert hp_bucket(3, 19) == "low"  # 15%
    assert hp_bucket(1, 19) == "critical"
    assert hp_bucket(0, 0) == "critical"


def test_pp_and_power_buckets():
    assert pp_bucket(0) == "out" and pp_bucket(5) == "low" and pp_bucket(6) == "plenty"
    assert power_bucket(0) == "none" and power_bucket(40) == "weak" and power_bucket(60) == "medium" and power_bucket(80) == "strong"
```

```python
# tests/test_battle_brain.py
import json
import re

from jevplays.brain.battle import battle_questions, battle_state, decide_battle
from jevplays.brain.decision import BattleAction
from jevplays.brain.policy import choose_battle_action
from jevplays.state.snapshot import BagItem, Battle, GameState, Mon, Move
from jevplays.state.modes import Mode

SCRATCH = Move(name="SCRATCH", type="Normal", power=40, pp=35, max_pp=35)
GROWL = Move(name="GROWL", type="Normal", power=0, pp=40, max_pp=40)
EMBER = Move(name="EMBER", type="Fire", power=40, pp=0, max_pp=25)
CHARMANDER = Mon(name="CHARMANDER", nickname="CHARMANDER", level=8, types=("Fire",), hp=8, max_hp=23, status="none", moves=(SCRATCH, GROWL, EMBER))
PIDGEY = Mon(name="PIDGEY", nickname="PIDGEY", level=4, types=("Normal", "Flying"), hp=17, max_hp=17, status="none", moves=(Move(name="GUST", type="Normal", power=40, pp=35, max_pp=35),))
BULBASAUR = Mon(name="BULBASAUR", nickname="BULBASAUR", level=5, types=("Grass", "Poison"), hp=15, max_hp=20, status="none", moves=())


def make_state(*, kind="wild", bench=(), bag=()):
    return GameState(
        mode=Mode.BATTLE_MENU, map_id=12, map="Route 1", tile=(9, 28), player_name="RED", party_count=1 + len(bench),
        badges=0, money=3000, bag_count=len(bag), in_battle=True, text="", menu_items=(), cursor=None,
        party=(CHARMANDER, *bench), active=CHARMANDER, enemy=BULBASAUR,
        battle=Battle(kind=kind, trainer_class=None if kind == "wild" else "RIVAL1"), bag=tuple(bag),
    )


def test_state_json_uses_words_not_numbers_for_hp_and_pp():
    s = battle_state(make_state(bag=(BagItem("POKE BALL", 3), BagItem("POTION", 1))), goal="Reach Viridian City")
    assert s["our_pokemon"]["hp"] == "hurt" and s["our_pokemon"]["level"] == 8
    assert s["our_pokemon"]["moves"][2] == {"name": "EMBER", "type": "Fire", "kind": "attack", "power": "weak", "pp": "out"}
    assert s["our_pokemon"]["moves"][1]["kind"] == "status"
    assert s["enemy_pokemon"] == {"name": "BULBASAUR", "level": 5, "types": ["Grass", "Poison"], "hp": "healthy"}
    assert s["battle"] == {"kind": "wild"} and s["bag"] == {"poke_balls": True, "potions": True} and s["goal"] == "Reach Viridian City"
    numbers = re.findall(r"\d+", json.dumps({k: v for k, v in s.items()}))
    assert numbers == ["8", "5"]  # only the two levels


def test_questions_include_only_what_can_apply():
    wild_alone = battle_questions(battle_state(make_state(), goal="g"))
    assert set(wild_alone) == {"move", "run"}  # no balls, no potions, no bench
    assert wild_alone["move"]["type"] == "choice"
    assert list(wild_alone["move"]["criteria"]) == ["SCRATCH", "GROWL"]  # EMBER is out of PP
    trainer_full = battle_questions(battle_state(make_state(kind="trainer", bench=(PIDGEY,), bag=(BagItem("POKE BALL", 1), BagItem("POTION", 1))), goal="g"))
    assert set(trainer_full) == {"move", "switch", "switch_to", "heal"}  # no run/catch in a trainer battle
    assert list(trainer_full["switch_to"]["criteria"]) == ["PIDGEY"]


def answers(**kw):
    out = {}
    for k, v in kw.items():
        if isinstance(v, dict):
            out[k] = {"type": "choice", "choice": max(v, key=v.get), "probabilities": v, "confidence": 0.5}
        else:
            out[k] = {"type": "noul", "noul": v}
    return out


def test_policy_order_heal_catch_run_switch_move():
    sj = {"our_pokemon": {"hp": "low"}, "battle": {"kind": "wild"}}
    a = answers(move={"SCRATCH": 0.9, "GROWL": 0.1}, heal=0.9, catch=0.9, run=0.9, switch=0.9, switch_to={"PIDGEY": 1.0})
    assert choose_battle_action(a, sj)[0] == BattleAction(kind="heal")
    a["heal"]["noul"] = 0.2
    assert choose_battle_action(a, sj)[0] == BattleAction(kind="catch")
    a["catch"]["noul"] = 0.2
    assert choose_battle_action(a, sj)[0] == BattleAction(kind="run")
    a["run"]["noul"] = 0.2
    assert choose_battle_action(a, sj)[0] == BattleAction(kind="switch", target="PIDGEY")
    a["switch"]["noul"] = 0.2
    action, used = choose_battle_action(a, sj)
    assert action == BattleAction(kind="move", move="SCRATCH") and used == ["move"]


def test_heal_needs_low_hp_not_just_a_yes():
    sj = {"our_pokemon": {"hp": "healthy"}, "battle": {"kind": "wild"}}
    a = answers(move={"SCRATCH": 1.0}, heal=0.95)
    assert choose_battle_action(a, sj)[0].kind == "move"


def test_decide_battle_marks_applied_answers_and_falls_back_for_unsupported_actions():
    state = make_state(kind="trainer", bench=(PIDGEY,))
    sj = battle_state(state, goal="g")
    qs = battle_questions(sj)
    response = {"model": "jev-1.13.0", "usage": {"input_tokens": 700, "output_tokens": 50},
                "answers": answers(move={"SCRATCH": 0.7, "GROWL": 0.3}, switch=0.9, switch_to={"PIDGEY": 1.0})}
    d = decide_battle(state, sj, qs, response, model="jev-1.13.0", input_tokens=700, latency_ms=400)
    assert d.kind == "battle" and d.model == "jev-1.13.0" and d.input_tokens == 700 and d.latency_ms == 400
    assert d.fallback is True and "switch" in d.fallback_reason
    assert d.action == "use SCRATCH"
    assert d.answers["switch"]["applied"] is True and d.answers["switch_to"]["applied"] is True and d.answers["move"]["applied"] is True
    assert d.questions["move"]["options"] == ["SCRATCH", "GROWL"]
    assert d.to_dict()["answers"]["move"]["probabilities"]["SCRATCH"] == 0.7


def test_decide_battle_plain_move():
    state = make_state()
    sj = battle_state(state, goal="g")
    qs = battle_questions(sj)
    response = {"model": "m", "usage": {"input_tokens": 1, "output_tokens": 1}, "answers": answers(move={"SCRATCH": 0.6, "GROWL": 0.4}, run=0.1)}
    d = decide_battle(state, sj, qs, response, model="m", input_tokens=1, latency_ms=1)
    assert d.fallback is False and d.action == "use SCRATCH"
    assert d.answers["run"]["applied"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_buckets.py tests/test_battle_brain.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'jevplays.brain'`

- [ ] **Step 3: Write the implementation**

```python
# src/jevplays/brain/buckets.py
"""Numbers to words. Jev is weak at arithmetic and strong at judgment, so code does the math."""


def hp_bucket(hp: int, max_hp: int) -> str:
    if max_hp <= 0 or hp <= 0:
        return "critical"
    fraction = hp / max_hp
    if fraction >= 1:
        return "full"
    if fraction > 0.6:
        return "healthy"
    if fraction > 0.3:
        return "hurt"
    if fraction > 0.1:
        return "low"
    return "critical"


def pp_bucket(pp: int) -> str:
    if pp <= 0:
        return "out"
    if pp <= 5:
        return "low"
    return "plenty"


def power_bucket(power: int) -> str:
    if power <= 0:
        return "none"
    if power < 50:
        return "weak"
    if power < 80:
        return "medium"
    return "strong"
```

```python
# src/jevplays/brain/decision.py
"""What the brain returns: the action to take and the full record of how it was chosen."""

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class BattleAction:
    kind: str  # move | run | switch | heal | catch
    move: str | None = None
    target: str | None = None

    def describe(self) -> str:
        return {
            "move": f"use {self.move}",
            "run": "run away",
            "switch": f"switch to {self.target}",
            "heal": "use a Potion",
            "catch": "throw a Poké Ball",
        }[self.kind]


@dataclass
class Decision:
    id: str
    ts: float
    kind: str
    state_summary: dict
    questions: dict[str, dict]
    answers: dict[str, dict]
    action: str
    fallback: bool = False
    fallback_reason: str = ""
    model: str = ""
    input_tokens: int = 0
    latency_ms: int = 0
    action_value: BattleAction | None = field(default=None, compare=False)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("action_value")
        return d
```

```python
# src/jevplays/brain/policy.py
"""The only place thresholds and priorities live. Raw answers stay in the Decision, so a threshold
change never needs a new request."""

from jevplays.brain.decision import BattleAction

HEAL_THRESHOLD = 0.7
CATCH_THRESHOLD = 0.6
RUN_THRESHOLD = 0.7
SWITCH_THRESHOLD = 0.7


def _noul(answers: dict[str, dict], key: str) -> float:
    a = answers.get(key)
    return a["noul"] if a and a.get("type") == "noul" else 0.0


def choose_battle_action(answers: dict[str, dict], state_json: dict) -> tuple[BattleAction, list[str]]:
    """Ordered rules; the first that fires wins. Returns the action and the answer ids it used."""
    hp = state_json.get("our_pokemon", {}).get("hp")
    if _noul(answers, "heal") > HEAL_THRESHOLD and hp in ("low", "critical"):
        return BattleAction(kind="heal"), ["heal"]
    if _noul(answers, "catch") > CATCH_THRESHOLD:
        return BattleAction(kind="catch"), ["catch"]
    if _noul(answers, "run") > RUN_THRESHOLD:
        return BattleAction(kind="run"), ["run"]
    if _noul(answers, "switch") > SWITCH_THRESHOLD and "switch_to" in answers:
        return BattleAction(kind="switch", target=answers["switch_to"]["choice"]), ["switch", "switch_to"]
    return BattleAction(kind="move", move=answers["move"]["choice"]), ["move"]
```

```python
# src/jevplays/brain/battle.py
"""The battle decision point: what Jev sees, what it is asked, and how its answers become a move.

Every question is one narrow judgment with its options spelled out, and questions that cannot
apply (RUN in a trainer battle, a Poké Ball with none in the bag) are not sent. All of them go in
one request; the policy consumes only the ones that apply.
"""

import time
import uuid

from jevplays.brain.buckets import hp_bucket, power_bucket, pp_bucket
from jevplays.brain.decision import BattleAction, Decision
from jevplays.brain.policy import choose_battle_action
from jevplays.state.snapshot import GameState, Mon


def _mon(mon: Mon, *, with_moves: bool) -> dict:
    d = {"name": mon.name, "level": mon.level, "types": list(mon.types), "hp": hp_bucket(mon.hp, mon.max_hp)}
    if with_moves:
        d["status"] = mon.status
        d["moves"] = [
            {"name": m.name, "type": m.type, "kind": "attack" if m.power > 0 else "status",
             "power": power_bucket(m.power), "pp": pp_bucket(m.pp)}
            for m in mon.moves
        ]
    return d


def battle_state(state: GameState, goal: str) -> dict:
    assert state.active is not None and state.enemy is not None and state.battle is not None
    bench = [m for m in state.party if not (m.nickname == state.active.nickname and m.name == state.active.name)]
    return {
        "our_pokemon": _mon(state.active, with_moves=True),
        "enemy_pokemon": _mon(state.enemy, with_moves=False),
        "battle": {"kind": state.battle.kind},
        "bench": [_mon(m, with_moves=False) for m in bench if m.hp > 0],
        "bag": {
            "poke_balls": any(item.name.endswith("BALL") and item.quantity > 0 for item in state.bag),
            "potions": any("POTION" in item.name and item.quantity > 0 for item in state.bag),
        },
        "goal": goal,
    }


def battle_questions(sj: dict) -> dict[str, dict]:
    usable = [m for m in sj["our_pokemon"]["moves"] if m["pp"] != "out"]
    if not usable:
        usable = sj["our_pokemon"]["moves"]
    qs: dict[str, dict] = {
        "move": {
            "type": "choice",
            "instructions": "Which move should `our_pokemon` use this turn to win the battle as quickly and safely as possible, given the types of both Pokémon?",
            "criteria": {m["name"]: f"{m['type']}-type {m['kind']}, {m['power']} power" for m in usable},
        }
    }
    if sj["bench"]:
        qs["switch"] = {
            "type": "noul",
            "instructions": "Should we switch out `our_pokemon` this turn instead of using a move?",
            "criteria": {"true": "A Pokémon in `bench` would clearly do better against `enemy_pokemon`, or `our_pokemon` is about to faint",
                         "false": "`our_pokemon` can keep fighting"},
        }
        qs["switch_to"] = {
            "type": "choice",
            "instructions": "If we switch, which Pokémon from `bench` should come in against `enemy_pokemon`?",
            "criteria": {m["name"]: f"{'/'.join(m['types'])} type, level {m['level']}, hp {m['hp']}" for m in sj["bench"]},
        }
    if sj["bag"]["potions"]:
        qs["heal"] = {"type": "noul", "instructions": "Should we use a Potion on `our_pokemon` this turn instead of attacking?"}
    if sj["battle"]["kind"] == "wild":
        qs["run"] = {"type": "noul", "instructions": "Should we run from this wild battle rather than fight it?"}
        if sj["bag"]["poke_balls"]:
            qs["catch"] = {
                "type": "noul",
                "instructions": "Should we throw a Poké Ball at `enemy_pokemon` this turn?",
                "criteria": {"true": "We want a party of at least three, `enemy_pokemon` is worth having, and its hp is low enough for a ball to work",
                             "false": "Its hp is still high, or it is not worth a ball"},
            }
    return qs


def _question_record(q: dict) -> dict:
    return {"primitive": q["type"], "instructions": q["instructions"],
            "options": list(q["criteria"]) if q["type"] == "choice" else []}


def _answer_record(a: dict) -> dict:
    if a["type"] == "choice":
        return {"primitive": "choice", "choice": a["choice"], "probabilities": dict(a["probabilities"]),
                "confidence": a["confidence"], "applied": False}
    return {"primitive": "noul", "noul": a["noul"], "applied": False}


def decide_battle(state: GameState, sj: dict, questions: dict, response: dict, *, model: str, input_tokens: int,
                  latency_ms: int, supported: frozenset[str] = frozenset({"move", "run"})) -> Decision:
    answers = {qid: _answer_record(a) for qid, a in response["answers"].items() if qid in questions}
    raw = {qid: a for qid, a in response["answers"].items() if qid in questions}
    fallback, reason = False, ""
    if "move" not in raw:
        first = next(iter(questions["move"]["criteria"]))
        action, used = BattleAction(kind="move", move=first), []
        fallback, reason = True, "the response had no move answer; using the first usable move"
    else:
        action, used = choose_battle_action(raw, sj)
        if action.kind not in supported:
            fallback, reason = True, f"{action.kind} is not executable yet; using the move answer instead"
            action = BattleAction(kind="move", move=raw["move"]["choice"])
            used = used + ["move"]
    for qid in used:
        if qid in answers:
            answers[qid]["applied"] = True
    return Decision(
        id=uuid.uuid4().hex[:12], ts=time.time(), kind="battle", state_summary=sj,
        questions={qid: _question_record(q) for qid, q in questions.items()}, answers=answers,
        action=action.describe(), fallback=fallback, fallback_reason=reason,
        model=model, input_tokens=input_tokens, latency_ms=latency_ms, action_value=action,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_buckets.py tests/test_battle_brain.py -q`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/brain tests/test_buckets.py tests/test_battle_brain.py
git commit -m "feat(brain): battle state, questions, policy, and the Decision record"
```

---

### Task 7: The TypeSafe client wrapper and recorded fixtures

**Files:**
- Modify: `pyproject.toml` (add `typesafe-sdk>=0.7` to dependencies), `uv.lock` (via `uv lock`)
- Create: `src/jevplays/brain/errors.py`, `src/jevplays/brain/client.py`, `Scripts/record-fixtures.py`, `tests/fixtures/__init__.py` (empty), `tests/fixtures/responses/battle_trainer.json`, `tests/fixtures/responses/battle_wild.json`
- Modify: `tests/test_imports.py` (also assert `typesafe_sdk` stays out of `sys.modules`)
- Test: `tests/test_client.py`, `tests/test_fixtures.py`

**Interfaces:**
- `errors.py`: `class BrainUnavailable(RuntimeError)` — its own module so `loop.py` can import it without importing the SDK.
- `client.py`: re-exports `BrainUnavailable`; `class Brain(model: str = "jev-latest", client=None)` with `async ask(state: dict, questions: dict[str, dict]) -> tuple[dict, int]` returning `(response.model_dump(), latency_ms)`; wraps `AsyncTypeSafeClient(model=...)`, converts the dict questions with `typesafe_sdk.Choice`/`Noul`, and raises `BrainUnavailable(str(error))` on `TypeSafeAPIError`, `TypeSafeAPIConnectionError`, `TypeSafeAPITimeoutError` after the SDK's own retries; `async close()`. Constructor accepts an injected client object with the same `system_one` coroutine for tests.
- `Scripts/record-fixtures.py`: for each of `battle_trainer`, `battle_wild`: load the state, `snapshot`, `battle_state(state, goal="Win the first battle")`, `battle_questions`, call `Brain.ask`, and write `{"state": state.to_dict(), "state_json": sj, "questions": qs, "response": response, "latency_ms": ms}` to `tests/fixtures/responses/<name>.json`. Committed.
- `tests/test_fixtures.py` replays each fixture through `decide_battle` and checks the decision is a move (no balls, no potions, no bench) and that the trainer fixture's move answer prefers an attack over GROWL.

- [ ] **Step 1: Add the dependency**

```bash
uv add "typesafe-sdk>=0.7"
```

Confirm `pyproject.toml` lists it under `dependencies` and `uv.lock` changed.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_client.py
import asyncio

import pytest

from jevplays.brain.client import Brain
from jevplays.brain.errors import BrainUnavailable


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def model_dump(self):
        return self._payload


class FakeClient:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    async def system_one(self, state, questions, **kwargs):
        self.calls.append((state, questions))
        if self.error:
            raise self.error
        return FakeResponse(self.payload)

    async def aclose(self):
        pass


PAYLOAD = {"model": "jev-1.13.0", "usage": {"input_tokens": 10, "output_tokens": 1},
           "answers": {"move": {"type": "choice", "choice": "SCRATCH", "probabilities": {"SCRATCH": 1.0}, "confidence": 1.0}}}
QUESTIONS = {"move": {"type": "choice", "instructions": "Which?", "criteria": {"SCRATCH": None}},
             "run": {"type": "noul", "instructions": "Run?", "criteria": {"true": "yes", "false": "no"}}}


def test_ask_converts_questions_and_returns_the_dump_and_latency():
    fake = FakeClient(payload=PAYLOAD)
    brain = Brain(client=fake)
    response, ms = asyncio.run(brain.ask({"x": 1}, QUESTIONS))
    assert response == PAYLOAD and ms >= 0
    state, questions = fake.calls[0]
    assert state == {"x": 1}
    assert type(questions["move"]).__name__ == "Choice" and type(questions["run"]).__name__ == "Noul"
    assert questions["move"].criteria == {"SCRATCH": None}


def test_api_errors_become_brain_unavailable():
    from typesafe_sdk import TypeSafeAPIConnectionError

    brain = Brain(client=FakeClient(error=TypeSafeAPIConnectionError("boom")))
    with pytest.raises(BrainUnavailable):
        asyncio.run(brain.ask({}, QUESTIONS))
```

```python
# tests/test_fixtures.py
import json
from pathlib import Path

import pytest

from jevplays.brain.battle import decide_battle
from jevplays.state.modes import Mode
from jevplays.state.snapshot import GameState

FIXTURES = Path(__file__).parent / "fixtures" / "responses"


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def rebuild(d: dict) -> GameState:
    from jevplays.state.snapshot import BagItem, Battle, Mon, Move

    def mon(m):
        return None if m is None else Mon(**{**m, "types": tuple(m["types"]), "moves": tuple(Move(**mv) for mv in m["moves"])})

    return GameState(**{**d, "mode": Mode(d["mode"]), "tile": tuple(d["tile"]), "menu_items": tuple(d["menu_items"]),
                        "party": tuple(mon(m) for m in d["party"]), "active": mon(d["active"]), "enemy": mon(d["enemy"]),
                        "battle": None if d["battle"] is None else Battle(**d["battle"]),
                        "bag": tuple(BagItem(**b) for b in d["bag"])})


@pytest.mark.parametrize("name", ["battle_trainer", "battle_wild"])
def test_recorded_response_decodes_to_a_move(name):
    f = load(name)
    d = decide_battle(rebuild(f["state"]), f["state_json"], f["questions"], f["response"],
                      model=f["response"]["model"], input_tokens=f["response"]["usage"]["input_tokens"], latency_ms=f["latency_ms"])
    assert d.action.startswith("use ") and d.fallback is False
    assert d.answers["move"]["applied"] is True
    assert set(d.questions) == set(f["questions"])


def test_trainer_fixture_prefers_an_attack_over_growl():
    f = load("battle_trainer")
    probs = f["response"]["answers"]["move"]["probabilities"]
    assert probs["SCRATCH"] > probs["GROWL"]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_client.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'jevplays.brain.client'`

- [ ] **Step 4: Write the error module, the client, and the recording script**

```python
# src/jevplays/brain/errors.py
"""Errors the loop reacts to. Kept SDK-free so loop.py never imports typesafe_sdk."""


class BrainUnavailable(RuntimeError):
    """TypeSafe could not answer after the SDK's own retries. The loop pauses, never presses."""
```

```python
# src/jevplays/brain/client.py
"""The only module that imports the TypeSafe SDK.

One request per decision point. The SDK retries transient failures itself; anything that still
fails becomes BrainUnavailable so the loop can pause and show it, never press a random button.
"""

import time

from typesafe_sdk import (
    AsyncTypeSafeClient,
    Choice,
    Noul,
    TypeSafeAPIConnectionError,
    TypeSafeAPIError,
    TypeSafeAPITimeoutError,
)

from jevplays.brain.errors import BrainUnavailable

__all__ = ["Brain", "BrainUnavailable", "to_sdk_questions"]


def to_sdk_questions(questions: dict[str, dict]) -> dict:
    out = {}
    for qid, q in questions.items():
        if q["type"] == "choice":
            out[qid] = Choice(instructions=q["instructions"], criteria=q["criteria"])
        elif q["type"] == "noul":
            out[qid] = Noul(instructions=q["instructions"], criteria=q.get("criteria"))
        else:
            raise ValueError(f"unsupported question type {q['type']!r} for {qid}")
    return out


class Brain:
    def __init__(self, model: str = "jev-latest", client=None) -> None:
        self.model = model
        self._client = client if client is not None else AsyncTypeSafeClient(model=model)

    async def ask(self, state: dict, questions: dict[str, dict]) -> tuple[dict, int]:
        started = time.monotonic()
        try:
            response = await self._client.system_one(state, to_sdk_questions(questions))
        except (TypeSafeAPIError, TypeSafeAPIConnectionError, TypeSafeAPITimeoutError) as error:
            raise BrainUnavailable(str(error)) from error
        return response.model_dump(), int((time.monotonic() - started) * 1000)

    async def close(self) -> None:
        await self._client.aclose()
```

(`AsyncTypeSafeClient.aclose` is the SDK's close coroutine, verified on 0.7.0; the test fake implements the same name.)

```python
#!/usr/bin/env -S uv run
# Scripts/record-fixtures.py
"""Record real TypeSafe responses for the battle save states, for the unit tests to replay.

    mise exec -- uv run Scripts/record-fixtures.py

Needs JEVPLAYS_ROM, states/battle_trainer.state, states/battle_wild.state, and TYPESAFE_API_KEY.
Writes tests/fixtures/responses/<name>.json. Re-run when the questions change; commit the result.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from jevplays.brain.battle import battle_questions, battle_state
from jevplays.brain.client import Brain
from jevplays.emulator.pyboy import Emulator
from jevplays.state.snapshot import snapshot

OUT = Path("tests/fixtures/responses")
GOAL = "Win the first battle"


async def record(rom: Path, states: Path) -> None:
    brain = Brain()
    try:
        for name in ("battle_trainer", "battle_wild"):
            with Emulator(rom) as emu:
                emu.load(states / f"{name}.state")
                state = snapshot(emu)
            sj = battle_state(state, goal=GOAL)
            qs = battle_questions(sj)
            response, ms = await brain.ask(sj, qs)
            OUT.mkdir(parents=True, exist_ok=True)
            (OUT / f"{name}.json").write_text(json.dumps(
                {"state": state.to_dict(), "state_json": sj, "questions": qs, "response": response, "latency_ms": ms},
                indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            move = response["answers"]["move"]
            print(f"{name}: {move['choice']} {move['probabilities']} confidence {move['confidence']} in {ms} ms")
    finally:
        await brain.close()


def main() -> int:
    rom = os.environ.get("JEVPLAYS_ROM")
    if not rom or not os.environ.get("TYPESAFE_API_KEY"):
        print("need JEVPLAYS_ROM and TYPESAFE_API_KEY", file=sys.stderr)
        return 2
    asyncio.run(record(Path(rom), Path(os.environ.get("JEVPLAYS_STATES", "states"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Record the fixtures and run the tests**

Run: `mise exec -- uv run Scripts/record-fixtures.py`
Expected: two lines like `battle_trainer: SCRATCH {...} confidence ... in ... ms`. Then:

Run: `uv run pytest tests/test_client.py tests/test_fixtures.py -q`
Expected: `5 passed`. If `test_trainer_fixture_prefers_an_attack_over_growl` fails, the model chose GROWL: report it (that is a real finding about the question wording), do not edit the assertion.

Then extend `tests/test_imports.py`: the subprocess must also assert `"typesafe_sdk" not in sys.modules` after importing `jevplays.loop`, `jevplays.cli`, `jevplays.state.snapshot`, and `jevplays.dashboard.server`. Run `uv run pytest tests/test_imports.py -q` and confirm it passes.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/jevplays/brain/errors.py src/jevplays/brain/client.py Scripts/record-fixtures.py tests/fixtures tests/test_client.py tests/test_fixtures.py tests/test_imports.py
git commit -m "feat(brain): TypeSafe client wrapper and recorded battle responses for the tests"
```

---

### Task 8: Battle macros

**Files:**
- Create: `src/jevplays/executor/battle.py`
- Test: `tests/test_battle_macros.py`, `tests/rom/test_battle_macros.py`

**Interfaces:**
- Produces: `class MacroError(RuntimeError)`; `select_command(emu, label: str) -> None` (at the command menu: navigate the 2x2 grid until `cursor_label` starts with `label`, then A; `label` in `FIGHT`, `PKMN`, `ITEM`, `RUN`); `select_move(emu, name: str) -> None` (after FIGHT: press down until the cursor label is `name`, bounded by 4, then A; B and `MacroError` if never found); `run_away(emu) -> None`; `apply(emu, action: BattleAction) -> None` (`move` → FIGHT then the move; `run` → RUN; any other kind raises `MacroError("unsupported")`). All macros read the screen through `rows_of(emu.tilemap())` and `cursor_label`, and every A press is preceded by a label check.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_battle_macros.py
import pytest

from jevplays.brain.decision import BattleAction
from jevplays.executor.battle import MacroError, apply, select_command, select_move
from tests.support import FakeEmulator

MENU = [""] * 14 + ["·       ·▶FIGHT PK·", "", "·       · ITEM RUN·"]
MENU_PKMN = [""] * 14 + ["·       · FIGHT▶PKMN", "", "·       · ITEM RUN·"]
MENU_RUN = [""] * 14 + ["·       · FIGHT PK·", "", "·       · ITEM▶RUN·"]
MOVES = [""] * 13 + ["·   ·▶SCRATCH      ·", "·   · GROWL        ·", "·   · -            ·", "·   · -            ·"]
MOVES_GROWL = [""] * 13 + ["·   · SCRATCH      ·", "·   ·▶GROWL        ·", "·   · -            ·", "·   · -            ·"]


class ScriptedEmulator(FakeEmulator):
    """Each press advances a script of screens so macros can be tested without a ROM."""

    def __init__(self, screens):
        super().__init__()
        self.step_effects = {}
        self.screens = list(screens)
        self.set_rows(self.screens.pop(0))

    def press(self, button, *, hold=8, settle=8):
        super().press(button, hold=hold, settle=settle)
        if self.screens:
            self.set_rows(self.screens.pop(0))
        return hold + settle


def test_select_command_moves_the_cursor_then_presses_a():
    emu = ScriptedEmulator([MENU, MENU_PKMN, MENU_RUN, MENU_RUN])  # right -> PKMN, down -> RUN, then A
    select_command(emu, "RUN")
    assert emu.presses == ["right", "down", "a"]


def test_select_move_scrolls_to_the_named_move():
    emu = ScriptedEmulator([MOVES, MOVES_GROWL, MOVES_GROWL])
    select_move(emu, "GROWL")
    assert emu.presses == ["down", "a"]


def test_select_move_fails_closed_when_the_move_is_missing():
    emu = ScriptedEmulator([MOVES] * 8)
    with pytest.raises(MacroError):
        select_move(emu, "EMBER")
    assert emu.presses[-1] == "b"


def test_apply_move_goes_through_fight():
    emu = ScriptedEmulator([MENU, MOVES, MOVES, MOVES])
    apply(emu, BattleAction(kind="move", move="SCRATCH"))
    assert emu.presses == ["a", "a"]


def test_apply_rejects_unsupported_kinds():
    emu = ScriptedEmulator([MENU])
    with pytest.raises(MacroError):
        apply(emu, BattleAction(kind="switch", target="PIDGEY"))
```

```python
# tests/rom/test_battle_macros.py
from jevplays.brain.decision import BattleAction
from jevplays.emulator import ram
from jevplays.emulator.pyboy import Emulator
from jevplays.executor.battle import apply
from jevplays.state.snapshot import rows_of


def test_apply_move_uses_the_chosen_move(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("battle_trainer"))
        apply(emu, BattleAction(kind="move", move="GROWL"))
        emu.tick(60)
        seen = " ".join("".join(r) for r in rows_of(emu.tilemap())[13:17])
        assert "GROWL" in seen


def test_run_away_from_a_wild_battle(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("battle_wild"))
        apply(emu, BattleAction(kind="run"))
        for _ in range(60):
            if emu.mem[ram.wIsInBattle] == 0:
                break
            emu.press("a", settle=20)
        assert emu.mem[ram.wIsInBattle] == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_battle_macros.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'jevplays.executor.battle'`

- [ ] **Step 3: Write the implementation**

```python
# src/jevplays/executor/battle.py
"""Button macros for the battle screens. Every A is preceded by reading the cursor's label."""

from jevplays.brain.decision import BattleAction
from jevplays.executor.dialog import cursor_label
from jevplays.state.snapshot import rows_of

COMMANDS = {"FIGHT": (0, 0), "PKMN": (0, 1), "ITEM": (1, 0), "RUN": (1, 1)}
"""(row, column) of each command in the 2x2 battle menu. The PKMN command is drawn as the two
glyph tiles PK and MN, which decode to "PK" and "MN" and join as "PKMN"."""


class MacroError(RuntimeError):
    pass


def _label(emu) -> str | None:
    return cursor_label(rows_of(emu.tilemap()))


def select_command(emu, label: str) -> None:
    if label not in COMMANDS:
        raise MacroError(f"unknown battle command {label!r}")
    target_row, target_col = COMMANDS[label]
    for _ in range(6):
        current = _label(emu)
        if current is not None and current.startswith(label):
            emu.press("a", settle=40)
            return
        here = next((pos for name, pos in COMMANDS.items() if current and current.startswith(name)), None)
        if here is None:
            raise MacroError(f"not at the battle menu; cursor reads {current!r}")
        row, col = here
        if col != target_col:
            emu.press("right" if target_col > col else "left", settle=16)
        elif row != target_row:
            emu.press("down" if target_row > row else "up", settle=16)
    raise MacroError(f"could not reach {label!r}")


def select_move(emu, name: str) -> None:
    for _ in range(4):
        current = _label(emu)
        if current == name:
            emu.press("a", settle=20)
            return
        emu.press("down", settle=16)
    emu.press("b", settle=20)
    raise MacroError(f"move {name!r} is not in the list")


def run_away(emu) -> None:
    select_command(emu, "RUN")


def apply(emu, action: BattleAction) -> None:
    if action.kind == "move":
        select_command(emu, "FIGHT")
        select_move(emu, action.move)
    elif action.kind == "run":
        run_away(emu)
    else:
        raise MacroError(f"unsupported action {action.kind!r}")
```

The move list's cursor label reads the move name exactly (`SCRATCH`), and the command menu's reads `FIGHT PKMN` (the cursor on FIGHT has the PKMN glyphs to its right on the same row), `PKMN`, `ITEM RUN`, or `RUN`; `startswith` tolerates the trailing text.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_battle_macros.py -q` then `mise exec -- uv run pytest tests/rom/test_battle_macros.py -q`
Expected: `5 passed` then `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/executor/battle.py tests/test_battle_macros.py tests/rom/test_battle_macros.py
git commit -m "feat(executor): battle macros that verify the cursor label before every press"
```

---

### Task 9: Brain in the loop, decision event, API backoff, CLI wiring

**Files:**
- Modify: `src/jevplays/loop.py`, `src/jevplays/cli.py`, `src/jevplays/dashboard/events.py`
- Test: `tests/test_loop.py`, `tests/test_events.py`, `tests/test_cli.py`

**Interfaces:**
- `events.py`: `decision_event(decision: Decision) -> dict` → `{"type": "decision", "decision": decision.to_dict()}`.
- `loop.py`: `LoopConfig` gains `goal: str = "Win every battle and explore"`, `backoff_max: float = 30.0`; `Loop(emu, broadcaster, config=None, brain=None)`; `advance` becomes `async def advance(state) -> int`; at `BATTLE_MENU` with a brain: build `battle_state`/`battle_questions`, `await brain.ask`, `decide_battle`, publish `decision_event`, `executor.battle.apply`; on `BrainUnavailable` publish `status_event("waiting_for_api", message)`, sleep with doubling backoff capped at `backoff_max`, and retry the same decision on the next iteration (no button pressed); on `MacroError` publish a `status_event("running", f"macro failed: ...")`, press B once, and continue. `Loop.decisions: list[Decision]` keeps every decision of the run. Without a brain, `BATTLE_MENU` idles as in milestone 1.
- `cli.py`: `run` gains `--no-brain` and `--goal TEXT`; a brain is created when `TYPESAFE_API_KEY` is set and `--no-brain` is absent, else the run prints `brain: off (no TYPESAFE_API_KEY)` and idles at decision points. The brain is closed on shutdown.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_events.py`:

```python
def test_decision_event_wraps_the_record():
    from jevplays.brain.decision import Decision
    from jevplays.dashboard.events import decision_event

    d = Decision(id="abc", ts=1.0, kind="battle", state_summary={}, questions={}, answers={}, action="use SCRATCH")
    ev = decision_event(d)
    assert ev["type"] == "decision" and ev["decision"]["action"] == "use SCRATCH" and "action_value" not in ev["decision"]
```

Append to `tests/test_loop.py`:

```python
from jevplays.brain.client import BrainUnavailable
from jevplays.emulator import ram
from tests.support import write_mon

BATTLE_MENU = [""] * 14 + ["·       ·▶FIGHT PK·", "", "·       · ITEM RUN·"]
MOVES = [""] * 13 + ["·   ·▶SCRATCH      ·", "·   · GROWL        ·", "·   · -            ·", "·   · -            ·"]


class FakeBrain:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = 0

    async def ask(self, state, questions):
        self.calls += 1
        if self.error:
            raise self.error
        return self.response, 12


def battle_emu():
    emu = FakeEmulator()
    emu.step_effects = {}
    emu.mem[ram.wIsInBattle] = 1
    write_mon(emu.mem, ram.wPartyMons, ram.wPartyMonNicks, species=176, level=5, hp=19, max_hp=19, types=(20, 20), moves=(10, 45), pps=(35, 40), nickname="CHARMANDER")
    emu.mem[ram.wPartyCount] = 1
    write_mon(emu.mem, ram.wBattleMonSpecies, ram.wBattleMonNick, species=176, level=5, hp=19, max_hp=19, types=(20, 20), moves=(10, 45), pps=(35, 40), nickname="CHARMANDER", layout="battle")
    write_mon(emu.mem, ram.wEnemyMonSpecies, ram.wEnemyMonNick, species=165, level=3, hp=14, max_hp=14, types=(0, 0), moves=(33,), pps=(35,), nickname="RATTATA", layout="battle")
    emu.set_rows(BATTLE_MENU)
    return emu


RESPONSE = {"model": "jev-1.13.0", "usage": {"input_tokens": 500, "output_tokens": 10},
            "answers": {"move": {"type": "choice", "choice": "SCRATCH", "probabilities": {"SCRATCH": 0.8, "GROWL": 0.2}, "confidence": 0.6},
                        "run": {"type": "noul", "noul": 0.1}}}


def test_battle_menu_asks_the_brain_publishes_the_decision_and_presses_the_move():
    emu = battle_emu()
    presses = []
    original = emu.press

    def press(button, **kw):
        presses.append(button)
        r = original(button, **kw)
        if presses == ["a"]:
            emu.set_rows(MOVES)  # FIGHT opened the move list
        return r

    emu.press = press
    bc = RecordingBroadcaster()
    brain = FakeBrain(response=RESPONSE)
    loop = Loop(emu, bc, LoopConfig(paced=False), brain=brain)
    asyncio.run(loop.run(max_iterations=1))
    assert brain.calls == 1
    assert [e["type"] for e in bc.events][:3] == ["state", "frame", "decision"]
    assert bc.events[2]["decision"]["action"] == "use SCRATCH"
    assert presses == ["a", "a"]
    assert loop.decisions[0].answers["run"]["applied"] is False


def test_api_failure_pauses_with_status_and_presses_nothing():
    emu = battle_emu()
    bc = RecordingBroadcaster()
    loop = Loop(emu, bc, LoopConfig(paced=False, backoff_max=0.01), brain=FakeBrain(error=BrainUnavailable("503")))
    asyncio.run(loop.run(max_iterations=2))
    statuses = [e for e in bc.events if e["type"] == "status"]
    assert statuses and statuses[0]["status"] == "waiting_for_api" and "503" in statuses[0]["message"]
    assert emu.presses == []


def test_without_a_brain_the_battle_menu_idles():
    emu = battle_emu()
    loop = Loop(emu, RecordingBroadcaster(), LoopConfig(paced=False, idle_frames=9))
    asyncio.run(loop.run(max_iterations=1))
    assert emu.presses == [] and emu.frames >= 9
```

Append to `tests/test_cli.py`:

```python
def test_run_help_lists_the_brain_flags(capsys):
    import pytest

    with pytest.raises(SystemExit):
        main(["run", "--help"])
    out = capsys.readouterr().out
    assert "--no-brain" in out and "--goal" in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_events.py tests/test_loop.py tests/test_cli.py -q`
Expected: FAIL (`ImportError: cannot import name 'decision_event'`, then `TypeError: Loop.__init__() got an unexpected keyword argument 'brain'`).

- [ ] **Step 3: Write the implementation**

`events.py`:

```python
from jevplays.brain.decision import Decision


def decision_event(decision: Decision) -> dict:
    return {"type": "decision", "decision": decision.to_dict()}
```

`loop.py` (replace the class; keep the module docstring, updating "Milestone 1 advances the game without deciding anything" to say the battle menu now asks the brain and the other decision points still idle until milestone 3):

```python
import asyncio
from dataclasses import dataclass, field
from itertools import count
from time import monotonic

from jevplays.brain.battle import battle_questions, battle_state, decide_battle
from jevplays.brain.decision import Decision
from jevplays.brain.errors import BrainUnavailable
from jevplays.dashboard.events import decision_event, frame_event, state_event, status_event
from jevplays.executor import battle as battle_macros
from jevplays.executor.battle import MacroError
from jevplays.state.modes import Mode
from jevplays.state.snapshot import GameState, snapshot

FRAMES_PER_SECOND = 60


@dataclass
class LoopConfig:
    fps: float = 15.0
    idle_frames: int = 30
    paced: bool = True
    goal: str = "Win every battle and explore"
    backoff_max: float = 30.0


class Loop:
    def __init__(self, emu, broadcaster, config: LoopConfig | None = None, brain=None) -> None:
        self.emu = emu
        self.broadcaster = broadcaster
        self.config = config or LoopConfig()
        self.brain = brain
        self.decisions: list[Decision] = []
        self._backoff = min(1.0, self.config.backoff_max)

    async def advance(self, state: GameState) -> int:
        if state.mode in (Mode.DIALOG, Mode.BATTLE_WAIT):
            return self.emu.press("a", settle=30)
        if state.mode is Mode.TRANSITION:
            return self.emu.tick(30)
        if state.mode is Mode.BATTLE_MENU and self.brain is not None:
            return await self._battle_turn(state)
        return self.emu.tick(self.config.idle_frames)

    async def _battle_turn(self, state: GameState) -> int:
        sj = battle_state(state, goal=self.config.goal)
        questions = battle_questions(sj)
        try:
            response, latency_ms = await self.brain.ask(sj, questions)
        except BrainUnavailable as error:
            await self.broadcaster.publish(status_event("waiting_for_api", f"TypeSafe unavailable: {error}; retrying in {self._backoff:.0f}s"))
            await asyncio.sleep(self._backoff)
            self._backoff = min(self._backoff * 2, self.config.backoff_max)
            return 0
        self._backoff = min(1.0, self.config.backoff_max)
        decision = decide_battle(state, sj, questions, response, model=response.get("model", ""),
                                 input_tokens=response.get("usage", {}).get("input_tokens", 0), latency_ms=latency_ms)
        self.decisions.append(decision)
        await self.broadcaster.publish(decision_event(decision))
        await self.broadcaster.publish(status_event("running", decision.action))
        try:
            battle_macros.apply(self.emu, decision.action_value)
        except MacroError as error:
            await self.broadcaster.publish(status_event("running", f"macro failed: {error}"))
            return self.emu.press("b", settle=20)
        return self.emu.tick(30)

    async def run(self, max_iterations: int | None = None) -> None:
        started = monotonic()
        emulated = 0
        last_frame_at = float("-inf")
        last_state: GameState | None = None
        for i in count():
            if max_iterations is not None and i >= max_iterations:
                return
            state = snapshot(self.emu)
            if state != last_state:
                await self.broadcaster.publish(state_event(state))
                last_state = state
            now = monotonic()
            if now - last_frame_at >= 1 / self.config.fps:
                await self.broadcaster.publish(frame_event(self.emu.frame_jpeg()))
                last_frame_at = now
            emulated += await self.advance(state)
            if self.config.paced:
                due = started + emulated / FRAMES_PER_SECOND
                await asyncio.sleep(max(0.0, due - monotonic()))
            else:
                await asyncio.sleep(0)
```

Note `apply` in `_battle_turn` is not `await`ed (macros are synchronous) and the frame budget after a decision counts the macro's presses only approximately (30 frames); milestone 3's run logging will make the accounting exact. Also remove the now-unused `field` import if ruff flags it.

`cli.py` `cmd_run`: add the flags in `build_parser` (`run.add_argument("--no-brain", action="store_true", help="never call TypeSafe; idle at decision points")`, `run.add_argument("--goal", default=LoopConfig().goal)`), and in `main_async` build the brain:

```python
        brain = None
        if not args.no_brain and os.environ.get("TYPESAFE_API_KEY"):
            from jevplays.brain.client import Brain

            brain = Brain()
            print("brain: jev-latest", flush=True)
        else:
            print("brain: off" + ("" if args.no_brain else " (no TYPESAFE_API_KEY)"), flush=True)
```

Pass `brain=brain` and `LoopConfig(paced=not args.unpaced, goal=args.goal)` to `Loop`, and in the `finally` close the brain (`if brain is not None: await brain.close()`). Import `LoopConfig` lazily with the other loop imports.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_events.py tests/test_loop.py tests/test_cli.py tests/test_imports.py -q`
Expected: all pass, including the import-boundary test: `loop.py` imports `BrainUnavailable` from `jevplays.brain.errors`, never from `client.py`, so `typesafe_sdk` stays out of `sys.modules` for a run without a brain.

- [ ] **Step 5: Run it for real**

Run in the background: `mise exec -- uv run jevplays run --state states/battle_wild.state --port 8765`, wait 10 s, then check the websocket or the page: a `decision` event with `action` `use SCRATCH` or `run away` and probabilities for `move`, and the game proceeds past the menu. Then stop it (`pkill -f "jevplays run"`) and record the stdout lines in the report.

- [ ] **Step 6: Commit**

```bash
git add src/jevplays/loop.py src/jevplays/cli.py src/jevplays/dashboard/events.py tests/test_events.py tests/test_loop.py tests/test_cli.py
git commit -m "feat(loop): ask Jev at the battle menu, publish the decision, and back off when the API is down"
```

---

### Task 10: The decision panel, party strip, and decision log on the dashboard

**Files:**
- Modify: `src/jevplays/dashboard/static/index.html`, `app.js`, `styles.css`
- Test: `tests/test_server.py` (static files still served), plus a manual check

**Interfaces:**
- Consumes the `decision` event from Task 9 and `state.party` from Task 5.
- Produces the layout from spec section 10: right column shows the latest decision (one bar per Choice option with the winner highlighted and the probability as a label; each Noul as a yes/no split bar; a confidence badge per Choice; questions whose `applied` is false dimmed and labelled "not applicable"; the action in words; latency and input tokens small at the bottom; a "fallback" tag when `fallback` is true); below it the current goal (from the decision's `state_summary.goal`), a party strip (nickname, level, HP bar coloured by bucket: green > 60%, amber > 30%, orange > 10%, red), and a scrolling log of the last 50 decisions (kind, action, top confidence). The milestone 1 "State" summary and "Raw" block stay, below the log, collapsed by default under a `<details>`.

- [ ] **Step 1: Update the page**

Replace the `<main>` in `index.html` with:

```html
  <main>
    <section class="screen">
      <img id="screen" width="640" height="576" alt="Game screen" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7">
      <div class="party" id="party"></div>
    </section>
    <section class="panel">
      <h2>Decision</h2>
      <div id="decision" class="decision"><p class="muted">waiting for the first decision…</p></div>
      <h2>Goal</h2>
      <p id="goal">–</p>
      <h2>Log</h2>
      <ol id="log" class="log"></ol>
      <details>
        <summary>State</summary>
        <dl id="summary">
          <dt>Mode</dt><dd id="mode">–</dd>
          <dt>Map</dt><dd id="map">–</dd>
          <dt>Text</dt><dd id="text">–</dd>
          <dt>Menu</dt><dd id="menu">–</dd>
        </dl>
        <pre id="state">waiting for the first snapshot…</pre>
      </details>
    </section>
  </main>
```

In `app.js`, keep the existing handlers and add:

```js
const decisionEl = document.getElementById("decision");
const goalEl = document.getElementById("goal");
const logEl = document.getElementById("log");
const partyEl = document.getElementById("party");

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function pct(p) { return `${Math.round(p * 100)}%`; }

function renderChoice(id, q, a) {
  const box = el("div", `question${a.applied ? "" : " unused"}`);
  const head = el("div", "qhead");
  head.append(el("span", "qid", id), el("span", "badge", `confidence ${a.confidence.toFixed(2)}`));
  if (!a.applied) head.append(el("span", "badge na", "not applicable"));
  box.append(head, el("p", "instructions", q.instructions));
  const options = Object.entries(a.probabilities).sort((x, y) => y[1] - x[1]);
  for (const [name, p] of options) {
    const row = el("div", `bar${name === a.choice ? " winner" : ""}`);
    const fill = el("div", "fill");
    fill.style.width = pct(p);
    row.append(el("span", "label", name), fill, el("span", "value", pct(p)));
    box.append(row);
  }
  return box;
}

function renderNoul(id, q, a) {
  const box = el("div", `question${a.applied ? "" : " unused"}`);
  const head = el("div", "qhead");
  head.append(el("span", "qid", id));
  if (!a.applied) head.append(el("span", "badge na", "not applicable"));
  box.append(head, el("p", "instructions", q.instructions));
  const row = el("div", "split");
  const yes = el("div", "yes", `yes ${pct(a.noul)}`);
  yes.style.width = pct(a.noul);
  const no = el("div", "no", `no ${pct(1 - a.noul)}`);
  no.style.width = pct(1 - a.noul);
  row.append(yes, no);
  box.append(row);
  return box;
}

function renderDecision(d) {
  decisionEl.replaceChildren();
  const action = el("div", "action", d.action);
  if (d.fallback) action.append(el("span", "badge fallback", `fallback: ${d.fallback_reason}`));
  decisionEl.append(action);
  for (const [id, q] of Object.entries(d.questions)) {
    const a = d.answers[id];
    if (!a) continue;
    decisionEl.append(a.primitive === "choice" ? renderChoice(id, q, a) : renderNoul(id, q, a));
  }
  decisionEl.append(el("p", "meta", `${d.model} · ${d.latency_ms} ms · ${d.input_tokens} tokens`));
  goalEl.textContent = d.state_summary.goal || "–";
  const top = d.answers.move ? ` (${d.answers.move.confidence.toFixed(2)})` : "";
  const item = el("li", "", `${d.kind}: ${d.action}${top}`);
  logEl.prepend(item);
  while (logEl.children.length > 50) logEl.lastChild.remove();
}

function hpClass(hp, max) {
  const f = max ? hp / max : 0;
  return f > 0.6 ? "hp-healthy" : f > 0.3 ? "hp-hurt" : f > 0.1 ? "hp-low" : "hp-critical";
}

function renderParty(party) {
  partyEl.replaceChildren();
  for (const mon of party) {
    const card = el("div", "mon");
    card.append(el("div", "name", `${mon.nickname} L${mon.level}`));
    const bar = el("div", "hpbar");
    const fill = el("div", `hpfill ${hpClass(mon.hp, mon.max_hp)}`);
    fill.style.width = mon.max_hp ? pct(mon.hp / mon.max_hp) : "0%";
    bar.append(fill);
    card.append(bar, el("div", "hp", `${mon.hp}/${mon.max_hp}${mon.status !== "none" ? " · " + mon.status : ""}`));
    partyEl.append(card);
  }
}
```

and in `ws.onmessage`: on `state` also call `renderParty(s.party || [])`; add `else if (event.type === "decision") renderDecision(event.decision);`.

Add to `styles.css`:

```css
.party { display: flex; gap: 10px; margin-top: 10px; flex-wrap: wrap; }
.mon { background: var(--panel); border-radius: 6px; padding: 8px 10px; min-width: 150px; }
.mon .name { font-weight: 600; }
.hpbar { height: 8px; background: #262a33; border-radius: 4px; margin: 6px 0 4px; overflow: hidden; }
.hpfill { height: 100%; }
.hp-healthy { background: var(--accent); }
.hp-hurt { background: var(--warn); }
.hp-low { background: #f2994a; }
.hp-critical { background: var(--stop); }
.mon .hp { color: var(--muted); font-size: 13px; }
.decision .action { font-size: 17px; font-weight: 600; margin: 8px 0 12px; }
.question { border-top: 1px solid #262a33; padding: 10px 0; }
.question.unused { opacity: .45; }
.qhead { display: flex; gap: 8px; align-items: center; }
.qid { font-weight: 600; }
.badge { font-size: 11px; padding: 2px 8px; border-radius: 999px; background: #262a33; color: var(--muted); }
.badge.na { background: #3a3f4b; }
.badge.fallback { background: var(--warn); color: #0f1115; margin-left: 8px; }
.instructions { color: var(--muted); font-size: 13px; margin: 4px 0 8px; }
.bar { display: grid; grid-template-columns: 110px 1fr 48px; align-items: center; gap: 8px; margin: 3px 0; }
.bar .fill { height: 14px; background: #3a3f4b; border-radius: 3px; }
.bar.winner .fill { background: var(--accent); }
.bar.winner .label { font-weight: 600; }
.bar .value { text-align: right; color: var(--muted); font-size: 13px; }
.split { display: flex; height: 18px; border-radius: 3px; overflow: hidden; font-size: 12px; }
.split .yes { background: var(--accent); color: #0f1115; padding-left: 6px; white-space: nowrap; overflow: hidden; }
.split .no { background: #3a3f4b; color: var(--text); padding-left: 6px; white-space: nowrap; overflow: hidden; }
.meta { color: var(--muted); font-size: 12px; margin-top: 10px; }
.log { margin: 0; padding-left: 20px; max-height: 240px; overflow: auto; color: var(--muted); font-size: 13px; }
details summary { cursor: pointer; color: var(--muted); margin-top: 12px; }
.muted { color: var(--muted); }
```

- [ ] **Step 2: Check the page renders a decision**

Run: `uv run pytest tests/test_server.py -q` (static routes still 200). Then run `mise exec -- uv run jevplays run --state states/battle_wild.state --port 8765` in the background and, with a websocket client or browser, confirm the page shows the decision panel with bars for `move`, a yes/no split for `run`, the party strip with CHARMANDER, and a log entry. Capture a screenshot if a browser is available; otherwise fetch `/` and confirm the new element ids are present. Stop the process afterwards.

- [ ] **Step 3: Commit**

```bash
git add src/jevplays/dashboard/static
git commit -m "feat(dashboard): decision panel with probability bars, party strip, and decision log"
```

---

### Task 11: Spec amendments, docs, full check, PR

**Files:**
- Modify: `docs/superpowers/specs/2026-09-20-jevplays-design.md`, `README.md`, `CLAUDE.md`

- [ ] **Step 1: Amend the spec**

Section 6: after the `GameState` block, replace "Buckets are computed in code from the raw numbers, following the jaggedness guidance to give Jev words rather than numbers." with: "`GameState` carries raw numbers (HP, PP, money) because it is the harness's record of the truth; the brain's builders convert them to bucket words at its own boundary (`brain/buckets.py`), and a test asserts the JSON sent to Jev carries no HP, PP, or money numbers. Levels are sent as numbers." Adjust the `GameState` listing: `party: [Mon]` fields become `name, nickname, level, types, hp, max_hp, status, moves: [Move]`; `Move: name, type, power, pp, max_pp`; drop `hp_bucket`, `pp_bucket`, `power_bucket` from the listing and note they are the brain's vocabulary.

Section 14, milestone 2: add "and the executor's window pathfinder (`executor/navigate.py`), delivered early because the save-state script needs to reach a battle; milestone 3 adds the waypoint graph on top of it". Milestone 3: remove "A* inside the visible collision window" from its list (it now exists) and keep the waypoint maps, goals, prompts, menus, logging, replay.

Section 8.1, after the policy list: "Milestone 2 executes `move` and `run`; `heal`, `catch`, and `switch` are asked and recorded but fall back to the move answer with `fallback` set until their macros land (milestone 4)."

- [ ] **Step 2: Update README and CLAUDE.md**

README: status paragraph becomes milestone 2; Quick start adds `mise exec -- uv run Scripts/record-fixtures.py` under a "Recording API fixtures" note, and `uv run jevplays run --state states/battle_wild.state` as the quickest way to watch a decision; Layout adds `brain/` and `executor/`. CLAUDE.md: add under Build & test "`import typesafe_sdk` lives in `src/jevplays/brain/client.py` (and the fixture script) and nowhere else; unit tests replay `tests/fixtures/responses/`, never the API", and under Changes "A change to a question's wording or a state field Jev sees re-records the fixtures (`Scripts/record-fixtures.py`) in the same PR."

- [ ] **Step 3: Full check**

```bash
mise run check
env -u JEVPLAYS_ROM .venv/bin/python -m pytest -q
mise exec -- uv run pytest -q
git ls-files | grep -E '\.(gb|gbc|state|ram)$|^roms/|^states/|^runs/|mise\.local' ; echo "exit=$?"
```

Expected: lint clean; both shapes green; the last command prints nothing and `exit=1`.

- [ ] **Step 4: Commit, push, PR**

```bash
git add docs/superpowers/specs/2026-09-20-jevplays-design.md README.md CLAUDE.md
git commit -m "docs: milestone 2 spec amendments and README/CLAUDE.md updates"
git push -u origin tylervick/milestone-2-battles
gh pr create --base main --title "Milestone 2: Jev fights" --body "$(cat <<'EOF'
Implements milestone 2 of docs/superpowers/specs/2026-09-20-jevplays-design.md.

- `GameState` gains the party, the active and enemy Pokémon, the battle kind, and the bag, parsed from verified RAM addresses (pinned against a rival battle and a wild Rattata).
- `brain/`: battle state as words, six speculative questions in one request, an ordered policy with named thresholds, and a `Decision` record; recorded TypeSafe responses replay in the unit tests.
- `executor/`: battle macros that verify the cursor label before every press, a dialog skipper, and a window pathfinder (delivered early so the state script can reach a battle).
- The loop asks Jev at the battle menu, publishes a `decision` event, and backs off when the API is down instead of pressing buttons.
- Dashboard: probability bars per option, yes/no split bars, confidence badges, dimmed inapplicable questions, party strip, decision log.
- `Scripts/make-states.py` walks from the bedroom to the rival battle and to Route 1 grass; `Scripts/record-fixtures.py` records responses.

Executes `move` and `run`; `heal`, `catch`, `switch` are asked and recorded but fall back to the move until milestone 4.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review

**Spec coverage:** section 6 party/enemy/battle/bag: Task 5 (buckets moved to the brain, amended in Task 11). Section 8.1 state JSON, six questions, policy order and thresholds: Task 6; `Decision` record (8.4): Task 6, with `applied` per answer. Section 9 macros with cursor verification and B-on-failure: Task 8. Section 10 `decision` event and the panel (bars, split bars, confidence badge, dimmed "not applicable", action, latency/tokens, party strip, log): Tasks 9 and 10. Section 12 error handling (API down pauses with `waiting_for_api`, never presses; missing answer is a `fallback`; model id logged): Tasks 6, 7, 9. Section 13 recorded fixtures and per-mode ROM states: Tasks 3 and 7. Section 14 milestone 2 "Demo: start from a save state on Route 1 and watch Jev fight and catch": fight yes; catch is asked but falls back (no balls at that point in the game and the ITEM macro is milestone 4), stated in the amendment.

**Placeholder scan:** every step has its code or command; the one "verify the SDK's close method name" instruction gives the exact command to run and a `getattr` chain that covers both names.

**Type consistency:** `BattleAction`, `Decision.action_value`, `decide_battle`'s signature, `battle_macros.apply(emu, action)`, `Brain.ask -> (dict, int)`, `BrainUnavailable` (defined in `brain/errors.py` in Task 7, re-exported from `client.py`, imported by the loop from `errors`), `Emulator.collision()` and `FakeEmulator.collision()`, `write_mon(..., layout=)`, `rows_of` from `state.snapshot`, `cursor_label` from `emulator.intro` re-exported by `executor.dialog`: each name is defined before it is consumed and spelled the same in every task.
