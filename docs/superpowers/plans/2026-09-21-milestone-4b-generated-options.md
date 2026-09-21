# Milestone 4b: Generated Options Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jev chooses what to do next in the overworld from options code generates out of the map it is standing on, with three badge-level milestones as the spine, and a logged run reaches the Boulder Badge within about three times the #17 baseline's 84 decisions.

**Architecture:** `executor/options.py` turns RAM (connections, warps, sprites, grass) into `Option`s with texts, memory words, and plans; `brain/explore.py` is the new decision point that replaces the goal one; `executor/goals.py` shrinks to three milestones; the loop executes an option the way it executed a goal, keeps a `Memory` it writes to the run dir, and ends the run with a `finished` status at the badge. Measurement extends `Scripts/accuracy.py`.

**Tech Stack:** Python 3.12, PyBoy, TypeSafe SDK (fixture recording), pytest.

**Spec:** `docs/superpowers/specs/2026-09-21-generated-options-design.md` (binding), which amends `docs/superpowers/specs/2026-09-20-jevplays-design.md` sections 7, 8.2, 9, 10, 11, 13, 14.

**Branch:** `tylervick/milestone-4b-generated-options` from `main` @ d9338f7 (the spec is its first commit).

## Global Constraints

- ruff: line length 110, `select = ["E", "F", "I", "B"]`, `ignore = ["E501"]`, py312; `uv run ruff check src tests Scripts && uv run ruff format src tests Scripts` clean before every commit.
- `import pyboy` only inside `src/jevplays/emulator/pyboy.py`; `import typesafe_sdk` only in `src/jevplays/brain/client.py` (and `Scripts/record-fixtures.py`). `tests/test_imports.py` pins `jevplays.loop` and `jevplays.cli` free of pyboy.
- Never commit a ROM, `*.state`, `*.ram`, `runs/`, or `mise.local.toml`. Fixtures hold no secrets; never print the API key.
- Never edit an existing test to make it pass. Tests for a feature this spec retires (the goal decision point and the removed goals) are deleted in the task that retires the feature, with the deletion named in the commit; no other existing assertion changes.
- Jev judges, code executes. Jev never receives coordinates, raw numbers (levels excepted), screenshots, or effectiveness. Option texts carry no numbers; the memory word is one of `new`, `visited`, `talked already`, `tried`.
- A change to a question's wording or a state field Jev sees re-records the affected fixtures in the same PR.
- Spec values, verbatim: NPC options capped at the six nearest reachable; `OPTION_BUDGET_S = 90.0`; policy `needs_heal` above `HEAL_FIRST_THRESHOLD` (0.7) with a `heal` option present wins, else the `explore` choice, else fallback to `milestone` then the first option; option ids `exit_<direction>`, `door_<dest map id>`, `npc_<slot>`, `grass`, `milestone`, `heal`; decision kind `explore`, action text `explore: <option text>`; statuses gain `finished`; success is the badge within about 250 decisions.
- Conventional commits; every commit body ends with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Unit: `env -u JEVPLAYS_ROM .venv/bin/python -m pytest -q`. ROM: `mise exec -- uv run pytest tests/rom -q`. Full: `mise run check`.

## File Structure

| File | Responsibility |
| --- | --- |
| `src/jevplays/state/data/sprites.json` (new) | sprite picture id → noun phrase, from pokered's `constants/sprite_constants.asm`. |
| `src/jevplays/executor/options.py` (new) | `Option`, `Memory`, `generate(emu, state, memory, milestone)`; texts, memory words, plans. Pure over RAM reads and the world layer; no emulator import beyond the `emu` handle it is given. |
| `src/jevplays/brain/explore.py` (new) | `ExploreAction`, `explore_state`, `explore_questions`, `decide_explore`, `PROGRESS_WORDS`; absorbs `brain/goal.py`'s bucket lines. |
| `src/jevplays/brain/policy.py` (modify) | `choose_explore(answers, option_ids)`; `choose_goal` removed. |
| `src/jevplays/brain/decision.py` (modify) | `ExploreAction(option_id, kind, text)`; `GoalAction` removed. |
| `src/jevplays/executor/goals.py` (modify) | three milestones, `active_milestone(state)`, `Goal`, `legs_to`, `battle_goal` kept; removed goals gone. |
| `src/jevplays/loop.py` (modify) | explore branch, option execution, `Memory` ownership, `OPTION_BUDGET_S`, `finished`; `_pick_goal`, `GOAL_RETRIES`, `_block_goal` retired. |
| `src/jevplays/runlog.py` (modify) | `save_memory(dict)`, `load_memory() -> dict | None` (`memory.json`). |
| `src/jevplays/cli.py` (modify) | `--resume` reloads memory; `finished` ends the process with exit 0 and prints the badge line. |
| `src/jevplays/dashboard/static/{app.js,styles.css}` (modify) | `finished` pill style; goal line from `state_summary.milestone` on `explore` decisions. |
| `Scripts/record-fixtures.py`, `Scripts/accuracy.py` (modify) | `explore_viridian` fixture; the exploration section. |
| tests: `tests/test_options.py`, `tests/test_explore_brain.py`, `tests/test_goals.py` (rewritten for three milestones), `tests/test_loop.py` (explore section), `tests/test_runlog.py`, `tests/test_fixtures.py`, `tests/test_accuracy.py`, `tests/rom/test_options.py` | per task. |

---

### Task 1: `sprites.json`, `Option`, `Memory`, and `generate`

**Files:**
- Create: `src/jevplays/state/data/sprites.json`, `src/jevplays/executor/options.py`
- Modify: `src/jevplays/state/data/README.md`
- Test: `tests/test_options.py`

**Interfaces:**
- Consumes: `world.read_connections(mem)`, `world.read_warps(mem)` (`Warp(y, x, id, dest)`), `world.build_grid(emu)` (`MapGrid.walkable`, `.grass()`), `world.astar(grid, start, goal, blocked)`, `world.blocked_by_sprites`, `maps.node_of`, `maps.route`, `maps.NODE_NAMES`, `names.map_name`, `talk.adjacent_tile`, `state.sprites` (`Sprite(slot, picture, x, y)`), `state.tile`, `state.map_id`, `state.party`, `goals.Goal` (`.id`, `.description`, `.legs(state)`, `.after`), `goals.legs_to(state, node)`, `ram.WARP_LAST_MAP`, `hp_bucket`.
- Produces:

```python
@dataclass(frozen=True)
class Option:
    id: str           # exit_north | door_41 | npc_3 | grass | milestone | heal
    kind: str         # exit | door | npc | grass | milestone | heal
    text: str         # what Jev reads, without the memory word
    memory: str       # new | visited | talked already | tried
    legs: tuple[Leg, ...]
    after: str | None # macro name: talk_<slot> | heal | buy_pokeballs | wander | the milestone's after | None
    target: tuple[int, int] | None = None  # the tile the npc option talks from
    face: str | None = None                # the direction it faces
    dest_map: int | None = None            # exit/door destination

    def labelled(self) -> str: return f"{self.text} ({self.memory})"


@dataclass
class Memory:
    visited_maps: set[int]
    talked: set[tuple[int, int]]      # (map id, sprite slot)
    tried: set[tuple[int, str]]       # (map id, option id)
    def to_dict(self) -> dict; @classmethod def from_dict(cls, d) -> "Memory"; @classmethod def empty(cls)
    def note_map(self, map_id) ; def note_talked(self, map_id, slot) ; def note_tried(self, map_id, option_id)
    def word(self, map_id: int, option: "Option") -> str   # the rule in spec section 3


NPC_CAP = 6
NEAR_TILES = 4

def sprite_noun(picture: int) -> str          # from sprites.json; "someone" when unknown
def place_words(player: tuple[int,int], sprite: Sprite, picture: int) -> str
    # "behind the counter" for nurse (0x29) and clerk (0x26) pictures; otherwise compass words
    # ("to the north", "to the south-east") from the sign of dx, dy, prefixed "near " within NEAR_TILES
def generate(emu, state: GameState, memory: Memory, milestone: Goal | None) -> list[Option]
    # order: milestone, heal, exits (N,S,W,E), doors (by dest map id), npcs (nearest first), grass
```

Rules for `generate`: exits from `read_connections` in the order north, south, west, east, `text = f"go {direction} to {map_name(dest)}"`, legs `[Leg(kind="edge", direction=direction, label=text)]`; doors from `read_warps` grouped by `dest`, one per destination, `text = "go back outside"` when `dest == WARP_LAST_MAP` else `f"enter {map_name(dest)}"`, legs `[Leg(kind="warp", dest_map=dest, label=text)]`; npcs: for each sprite (skip picture 0 and the player's own slot 0), find the nearest of its four neighbours that is walkable and reachable by `astar` from the player (blocked by the other sprites), keep the path length, sort by it, cap at `NPC_CAP`; `text = f"talk to {sprite_noun(p)} {place_words(...)}"`; legs `[Leg(kind="walk", target=neighbour, label=text)]`, `after = f"talk_{slot}"`, `target = neighbour`, `face` = the direction from the neighbour to the sprite; a nurse sprite gets `after="heal"`, a clerk sprite `after="buy_pokeballs"`; grass when `grid.grass()` is non-empty: `text = "train in the tall grass here"`, legs `()`, `after="wander"`; milestone when `milestone is not None` and `not milestone.done(state)`: `text = f"head for {milestone.description}"`, legs `tuple(milestone.legs(state))`, `after = milestone.after` (when the legs are empty and the current node is not `map_`-prefixed the option still exists: its plan is just the macro); omitted when `maps.node_of(state.map_id, *state.tile)` starts with `map_`; heal when the lead exists, `hp_bucket(lead) in ("hurt", "low", "critical")` and `maps.route(node, center)` exists for some center in `("viridian_pokecenter", "pewter_pokecenter")` (choose the shorter), `text = f"go heal at {map_name(center map id)}"`, legs `legs_to(state, center)`, `after="heal"`; inside a Pokémon Center the nurse npc option is the heal, so `heal` is omitted there. Memory words via `memory.word(state.map_id, option)`: `tried` when `(map_id, option.id) in memory.tried`; else for npc `talked already` when `(map_id, slot) in memory.talked`; else for exit/door `visited` when `dest_map in memory.visited_maps`; else `new`.

- [ ] **Step 1: Failing tests** (`tests/test_options.py`; use `tests.support.FakeEmulator`, `install_map(emu, rows, warps=..., connections=...)`, `set_sprites`, `snapshot`; read `tests/test_navigator.py` for a map fixture with warps and a connection; grass rows use `~` as `install_map` documents):

```python
from jevplays.executor.options import NPC_CAP, Memory, generate, place_words, sprite_noun
from jevplays.state.snapshot import Sprite, snapshot
from tests.support import FakeEmulator, install_map

ROWS = [  # 8x8 tiles = 4x4 blocks; '#' blocked, '.' floor, '~' grass (block-uniform per install_map)
    "..##....",
    "..##....",
    "........",
    "........",
    "....~~..",
    "....~~..",
    "........",
    "........",
]


def town(memory=None, sprites=((3, 0x29, 6, 1), (4, 0x04, 1, 6), (5, 0x04, 2, 0))):
    emu = FakeEmulator()
    install_map(emu, ROWS, warps=[(0, 7, 0, 41), (1, 7, 0, 41), (7, 7, 0, 42)], connections={"north": 13, "east": 12})
    emu.set_sprites(list(sprites))  # nurse at (6,1); a youngster at (1,6); a youngster walled in at (2,0)
    emu.mem[0xD362], emu.mem[0xD361] = 4, 4  # the player at (4,4)  (wXCoord, wYCoord)
    return emu, snapshot(emu), memory or Memory.empty()


def test_options_cover_exits_doors_reachable_npcs_and_grass_in_order():
    emu, state, memory = town()
    ids = [o.id for o in generate(emu, state, memory, milestone=None)]
    assert ids == ["exit_north", "exit_east", "door_41", "door_42", "npc_3", "npc_4", "grass"]
    texts = {o.id: o.text for o in generate(emu, state, memory, None)}
    assert texts["exit_north"] == "go north to Route 2" and texts["door_41"] == "enter Viridian Pokémon Center"
    assert texts["npc_3"] == "talk to the nurse behind the counter"
    assert texts["npc_4"].startswith("talk to a youngster")
    assert texts["grass"] == "train in the tall grass here"


def test_an_unreachable_npc_is_not_offered_and_the_cap_holds():
    emu, state, memory = town(sprites=tuple((s, 0x04, 5, 6) for s in range(1, 10)) + ((11, 0x04, 2, 0),))
    npcs = [o for o in generate(emu, state, memory, None) if o.kind == "npc"]
    assert len(npcs) == NPC_CAP and all(o.id != "npc_11" for o in npcs)


def test_memory_words():
    emu, state, memory = town()
    memory.note_map(41); memory.note_talked(state.map_id, 3); memory.note_tried(state.map_id, "grass")
    words = {o.id: o.memory for o in generate(emu, state, memory, None)}
    assert words == {"exit_north": "new", "exit_east": "new", "door_41": "visited", "door_42": "new",
                     "npc_3": "talked already", "npc_4": "new", "grass": "tried"}
    assert Memory.from_dict(memory.to_dict()) == memory


def test_npc_plan_walks_to_a_neighbour_and_faces_the_sprite():
    emu, state, memory = town()
    nurse = next(o for o in generate(emu, state, memory, None) if o.id == "npc_3")
    assert nurse.after == "heal" and nurse.legs[0].kind == "walk"
    assert nurse.face in ("up", "down", "left", "right") and nurse.target is not None


def test_texts_and_labels_carry_no_numbers():
    import re
    emu, state, memory = town()
    for o in generate(emu, state, memory, None):
        assert not re.search(r"\d", o.labelled()), o.labelled()


def test_place_words_and_nouns():
    assert sprite_noun(0x29) == "the nurse" and sprite_noun(0x03) == "Professor Oak" and sprite_noun(0x3D) == "an item on the ground"
    assert sprite_noun(200) == "someone"
    assert place_words((4, 4), Sprite(1, 4, 4, 1), 4) == "near to the north"
    assert place_words((4, 4), Sprite(1, 4, 12, 12), 4) == "to the south-east"
    assert place_words((4, 4), Sprite(1, 0x26, 0, 5), 0x26) == "behind the counter"
```

Adjust the fixture coordinates to what `install_map` produces (block-uniform 2x2 tiles per character; the warp tuples are `(y, x, id, dest)` as `install_map` takes them; check its signature) so the expected ids hold; the assertions on ids, texts, words, and the cap are the requirement. The map ids 13 (Route 2), 12 (Route 1), 41, 42 must map through `names.map_name` to "Route 2", "Route 1", "Viridian Pokémon Center", "Viridian Mart" (check the exact spellings in `names.py`'s `MAP_NAMES` and use them).

- [ ] **Step 2:** run, fail. **Step 3:** generate `sprites.json` from `/private/tmp/claude-503/-Users-builder-orca-projects-jevplays/cef7ae7f-42b5-46cc-8fab-57ac894a688b/scratchpad/sprite_constants.asm` (73 `const SPRITE_X ; $nn` lines; if missing fetch `https://raw.githubusercontent.com/pret/pokered/master/constants/sprite_constants.asm`): id → noun phrase, hand-written for the ones the early game shows (OAK "Professor Oak", NURSE "the nurse", CLERK "the shop clerk", OLD_MAN "an old man", YOUNGSTER "a youngster", LITTLE_GIRL "a little girl", MIDDLE_AGED_MAN "a man", MIDDLE_AGED_WOMAN "a woman", GIRL "a girl", FISHER "a fisherman", BUG_CATCHER "a bug catcher", BLUE "your rival", MOM "your mom", GENTLEMAN "a gentleman", POKE_BALL "an item on the ground", BRUNETTE_GIRL "a girl", MONSTER "a Pokémon", FAT_BALD_GUY "a bald man", GAMBLER "a gambler", SCIENTIST "a scientist", SUPER_NERD "a nerd", BALDING_GUY "a balding man", COOLTRAINER_M/F "a trainer", BLACK_HAIR_BOY_1/2 "a boy", SAILOR "a sailor", GUARD "a guard", ROCKET "a Rocket grunt", BROCK "Brock", MISTY "Misty", CLIPBOARD "a clipboard", the rest a sensible lowercase phrase from the constant name, e.g. "a hiker"); README line; implement `options.py` per the interface. **Step 4:** run all unit tests. **Step 5:** commit `feat(executor): options generated from the map, with memory words`.

---

### Task 2: The explore decision point

**Files:**
- Create: `src/jevplays/brain/explore.py`
- Modify: `src/jevplays/brain/decision.py` (`ExploreAction`; remove `GoalAction`), `src/jevplays/brain/policy.py` (`choose_explore`; remove `choose_goal`), `src/jevplays/brain/goal.py` (delete; its `money_bucket`/`quantity_bucket` uses come from `buckets.py` already), `tests/test_goal_brain.py` (delete: it tests the retired decision point), `tests/test_fixtures.py` (remove the two `goal_*` tests), `tests/fixtures/responses/goal_route1.json`, `goal_hurt.json` (delete), `Scripts/record-fixtures.py` (remove the goal entries; add `explore_viridian` = (`viridian_oldman`, `explore_ask`, None) where `explore_ask` builds `generate(...)` on the loaded emulator with an empty `Memory` and the active milestone)
- Test: `tests/test_explore_brain.py`

**Interfaces:**
- `ExploreAction(option_id: str, kind: str, text: str)`, `describe() -> f"explore: {text}"`.
- `PROGRESS_WORDS: dict[str, str]` over `TRACKED_FLAGS` names: `got_starter` "got a starter", `got_oaks_parcel` "picked up Oak's parcel", `oak_got_parcel` "delivered Oak's parcel", `got_pokedex` "got the Pokédex", `beat_brock` "earned the Boulder Badge", `battled_rival_in_oaks_lab` "beat the rival in the lab"; others omitted.
- `explore_state(state, options: list[Option], milestone: Goal | None) -> dict` with keys `map`, `progress` (list of words in table order), `party` (name/level/hp bucket), `money` (bucket), `bag` (name → quantity bucket), `milestone` (description or "none yet"), `options` (id → `option.labelled()`).
- `explore_questions(sj) -> dict`: `explore` Choice (criteria = `sj["options"]`), `needs_heal` Noul (criteria as spec section 4).
- `choose_explore(answers, option_ids: list[str]) -> tuple[str, list[str]]` (heal-first rule requires `"heal"` in `option_ids`; the choice must be in `option_ids`, else `"milestone"` if present else `option_ids[0]`, returning `used=[]` for that fallback).
- `decide_explore(sj, questions, response, options: list[Option], *, model, input_tokens, latency_ms) -> Decision` (kind `explore`, `fallback=True` with a reason when the answer is missing or off-list; `action_value=ExploreAction(...)`; `applied` marks as the other decoders; uses `brain/record.py`).

- [ ] **Step 1: Failing tests** (`tests/test_explore_brain.py`, mirroring `tests/test_prompt_brain.py`'s canned-response style):

```python
def test_explore_state_uses_words_and_lists_options_with_memory_words():
    state = overworld_state(map_id=1, flags=("got_starter", "got_pokedex"), money=3175, bag=(BagItem("POKE BALL", 4),))
    options = [Option("exit_north", "exit", "go north to Route 2", "new", (), None, dest_map=13),
               Option("milestone", "milestone", "head for the Pewter Gym", "new", (), "talk_brock")]
    sj = explore_state(state, options, milestone=None)
    assert sj["progress"] == ["got a starter", "got the Pokédex"] and sj["money"] == "comfortable"
    assert sj["options"] == {"exit_north": "go north to Route 2 (new)", "milestone": "head for the Pewter Gym (new)"}
    assert not re.search(r"\d", json.dumps({k: v for k, v in sj.items() if k != "party"}))


def test_questions_offer_exactly_the_options_and_always_ask_needs_heal(): ...
def test_policy_heals_first_only_when_a_heal_option_exists_and_the_noul_clears(): ...
def test_off_list_choice_falls_back_to_the_milestone_with_fallback_set(): ...
def test_decide_explore_marks_applied_and_carries_the_option_kind(): ...
```

Write the four elided tests in full in the file (each asserts the concrete values: question criteria equal the options dict; `choose_explore({"needs_heal": 0.9, "explore": "grass"}, ["heal","grass"]) == ("heal", ["needs_heal"])`; with no heal option the explore choice wins; an off-list choice yields `milestone` with `fallback=True` and a reason containing "not offered"; `decide_explore` returns `action == "explore: go north to Route 2"` and `action_value.kind == "exit"` with `answers["explore"]["applied"] is True`).

- [ ] **Steps 2–5:** run (fail), implement, run everything (`test_goal_brain.py` and the goal fixtures are gone; `tests/test_fixtures.py` keeps its battle/prompt/menu tests), commit `feat(brain): the explore decision point replaces the goal one` (the body names the retired files).

---

### Task 3: Three milestones

**Files:**
- Modify: `src/jevplays/executor/goals.py`, `tests/test_goals.py` (rewrite: the removed goals' tests go; keep `legs_to` and `battle_goal` tests unchanged)
- Test: `tests/test_goals.py`

**Interfaces:** `MILESTONES: list[Goal]` = `get_starter` (as today), `get_pokedex` (id renamed from `deliver_parcel`; available `got_starter`; done `got_pokedex`; legs as today's deliver_parcel; `after="talk_oak"`), `beat_brock` (available `got_pokedex`; done `beat_brock`; legs `legs_to(state, "pewter_gym") + [Leg(kind="walk", target=(4, 2))]` when not already in the gym, else the walk leg; `after="talk_brock"`); `active_milestone(state) -> Goal | None` (the first not done); `GOALS`, `available_goals`, `goal_by_id`, `ALWAYS`, `OLD_MAN_PICTURE` and the seven removed goals are deleted (grep the repo for users: `Scripts/make-states.py` imports `OLD_MAN_PICTURE` and the old ids; update it to use the literal it needs and `active_milestone`; `Scripts/record-fixtures.py`'s prompt/menu asks use `goal_by_id("get_starter").description`: switch them to `MILESTONES[0].description`). `legs_to`, `battle_goal`, `STANDING_CLAUSE`, `Goal` unchanged.

- [ ] **Step 1: Failing tests:** `active_milestone` on a fresh state is `get_starter`; with `got_starter` it is `get_pokedex`; with `got_pokedex` it is `beat_brock`; with `beat_brock` it is None; `get_pokedex.legs` goes to the Mart before the parcel and to the lab after; `beat_brock.legs` from Viridian ends with the walk leg to (4, 2); `MILESTONES` ids in order. **Steps 2–5:** implement, run the whole suite (fix the scripts' imports), commit `refactor(executor): the goal table becomes three milestones`.

---

### Task 4: The loop explores

**Files:**
- Modify: `src/jevplays/loop.py`, `src/jevplays/runlog.py`, `src/jevplays/cli.py`, `src/jevplays/dashboard/events.py` (docstring: statuses gain `finished`), `src/jevplays/dashboard/static/app.js` + `styles.css`
- Test: `tests/test_loop.py` (explore section), `tests/test_runlog.py`, `tests/test_cli.py`

**Interfaces:**
- `RunDir.save_memory(d: dict)`, `RunDir.load_memory() -> dict | None` (`memory.json`, UTF-8, atomic via temp + replace).
- `Loop.__init__(..., memory: Memory | None = None)`; `self.memory`; `self.milestone: Goal | None` (refreshed each overworld turn via `active_milestone(state)`); `self.option: Option | None`, `self.option_started_at`; `OPTION_BUDGET_S = 90.0`; `GOAL_RETRIES`, `_goal_failures`, `blocked_goals`, `_pick_goal`, `_block_goal`, `_finish_goal`, `_goal_budget_spent`, `GOAL_BUDGET_S` removed; `_apply_macro` gains `talk_<slot>` (walk is already done by the leg; face `option.face`, `talk_to(emu, *option.target, option.face)`), `heal`, `buy_pokeballs`, `wander`, `talk_oak`, `talk_brock`, `choose_charmander` as today.
- `_overworld_turn`: (1) `self.milestone = active_milestone(state)`; if the previous milestone id differs, publish `running: milestone done: <old id>`; if `self.milestone is None`: publish `status_event("finished", "Boulder Badge")`, set `self.finished = True`, return idle frames (`run()` returns when `self.finished`). (2) navigator busy → `_walk` (on `stuck`: `memory.note_tried`, publish `running: tried: <text>`, clear the option). (3) option arrived → `_run_macro` (False or exception → `note_tried`; True → `note_talked` for npc options, then clear the option). (4) option budget spent → `note_tried`, clear. (5) no option → `generate(...)`, `explore_state`, `explore_questions`, `_decide("explore", ..., partial(decide_explore, options=options), offline=(first non-tried option, milestone first, "no brain: ..."))`, then `memory.note_map(state.map_id)` and start the option's legs (empty legs with `after` → arrived at once). On every map change (`_walk`'s `leg_done`/`done` with a new map id) `memory.note_map(new map)`. After every memory change: `run_dir.save_memory(memory.to_dict())` when a run dir exists.
- `cli.py`: `--resume` passes `Memory.from_dict(run_dir.load_memory() or {})`; when the loop finishes, print `finished: Boulder Badge after N decisions` and exit 0 (the exit checkpoint still runs).
- `app.js`: the goal line reads `state_summary.milestone` on an `explore` decision; the pill's `finished` style = `stopped`'s color but with the accent (add `.status[data-status="finished"]`).

- [ ] **Step 1: Failing tests:** with `FakeEmulator` + the Task 1 `town()` map and a `QuestionBrain(explore="exit_north", needs_heal=0.1)`: (a) the loop asks once, records an `explore` decision with `action_value.kind == "exit"`, and starts moving (a direction press); (b) an npc option runs `talk_<slot>` after the walk and marks `talked` in memory; (c) a stuck navigator marks the option `tried` and the next ask shows `(tried)` in the options text; (d) with a fake clock past `OPTION_BUDGET_S` the option is dropped and marked tried; (e) with `beat_brock` set in flags the loop publishes `finished` and `run()` returns; (f) `RunDir.save_memory/load_memory` round trip and the loop saving after a change; (g) `--resume` CLI test that a run dir with `memory.json` feeds the loop (parse-level: `resolve_resume` or the helper you add returns the memory). Offline (no brain) picks the milestone first.
- [ ] **Steps 2–5:** implement, run everything, commit `feat(loop): Jev explores from generated options between milestones`.

---

### Task 5: ROM tests, the explore fixture, and the dashboard check

**Files:**
- Create: `tests/rom/test_options.py`
- Modify: `Scripts/record-fixtures.py` (already has `explore_viridian` from Task 2; record it now), `tests/test_fixtures.py` (add the replay test)
- Test: as named

- [ ] `tests/rom/test_options.py`: on `viridian_oldman.state` with an empty `Memory` and `active_milestone`, `generate` yields ids including `exit_north` (text "go north to Route 2"), `door_41`, `door_42`, an npc option whose text starts with "talk to an old man", and `milestone`; executing the old man option through the loop (`ThrowBrain`-style stand-in that answers `explore` with that id and `needs_heal` 0) for up to 400 iterations ends with no sprite of picture 72 on the map (he moved) and the memory holding `(1, slot)` in `talked`.
- [ ] Record `mise exec -- uv run Scripts/record-fixtures.py --only explore_viridian` (never print the key; grep the JSON for secrets); `tests/test_fixtures.py::test_explore_fixture_picks_an_offered_option`: replay through `decide_explore` with the options rebuilt from the fixture's `state_json["options"]` (build `Option` stubs from the ids and texts), assert `fallback is False` and the chosen id is in the offered set; record what Jev chose and its probability in the report.
- [ ] Dashboard: `mise exec -- uv run jevplays run --state states/viridian_oldman.state --no-brain --unpaced` in the background; the controller checks the page shows the milestone line and `explore:` log entries; kill it.
- [ ] Commit `test(rom): options on Viridian and the old man through the loop; the explore fixture`.

---

### Task 6: Measurement

**Files:**
- Modify: `Scripts/accuracy.py`, `tests/test_accuracy.py`

**Interfaces:** `exploration(decisions: Iterable[dict]) -> dict` with `by_kind` (decision kinds → count), `explore_by_option_kind` (from `action_value`? no: the log holds `action` text and `state_summary`; derive the option kind from the chosen id prefix: `exit_`/`door_`/`npc_`/`grass`/`milestone`/`heal`; the chosen id is `answers["explore"]["choice"]` when present else parse the fallback), `milestone_share` (milestone picks / explore decisions), `maps_seen` (distinct `state_summary["map"]` over explore decisions), `total`. `main` prints an "exploration" block after the existing ones: `decisions: N (battle B, explore E, prompt P, menu M)`, `explore picks: exit x, door y, npc z, grass g, milestone m, heal h`, `milestone share: P%`, `maps seen: K`.

- [ ] Test with a synthetic log of six decisions; run on the demo runs in the scratchpad (they have no explore decisions: the block prints zeros). Commit `feat(scripts): the accuracy script summarises exploration`.

---

### Task 7: Docs and the full check

- Base spec: section 7 (loop order, `finished`), 8.2 (replaced by a pointer to the new spec plus the explore table), 9 (the goal table paragraph → three milestones and options), 10 (`finished` status), 11 (`memory.json`), 13 (exploration numbers), 14 (4b as built); mark as 4b amendments. README: status 4b; a "How Jev explores" paragraph; `memory.json` in the Runs section; the accuracy block. CLAUDE.md: "options are generated from the map (`executor/options.py`); milestones are the only hand-written story in `executor/goals.py`".
- Checks: `mise run check`; unit; ROM; tracked-files grep; fixtures secrets grep.
- Commit `docs: milestone 4b spec amendments and README`.

---

### Task 8: The run to the Boulder Badge

- `mise exec -- uv run jevplays run --state states/route1.state --unpaced` with the real Jev (the API key comes from `mise.local.toml`; never print it) until `finished` or 400 decisions (`--limit`? add nothing: watch the run dir's `decisions.jsonl` line count from another shell; kill at 400 if not finished). Then `mise exec -- uv run Scripts/accuracy.py runs/<stamp>`.
- Report: decisions to the badge, the exploration block, move accuracy and the Brier line; compare with #17's 84 decisions / 95% / 0.073; success is the badge within about 250 decisions.
- If the run stalls or misbehaves: one fix wave for what it exposes (each fix with a test), then rerun once. Findings that need more go to issues.
- The numbers go into the PR body and a comment on issue #17.

---

## Self-review

**Spec coverage:** section 2 options (Task 1); 3 memory (Tasks 1, 4); 4 what Jev sees (Task 2); 5 milestones (Task 3); 6 loop (Task 4); 7 runs and dashboard (Task 4); 8 measurement (Tasks 6, 8); 9 testing (Tasks 1–5); 10 out of scope (issues, Task 7's PR body).

**Placeholder scan:** Task 2 lists four test names with their concrete assertions in prose; the implementer writes them out. No TBDs.

**Type consistency:** `Option(id, kind, text, memory, legs, after, target, face, dest_map)` and `Memory` (Task 1) are what Tasks 2, 4, 5 use; `ExploreAction(option_id, kind, text)` (Task 2) is what the loop records and the accuracy script parses by id prefix (Task 6); `active_milestone`/`MILESTONES` (Task 3) are what Tasks 1, 4, 5 call; `RunDir.save_memory/load_memory` (Task 4) are what `cli.py` uses.
