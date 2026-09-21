# Milestone 4a: Heal, Catch, and Switch Macros, and the Accuracy Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every battle decision Jev can make is executable (heal, catch, switch join move and run), Jev sees what those judgments need (bench labels, enemy status, party size), and a script measures how good Jev's move choices are from a run's decision log.

**Architecture:** Three new button macros in `executor/battle.py` follow the ITEM and PKMN screens exactly as the ROM spikes showed them (item list with two rows per item, party list with two rows per Pokémon, a SWITCH sub-menu). `brain/battle.py` keys `switch_to` by a stable bench label and decodes it to a party slot, adds the enemy's status and a party-size word, and stops marking heal/catch/switch as unsupported. A Gen 1 type chart (`state/data/type_chart.json`, from pokered) backs `state/types.effectiveness`, which only `Scripts/accuracy.py` uses: Jev never sees it. New save states and recorded fixtures pin each new decision.

**Tech Stack:** Python 3.12, PyBoy 2.7, TypeSafe SDK (fixture recording only), pytest.

**Spec:** `docs/superpowers/specs/2026-09-20-jevplays-design.md`, sections 8.1 (battle), 12 (fallbacks), 13 (the accuracy script), 14 (milestone 4). This plan amends 8.1 and 14 in its last task.

**Branch:** `tylervick/milestone-4a-battle-macros`, created from `tylervick/milestone-3b-runs-replay` (PR #14, unmerged; PR #9 unmerged) because it builds on 3b's loop. The PR targets `main` once #9 and #14 merge; until then it may be opened against the 3b branch.

## Global Constraints

- ruff: line length 110, `select = ["E", "F", "I", "B"]`, `ignore = ["E501"]`, py312; `uv run ruff check src tests Scripts && uv run ruff format src tests Scripts` clean before every commit.
- `import pyboy` only inside `src/jevplays/emulator/pyboy.py`; `import typesafe_sdk` only in `src/jevplays/brain/client.py` (and `Scripts/record-fixtures.py`). `tests/test_imports.py` pins `jevplays.loop` and `jevplays.cli` free of pyboy.
- Never commit a ROM, `*.state`, `*.ram`, `runs/`, or `mise.local.toml`. Fixtures hold no secrets. Never print the API key.
- Never edit an existing test to make it pass. Add tests; leave existing assertions alone.
- Jev judges, code executes. Jev never receives coordinates, raw numbers (levels excepted), screenshots, or computed type effectiveness. Buckets, arithmetic, and policy stay in code.
- A change to a question's wording or a state field Jev sees re-records the fixtures (`Scripts/record-fixtures.py`) in the same PR.
- Spec 8.1 policy order and thresholds stay: `HEAL_THRESHOLD = 0.7` with hp `low`/`critical`, `CATCH_THRESHOLD = 0.6`, `RUN_THRESHOLD = 0.7`, `SWITCH_THRESHOLD = 0.7`, else `move`.
- Verified on the ROM (2026-09-21 spike): the in-battle ITEM list draws items on rows 4, 6, 8 (cursor label = item name, `CANCEL` last); a Poké Ball throw runs as text after A; a caught Pokémon triggers a `give a nickname to <NAME>?` YES/NO box; a Potion opens `Use item on which POKéMON?` with the party list (name on row 2i, HP on row 2i+1, cursor on the HP row) and prints `It won't have any effect.` at full HP; PKMN opens the same party list (`Choose a POKéMON.`), A on a slot opens a sub-menu with the cursor on `SWITCH` (row 12) over `STATS`/`CANCEL`; a fainted target prints `There's no will to fight!`. Mid-catch the party count is bumped before the record is written, so a snapshot can show a slot with species 0.
- Conventional commits; every commit body ends with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Unit tests: `env -u JEVPLAYS_ROM .venv/bin/python -m pytest -q`. ROM tests: `mise exec -- uv run pytest tests/rom -q`. Full: `mise run check`.

## File Structure

| File | Responsibility |
| --- | --- |
| `src/jevplays/state/data/type_chart.json` (new) | Gen 1 type matchups: `[[attacker, defender, multiplier], ...]`, 82 rows from pokered's `data/types/type_matchups.asm`. |
| `src/jevplays/state/types.py` (new) | `effectiveness(move_type, defender_types) -> float`, `best_moves(moves, defender_types)`. Pure lookup; used only by the accuracy script and its tests. |
| `src/jevplays/state/snapshot.py` (modify) | `read_party` drops slots whose species byte is 0 (mid-catch placeholder). |
| `src/jevplays/brain/decision.py` (modify) | `BattleAction.slot: int | None` for `switch`; `describe()` unchanged. |
| `src/jevplays/brain/battle.py` (modify) | bench labels, `enemy_pokemon.status`, `party` size word, `switch_to` → slot, `supported` = all five. |
| `src/jevplays/executor/battle.py` (modify) | `select_item`, `use_potion`, `throw_ball`, `switch_to`, `apply` for all kinds, #5 guard. |
| `Scripts/make-states.py` (modify) | `battle_items.state`, `battle_two.state` (group `items`). |
| `Scripts/record-fixtures.py` (modify) | `battle_catch`, `battle_heal`, `battle_switch`. |
| `Scripts/accuracy.py` (new) | `uv run Scripts/accuracy.py runs/<dir>`: move-choice accuracy from `decisions.jsonl`. |
| `tests/test_types.py`, `tests/test_battle_macros.py` (extend), `tests/test_battle_brain.py` (extend), `tests/test_snapshot.py` (extend), `tests/test_fixtures.py` (extend), `tests/test_accuracy.py` (new), `tests/rom/test_battle_items.py` (new) | Tests per task. |
| `README.md`, `CLAUDE.md`, spec 8.1/14 | Docs. |

---

### Task 1: The Gen 1 type chart and `effectiveness`

**Files:**
- Create: `src/jevplays/state/data/type_chart.json`, `src/jevplays/state/types.py`
- Modify: `src/jevplays/state/data/README.md`
- Test: `tests/test_types.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `TYPE_CHART: dict[tuple[str, str], float]` loaded from the JSON (keys are display type names as `names.type_name` returns them: `Normal`, `Fighting`, `Flying`, `Poison`, `Ground`, `Rock`, `Bug`, `Ghost`, `Fire`, `Water`, `Grass`, `Electric`, `Psychic`, `Ice`, `Dragon`); `effectiveness(move_type: str, defender_types: Sequence[str]) -> float` (product over defender types; 1.0 when unlisted); `best_moves(moves: list[dict], defender_types: Sequence[str]) -> set[str]` (names of the damaging moves, `kind == "attack"` in the decision's `state_summary` shape, whose `effectiveness(type) * (1.5 if STAB else 1.0)` is maximal; STAB when the move's type is in `attacker_types`, passed as a keyword `attacker_types=()`); returns an empty set when no move is damaging.

The source table is already fetched at `/private/tmp/claude-503/-Users-builder-orca-projects-jevplays/cef7ae7f-42b5-46cc-8fab-57ac894a688b/scratchpad/type_matchups.asm` (85 lines, 82 `db ATTACKER, DEFENDER, EFFECT` rows; `SUPER_EFFECTIVE` = 2.0, `NOT_VERY_EFFECTIVE` = 0.5, `NO_EFFECT` = 0.0; pokered's constants are upper-case, map them to the display names above, e.g. `FIRE` → `Fire`). If the file is missing, fetch `https://raw.githubusercontent.com/pret/pokered/master/data/types/type_matchups.asm`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_types.py
from jevplays.state.types import TYPE_CHART, best_moves, effectiveness


def test_chart_has_the_82_gen1_rows_and_the_famous_ones():
    assert len(TYPE_CHART) == 82
    assert effectiveness("Fire", ["Grass"]) == 2.0
    assert effectiveness("Water", ["Fire"]) == 2.0
    assert effectiveness("Ground", ["Flying"]) == 0.0
    assert effectiveness("Normal", ["Ghost"]) == 0.0
    assert effectiveness("Fire", ["Rock"]) == 0.5
    assert effectiveness("Fighting", ["Rock"]) == 2.0
    assert effectiveness("Normal", ["Normal"]) == 1.0


def test_dual_types_multiply():
    assert effectiveness("Electric", ["Rock", "Ground"]) == 0.0
    assert effectiveness("Water", ["Rock", "Ground"]) == 4.0
    assert effectiveness("Fire", ["Bug", "Grass"]) == 4.0


def test_best_moves_prefers_effectiveness_then_stab_and_ignores_status_moves():
    moves = [
        {"name": "EMBER", "type": "Fire", "kind": "attack"},
        {"name": "SCRATCH", "type": "Normal", "kind": "attack"},
        {"name": "GROWL", "type": "Normal", "kind": "status"},
    ]
    assert best_moves(moves, ["Grass"], attacker_types=["Fire"]) == {"EMBER"}
    assert best_moves(moves, ["Rock", "Ground"], attacker_types=["Fire"]) == {"SCRATCH"}
    assert best_moves(moves, ["Normal"], attacker_types=["Normal"]) == {"SCRATCH"}
    assert best_moves([{"name": "GROWL", "type": "Normal", "kind": "status"}], ["Normal"]) == set()
```

(`Fire` vs `Rock`/`Ground` at 0.5 × 1.5 STAB = 0.75 loses to Normal's 1.0, hence `SCRATCH`.)

- [ ] **Step 2: Run to verify they fail**

Run: `env -u JEVPLAYS_ROM .venv/bin/python -m pytest -q tests/test_types.py` → `ModuleNotFoundError`.

- [ ] **Step 3: Generate the JSON and write `types.py`**

Generate `type_chart.json` with a one-off (not committed) that parses the asm: for each line matching `db\s+(\w+),\s+(\w+),\s+(\w+)`, emit `[Title(attacker), Title(defender), multiplier]` where `Title` maps `FIRE` → `Fire` etc. (all Gen 1 names are single words). Write `json.dumps(rows, indent=0)` with one row per line for a readable diff. Add a README line: "`type_chart.json`: Gen 1 type matchups as `[attacker, defender, multiplier]` rows, 82 entries, from pokered's `data/types/type_matchups.asm`. Only `state/types.py` reads it; Jev never sees effectiveness."

```python
# src/jevplays/state/types.py
"""Gen 1 type effectiveness, for measuring Jev's move choices after the fact. Nothing on the path
to a decision imports this: the spec keeps effectiveness out of what the model sees."""

import json
from collections.abc import Sequence
from functools import reduce
from pathlib import Path

_ROWS = json.loads((Path(__file__).parent / "data" / "type_chart.json").read_text(encoding="utf-8"))
TYPE_CHART: dict[tuple[str, str], float] = {(a, d): float(m) for a, d, m in _ROWS}

STAB = 1.5


def effectiveness(move_type: str, defender_types: Sequence[str]) -> float:
    return reduce(lambda acc, t: acc * TYPE_CHART.get((move_type, t), 1.0), defender_types, 1.0)


def best_moves(moves: list[dict], defender_types: Sequence[str], *, attacker_types: Sequence[str] = ()) -> set[str]:
    """The damaging moves (`kind == "attack"`) with the highest effectiveness against
    `defender_types`, STAB included. Empty when no move does damage."""
    scored = {
        m["name"]: effectiveness(m["type"], defender_types) * (STAB if m["type"] in attacker_types else 1.0)
        for m in moves
        if m.get("kind") == "attack"
    }
    if not scored:
        return set()
    top = max(scored.values())
    return {name for name, score in scored.items() if score == top}
```

- [ ] **Step 4: Run the tests** → pass. Also `env -u JEVPLAYS_ROM .venv/bin/python -m pytest -q tests/test_imports.py`.

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/state/data/type_chart.json src/jevplays/state/data/README.md src/jevplays/state/types.py tests/test_types.py
git commit -m "feat(state): the Gen 1 type chart and an effectiveness lookup for measurement"
```

---

### Task 2: The item and switch macros

**Files:**
- Modify: `src/jevplays/executor/battle.py`, `src/jevplays/brain/decision.py`
- Test: `tests/test_battle_macros.py` (extend; read its existing fixtures for the battle menu rows first)

**Interfaces:**
- Consumes: `select_command` (existing), `cursor_label`, `rows_of`, `CURSOR`.
- Produces: `BattleAction(kind, move=None, target=None, slot=None)` (`slot` is the party index for `switch`; `describe()` unchanged); in `executor/battle.py`: `ITEM_ROWS = (4, 6, 8)` (the visible item slots; the list scrolls after three: walk with `down` and re-read, bounded by 20 presses), `PARTY_ROWS = (1, 3, 5, 7, 9, 11)` (the HP row of party slot i is `2*i + 1`), `SWITCH_ROW = 12`; `select_item(emu, name: str) -> None` (ITEM, then `down` until the cursor label starts with `name`, then A; `MacroError` when it never does, after pressing B twice to back out); `throw_ball(emu) -> None` (`select_item(emu, "POKé BALL")`; the throw runs on its own after A); `use_potion(emu, slot: int) -> None` (`select_item(emu, "POTION")`, wait for `Use item on which`, move the cursor to `PARTY_ROWS[slot]`, A; if the screen then says `won't have any effect`, press B twice and raise `MacroError("the Potion had no effect")`); `switch_to(emu, slot: int) -> None` (`select_command(emu, "PKMN")`, wait for `Choose a POKéMON`, cursor to `PARTY_ROWS[slot]`, A, verify the cursor label is `SWITCH`, A; if the screen says `no will to fight` press B twice and raise `MacroError("<slot> has fainted")`); `apply(emu, action)` dispatches `move`, `run`, `heal` (→ `use_potion(emu, active_slot)`; `apply` gains a keyword `active_slot: int = 0`), `catch` (→ `throw_ball`), `switch` (→ `switch_to(emu, action.slot)`; a `None` slot raises `MacroError`). The `select_move` cursor search uses `next(..., None)` and raises `MacroError("cursor not found in the move list")` after pressing B (issue #5).
- Waiting: reuse `jevplays.executor.dialog.wait_for(emu, predicate, frames)` with `frames=300`; predicates read `rows_of(emu.tilemap())` and search the joined text.

- [ ] **Step 1: Failing tests** (append to `tests/test_battle_macros.py`; use its existing helpers for drawing the battle menu; add row fixtures for the item list, the party list, and the SWITCH sub-menu as the spike printed them):

```python
ITEM_LIST_ROWS = [""] * 4 + [
    "····▶POKé BALL    ·",
    "····         × 5  ·",
    "···· POTION       ·",
    "····         × 3  ·",
    "···· CANCEL       ·",
]
PARTY_LIST_ROWS = [
    "   CHARMANDER·6     ",
    "▶   ········· 22/ 22",
    "   PIDGEY    ·2     ",
    "    ·········  1/ 14",
] + [""] * 10 + ["·Choose a POKéMON. ·"]
SWITCH_MENU_ROWS = PARTY_LIST_ROWS[:12] + ["············▶SWITCH·", "", "·Choose a P· STATS ·", "", "·          · CANCEL·"]
NO_EFFECT_ROWS = PARTY_LIST_ROWS[:14] + ["·It won't have any  ·", "", "·effect.           ·"]


def test_select_item_walks_the_cursor_to_the_named_item_and_presses_a():
    emu = battle_menu_emu()  # the existing helper that draws FIGHT/PKMN/ITEM/RUN with the cursor on FIGHT
    emu.on_press("a", lambda: emu.set_rows(ITEM_LIST_ROWS))  # ITEM opens the list; see the note below
    select_item(emu, "POTION")
    assert emu.presses[-3:] == ["a", "down", "a"]  # A on ITEM, down to POTION, A


def test_select_item_backs_out_when_the_item_is_missing():
    emu = battle_menu_emu()
    emu.on_press("a", lambda: emu.set_rows(ITEM_LIST_ROWS))
    with pytest.raises(MacroError):
        select_item(emu, "ANTIDOTE")
    assert emu.presses[-2:] == ["b", "b"]


def test_switch_to_picks_the_slot_and_confirms_switch():
    emu = battle_menu_emu()
    emu.on_press("a", lambda: emu.set_rows(PARTY_LIST_ROWS), then=lambda: emu.set_rows(SWITCH_MENU_ROWS))
    switch_to(emu, 1)
    assert emu.presses[-4:] == ["a", "down", "a", "a"]  # PKMN (after one `down` from FIGHT), slot 1, SWITCH


def test_use_potion_raises_when_it_has_no_effect():
    emu = battle_menu_emu()
    emu.on_press("a", lambda: emu.set_rows(ITEM_LIST_ROWS), then=lambda: emu.set_rows(NO_EFFECT_ROWS))
    with pytest.raises(MacroError, match="no effect"):
        use_potion(emu, 0)


def test_apply_dispatches_every_kind():
    for action, first in (
        (BattleAction(kind="catch"), "ITEM"),
        (BattleAction(kind="heal"), "ITEM"),
        (BattleAction(kind="switch", target="PIDGEY", slot=1), "PKMN"),
    ):
        emu = battle_menu_emu()
        emu.on_press("a", lambda: emu.set_rows(ITEM_LIST_ROWS if first == "ITEM" else PARTY_LIST_ROWS))
        with contextlib.suppress(MacroError):
            apply(emu, action, active_slot=0)
        assert "a" in emu.presses


def test_select_move_without_a_cursor_raises_macro_error_not_stop_iteration():
    emu = battle_menu_emu()
    emu.set_rows(MOVE_LIST_ROWS_WITHOUT_CURSOR)  # the FIGHT screen with the four moves drawn and no ▶
    with pytest.raises(MacroError, match="cursor"):
        select_move(emu, "SCRATCH")
```

`FakeEmulator` has no `on_press`; add it to `tests/support.py`: `on_press(button, effect, then=None)` registers callables run after the first and second press of `button` (a small queue per button, consumed in order), so a test can script "A opens the list, the next A opens the sub-menu". Keep the existing `step_effects` behavior. The `battle_menu_emu()` helper name is whatever the existing test file uses to build the FIGHT/PKMN/ITEM/RUN screen; if there is none, add one that draws rows 14 and 16 as `·       ·▶FIGHT PKMN ·` and `·       · ITEM  RUN·`.

- [ ] **Step 2: Run to verify they fail**, **Step 3: implement** per the interface (the macros press and read exactly as the constraints describe; every wait is `wait_for(..., frames=300)`), **Step 4: run** `env -u JEVPLAYS_ROM .venv/bin/python -m pytest -q` (all pass), **Step 5: commit**:

```bash
git add src/jevplays/executor/battle.py src/jevplays/brain/decision.py tests/test_battle_macros.py tests/support.py
git commit -m "feat(executor): throw a ball, use a potion, and switch from the battle menu"
```

---

### Task 3: What Jev sees, and the catch placeholder in the party

**Files:**
- Modify: `src/jevplays/brain/battle.py`, `src/jevplays/brain/policy.py` (only `choose_battle_action`'s switch branch), `src/jevplays/state/snapshot.py` (`read_party`)
- Test: `tests/test_battle_brain.py` (extend), `tests/test_snapshot.py` (extend)

**Interfaces:**
- `battle_state`: `enemy_pokemon` gains `"status"` (the `Mon.status` word); a new top-level `"party": "one" | "two" | "three or more"` word (party members with hp > 0, the active one included); each bench entry gains `"label"`: the nickname, and `"<nickname> #2"`, `#3`... for repeats in bench order; bench entries keep name/level/types/hp. Nothing else changes shape (the existing number-leak test must keep passing: labels contain no digits except the `#n` suffix, so amend the leak regex expectation in a NEW test rather than editing the old one, or keep suffixes as words: use `" (second)"`, `" (third)"` instead of `#2`/`#3` so the old test's digit rule still holds — do that).
- `battle_questions`: `switch_to` criteria keyed by `label`; the `catch` criteria mention status: `"true": "We want a party of at least three, `enemy_pokemon` is worth having, and its hp is low enough (asleep or paralyzed helps) for a ball to work"`.
- `choose_battle_action` returns `BattleAction(kind="switch", target=<label>, slot=None)`; `decide_battle` resolves the label to the party slot: the bench list is in party order minus the active slot, so slot = the index in `state.party` of the bench member with that label; `battle_state` records `"slot"` on each bench entry for that purpose (an index is a raw number, but it is not a game quantity; the spec's rule is about levels/HP/money/coordinates; keep it, and note it in the report; if the reviewer objects, resolve via a parallel list kept outside `sj`). `decide_battle`'s `supported` default becomes `frozenset({"move", "run", "heal", "catch", "switch"})`; the "not executable yet" fallback branch stays for callers that pass a smaller set.
- `read_party`: skip a slot whose species byte is 0 (the mid-catch placeholder); `party_count` in `GameState` stays the raw count byte.

- [ ] **Step 1: Failing tests**

```python
# tests/test_battle_brain.py (append)
def test_bench_labels_are_unique_and_switch_to_resolves_to_the_party_slot():
    state = battle(party=(CHARMANDER, PIDGEY, PIDGEY), active_slot=0)  # the file's existing state builder
    sj = battle_state(state, goal="g")
    assert [m["label"] for m in sj["bench"]] == ["PIDGEY", "PIDGEY (second)"]
    assert sj["party"] == "three or more" and sj["enemy_pokemon"]["status"] == "none"
    qs = battle_questions(sj)
    assert list(qs["switch_to"]["criteria"]) == ["PIDGEY", "PIDGEY (second)"]
    response = respond(move="SCRATCH", switch=0.9, switch_to="PIDGEY (second)")  # the file's canned-response helper
    d = decide_battle(sj, qs, response, model="m", input_tokens=1, latency_ms=1)
    assert d.action_value == BattleAction(kind="switch", target="PIDGEY (second)", slot=2)
    assert d.fallback is False and d.answers["switch"]["applied"] and d.answers["switch_to"]["applied"]


def test_heal_and_catch_are_executable_now():
    state = battle(party=(CHARMANDER,), bag=(BagItem("POTION", 1), BagItem("POKE BALL", 2)), lead_hp="low")
    sj = battle_state(state, goal="g")
    qs = battle_questions(sj)
    d = decide_battle(sj, qs, respond(move="SCRATCH", heal=0.9), model="m", input_tokens=1, latency_ms=1)
    assert d.action_value == BattleAction(kind="heal") and d.fallback is False
    d = decide_battle(sj, qs, respond(move="SCRATCH", catch=0.8), model="m", input_tokens=1, latency_ms=1)
    assert d.action_value == BattleAction(kind="catch") and d.fallback is False


def test_party_word_counts_only_the_living():
    fainted = PIDGEY.__class__(**{**PIDGEY.__dict__, "hp": 0})
    assert battle_state(battle(party=(CHARMANDER, fainted)), goal="g")["party"] == "one"
```

```python
# tests/test_snapshot.py (append)
def test_a_party_slot_with_species_zero_is_skipped_mid_catch():
    emu = FakeEmulator()
    write_mon(emu.mem, 0, species=176, ...)  # the support helper's real signature; CHARMANDER
    emu.mem[ram.wPartyCount] = 2  # the game bumps the count before writing the new record
    emu.mem[ram.wPartyMons + ram.PARTY_MON_SIZE] = 0
    s = snapshot(emu)
    assert [m.name for m in s.party] == ["CHARMANDER"] and s.party_count == 2
```

Adapt the helper names (`battle(...)`, `respond(...)`, `write_mon(...)`) to what the files define; if `battle()` lacks a `lead_hp`/`bag` parameter, build the `GameState` the way its neighbours do.

- [ ] **Step 2–5:** run (fail), implement, run everything (`env -u JEVPLAYS_ROM .venv/bin/python -m pytest -q`; the existing fixture tests still decode because the recorded `state_json` files are replayed as-is), commit:

```bash
git add src/jevplays/brain/battle.py src/jevplays/brain/policy.py src/jevplays/state/snapshot.py tests/test_battle_brain.py tests/test_snapshot.py
git commit -m "feat(brain): bench labels, enemy status, and a party-size word; heal, catch, and switch are live"
```

---

### Task 4: The loop passes the active slot, and the safe default stays a move

**Files:**
- Modify: `src/jevplays/loop.py` (`_battle_turn`, `_retry_after_macro_error`, `_after_second_failure`)
- Test: `tests/test_loop.py` (extend)

**Interfaces:** `battle_macros.apply(self.emu, decision.action_value, active_slot=state.active_slot or 0)` at both call sites; `_after_second_failure` unchanged (first usable move). A `MacroError` from `use_potion`/`switch_to` follows the existing retry path (B, then the same action once, then the safe default).

- [ ] **Step 1: Failing test**: a battle-menu `FakeEmulator` with `QuestionBrain(move="SCRATCH", heal=0.95)` and a `low` lead: the loop's presses include the ITEM path (`a` after reaching ITEM) rather than FIGHT, and the decision's action is `"use a Potion"`; a second test where the fake's item list lacks POTION makes the macro raise and the loop ends on the safe default `use SCRATCH` with a status message containing `macro failed`.
- [ ] **Steps 2–5:** run (fail), implement, run all, commit `feat(loop): heal, catch, and switch decisions are carried out`.

---

### Task 5: States and fixtures for the new decisions, and ROM tests for the macros

**Files:**
- Modify: `Scripts/make-states.py` (group `items`: `battle_items`, `battle_two`), `Scripts/record-fixtures.py` (`battle_catch`, `battle_heal`, `battle_switch`)
- Test: `tests/rom/test_battle_items.py` (new), `tests/test_fixtures.py` (extend), `tests/rom/test_snapshot.py` (extend the mode table with `battle_items` and `battle_two` as BATTLE_MENU)

**States** (document in the script's docstring; both are derived from `battle_wild.state`):
- `battle_items.state`: load `battle_wild.state`, write a bag of 5 POKé BALLs and 3 POTIONs into RAM (`wNumBagItems = 2`, then `4, 5, 20, 3, 0xFF` at `wBagItems`), tick once, save. Writing the bag is the same doctoring `goal_hurt` does to HP: the game could be in this state (the Mart sells both).
- `battle_two.state`: load `battle_items.state`, set the enemy's HP to 1 (`wEnemyMonHP`, big-endian u16: `0xCFE6 = 0`, `0xCFE7 = 1`), `throw_ball`, press A through the throw until the nickname box (`yes_no_open`), answer NO, press A until OVERWORLD, then walk up/down in place (`navigate.step`) until `in_battle`, press A until BATTLE_MENU, save. The party is CHARMANDER + PIDGEY.

**Fixtures** (`FIXTURES` entries: state, ask, tweak): `battle_catch` = (`battle_items`, `battle_ask`, set the enemy HP to 2 the same way), `battle_heal` = (`battle_items`, `battle_ask`, `hurt_the_lead` already exists: reuse it; it writes the party record, and in battle the active record at `wBattleMonHP 0xD015` is what `snapshot` shows for `active`: write both), `battle_switch` = (`battle_two`, `battle_ask`, `hurt_the_lead` on both records).

- [ ] **Step 1: Failing tests**

```python
# tests/rom/test_battle_items.py
from jevplays.emulator import ram
from jevplays.emulator.pyboy import Emulator
from jevplays.executor.battle import switch_to, throw_ball, use_potion
from jevplays.state.snapshot import snapshot


def balls(s):
    return next((i.quantity for i in s.bag if i.name == "POKE BALL"), 0)


def test_throwing_a_ball_spends_one(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("battle_items"))
        before = balls(snapshot(emu))
        throw_ball(emu)
        for _ in range(12):
            emu.press("a", settle=40)
        assert balls(snapshot(emu)) == before - 1


def test_a_potion_heals_the_lead(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("battle_items"))
        emu.mem[0xD015], emu.mem[0xD016] = 0, 5  # wBattleMonHP = 5
        use_potion(emu, 0)
        for _ in range(8):
            emu.press("a", settle=40)
        assert ram.read_u16(emu.mem, 0xD015) > 5


def test_switching_brings_the_bench_pokemon_in(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("battle_two"))
        assert snapshot(emu).active_slot == 0
        switch_to(emu, 1)
        for _ in range(12):
            emu.press("a", settle=40)
            if snapshot(emu).active_slot == 1:
                break
        assert snapshot(emu).active_slot == 1
```

```python
# tests/test_fixtures.py (append)
def test_catch_fixture_throws_when_the_enemy_is_almost_down():
    d = replay("battle_catch", decide_battle)  # the file's replay helper; pass model/tokens/latency the way it does
    assert d.action == "throw a Poké Ball" and d.fallback is False


def test_heal_fixture_uses_a_potion_on_a_low_lead():
    d = replay("battle_heal", decide_battle)
    assert d.action == "use a Potion" and d.fallback is False


def test_switch_fixture_decodes_to_a_bench_slot():
    d = replay("battle_switch", decide_battle)
    assert d.fallback is False
    assert d.action_value.kind in ("switch", "move")  # Jev may prefer fighting on; both are legal
    if d.action_value.kind == "switch":
        assert d.action_value.slot == 1
```

If a recording contradicts an assertion (Jev declines to throw, say), do not weaken the test into `assert True`: assert what the recording shows (the noul value and the decoded action agree) and say so in the report.

- [ ] **Steps 2–5:** extend the scripts, `mise run states` (all 18 states), `mise exec -- uv run Scripts/record-fixtures.py --only battle_catch --only battle_heal --only battle_switch` (never print the key; check the JSON for secrets), run `mise exec -- uv run pytest tests/rom -q` and the unit suite, commit:

```bash
git add Scripts/make-states.py Scripts/record-fixtures.py tests/rom/test_battle_items.py tests/rom/test_snapshot.py tests/test_fixtures.py tests/fixtures/responses/battle_catch.json tests/fixtures/responses/battle_heal.json tests/fixtures/responses/battle_switch.json
git commit -m "feat(states): item and two-Pokémon battle states, and recorded heal, catch, and switch answers"
```

Also re-record `battle_trainer` and `battle_wild` (the question wording changed: `catch` criteria, `party`, `enemy status`) in the same commit, per the global constraint.

---

### Task 6: The accuracy script

**Files:**
- Create: `Scripts/accuracy.py`
- Test: `tests/test_accuracy.py`

**Interfaces:** `Scripts/accuracy.py RUN_DIR [--verbose]`: reads `decisions.jsonl` through `jevplays.runlog.RunDir.open`, keeps decisions with `kind == "battle"` and a `move` answer, and for each computes `best = best_moves(sj["our_pokemon"]["moves"], sj["enemy_pokemon"]["types"], attacker_types=sj["our_pokemon"]["types"])` and whether `answers["move"]["choice"]` is in it; prints `moves judged: N, matched the best type: M (P%)`, then with `--verbose` one line per decision: `<id> <ours> vs <enemy types> chose <move> best <set> <ok|miss>`. Decisions with no damaging move count as neither. Importable: `def accuracy(decisions: Iterable[dict]) -> tuple[int, int, list[dict]]` (judged, matched, rows) so the test needs no subprocess; `main(argv)` returns 0, or 2 when the dir is not a run.

- [ ] **Step 1: Failing test**

```python
# tests/test_accuracy.py
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "Scripts" / "accuracy.py"
spec = importlib.util.spec_from_file_location("accuracy", SCRIPT)
accuracy_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(accuracy_mod)


def decision(choice, enemy_types, ours_types=("Fire",)):
    return {
        "kind": "battle",
        "id": f"d-{choice}",
        "state_summary": {
            "our_pokemon": {"name": "CHARMANDER", "types": list(ours_types), "moves": [
                {"name": "EMBER", "type": "Fire", "kind": "attack"},
                {"name": "SCRATCH", "type": "Normal", "kind": "attack"},
                {"name": "GROWL", "type": "Normal", "kind": "status"},
            ]},
            "enemy_pokemon": {"name": "X", "types": list(enemy_types)},
        },
        "answers": {"move": {"primitive": "choice", "choice": choice}},
    }


def test_accuracy_counts_matches_against_the_best_typed_move():
    log = [
        decision("EMBER", ["Grass"]),            # ok
        decision("SCRATCH", ["Grass"]),          # miss
        decision("SCRATCH", ["Rock", "Ground"]), # ok (Fire is resisted)
        {"kind": "goal", "id": "g", "state_summary": {}, "answers": {}},  # ignored
    ]
    judged, matched, rows = accuracy_mod.accuracy(log)
    assert (judged, matched) == (3, 2)
    assert [r["ok"] for r in rows] == [True, False, True]


def test_main_rejects_a_directory_without_a_run(tmp_path, capsys):
    assert accuracy_mod.main([str(tmp_path)]) == 2
    assert "run.json" in capsys.readouterr().err
```

- [ ] **Steps 2–5:** run (fail), implement (the script adds `src` to `sys.path` the way `Scripts/make-states.py` does, or relies on the installed package: check how the other scripts import `jevplays`), run, then try it on a real run: `mise exec -- uv run Scripts/accuracy.py <the scratchpad demo run>` (`/private/tmp/claude-503/-Users-builder-orca-projects-jevplays/cef7ae7f-42b5-46cc-8fab-57ac894a688b/scratchpad/runs-demo/20260920-185526`, 27 decisions from a first-choice stand-in, so the number is meaningless; the report records that it runs), commit `feat(scripts): measure how often Jev's move matches the best-typed attack`.

---

### Task 7: Spec 8.1 and 14, docs, full check

- Spec 8.1: the state example gains `enemy_pokemon.status`, `party`, and bench `label`s; the `switch_to` row says "bench labels"; the `catch` criteria mention status; replace "Milestone 2 executes `move` and `run`..." with "As of milestone 4a all five actions execute; see 9 for the macros." Add a paragraph under 9 (executor) describing the three macros' screens as the Global Constraints list them. Section 13: the accuracy script exists (`Scripts/accuracy.py`), reads `decisions.jsonl`, and reports the match rate against the best-typed attack with STAB. Section 14: milestone 4 becomes 4a (this) and 4b (Route 22, fighter goals or generated options, the party-reorder macro, the real run to Brock). Mark amendments the way the file marks 3a/3b's.
- README: status milestone 4a; the accuracy script's one-liner under Runs; a sentence that battles now heal, catch, and switch.
- CLAUDE.md: "type effectiveness lives in `state/types.py` for measurement only; never pass it to Jev".
- Checks: `mise run check`; `env -u JEVPLAYS_ROM .venv/bin/python -m pytest -q`; `mise exec -- uv run pytest -q`; `git ls-files | grep -E '\.state$|\.ram$|mise\.local|^runs/'` prints nothing; `grep -rl "sk-\|api_key" tests/fixtures/responses/` prints nothing.
- Commit `docs: milestone 4a spec amendments and README`; the controller pushes and opens the PR "Milestone 4a: heal, catch, switch, and the accuracy script".

---

## Self-review

**Spec coverage:** 8.1 questions and policy (Task 3, unchanged thresholds); 8.1 "heal/catch/switch macros land in milestone 4" (Task 2, 4); 12 fallback semantics (Task 3 keeps the missing-answer fallback and the smaller-`supported` fallback); 13 fixtures per scenario (Task 5) and the accuracy script (Task 6); 14 (Task 7). Deferred from milestone 2 and closed here: `switch_to` keyed by species (Task 3), enemy status not sent (Task 3), #5 (Task 2).

**Placeholder scan:** Task 2's `on_press` helper and `battle_menu_emu()` are named "reuse if present, else add" with the shape given; Task 3's `battle()`/`respond()`/`write_mon()` likewise. No TBDs.

**Type consistency:** `BattleAction.slot` (Task 2) is what Task 3's decoder sets and Task 2's `apply` reads; `apply(emu, action, active_slot=)` (Task 2) is what Task 4 calls; `best_moves(moves, defender_types, attacker_types=)` (Task 1) is what Task 6 calls; the state names `battle_items`/`battle_two` (Task 5) are what the ROM tests and fixtures load.
