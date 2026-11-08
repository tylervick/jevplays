# Past Brock (Misty, opt-in) — implementation report

Branch `tylervick/misty`, worktree `.worktrees/misty`. Spec: `docs/superpowers/specs/2026-10-01-past-brock-design.md`.
Not pushed; no PR.

## Commits (on top of 9ebf29c, the spec)

- `ea68c7a` feat(executor): name Mt. Moon and the Cerulean maps, and the Cerulean Mart's shelf
- `242a785` feat(executor): a beat_misty milestone past the default spine, offered once walked to
- `9673841` feat(executor): talk_leader macro and LoopConfig.until
- `77a10f0` feat(cli): `jevplays run --until` names the badge a run finishes at

## Tests added (all written first and seen failing)

- `tests/test_names.py::test_mt_moon_and_the_cerulean_buildings_have_display_names` (60–68; Route 3/4 = ids 14/15 via the existing rule)
- `tests/test_maps.py::test_cerulean_has_node_names_but_no_hand_written_links` (node names, MAP_IDS, nothing in LINKS, routes only over a walked overlay)
- `tests/test_ram.py::test_the_cerulean_mart_inventory_is_the_third_entry_of_the_rom_table`
- `tests/rom/test_shop.py`: one new assertion for map 67 (existing assertions untouched) — **passes against the ROM**, so 0x2453 and the shelf are verified
- `tests/test_goals.py`: story order/fields, Misty available/done, `active_milestone(until=...)`, ValueError on unknown id, Misty legs over the walked graph (no walk leg)
- `tests/test_options.py::test_a_milestone_with_a_destination_is_not_offered_until_the_run_has_walked_there`
- `tests/test_loop.py`: `talk_leader` picks the northernmost sprite and talks from (x, y+1) facing up; no sprites -> False, no presses; `until="beat_misty"` carries on past badge one and finishes with "Cascade Badge"; `LoopConfig().until == "beat_brock"`
- `tests/test_cli.py`: `--until` default/choices; `finished_line` names the badge
- `tests/test_branch_alternatives.py::test_a_logged_milestone_past_brock_is_found_again`

No existing test edited or deleted.

## Check output

- `mise exec -- uv run pytest -q`: **642 passed, 1 skipped** (the skip is pre-existing: `tests/rom/test_world.py:54`, battle_wild is mid-battle). ROM tests collected and run.
- `mise run check`: exit 0 (lint clean, same 642 passed / 1 skipped).
- `tests/test_fixtures.py`: 10 passed. Fixtures not re-recorded.
- Byte-identity: `explore_state` + `explore_questions` for the default spine at all four stages (no milestone done -> Brock done), plus the starter question, were JSON-dumped from the pre-change tree (9ebf29c via `git archive`, confirmed it imported that tree) and from HEAD: **identical, 8977 bytes each**. No new keys reach Jev.

## Smoke test

`mise exec -- uv run jevplays run --state states/brock_award.state --unpaced --no-brain --until beat_misty --no-log --port 8999`, ~5 minutes, then killed.

```
dashboard: http://127.0.0.1:8999
run: not logged (--no-log)
brain: off
goal: beat_brock · option: milestone
goal: beat_misty · option: heal
goal: beat_misty · option: door_255
goal: beat_misty · option: none
goal: beat_misty · option: exit_north
goal: beat_misty · option: exit_south
... (alternating)
```

Counts over the whole run (795 goal lines): exit_south 315, exit_north 295, none 148, heal 1, door_255 1, beat_brock/milestone 1.
The milestone switched from beat_brock to beat_misty once the Boulder Badge landed, and no milestone option was
offered afterwards (no route to cerulean_gym yet — the new rule working). Nothing crashed. The only traceback is
the `KeyboardInterrupt` uvicorn re-raises when the process is killed (SIGTERM -> SIGINT handler), at shutdown —
not from this change. With no brain, the offline policy (first untried option) bounces between a north and a south
exit for the whole window rather than heading east; expected for `--no-brain`, and says nothing about Jev.

## Deviations from the brief, and why

1. **`MILESTONES` keeps exactly the three-goal spine; Misty lives in a new `ALL_MILESTONES = [*MILESTONES, BEAT_MISTY]`.**
   Adding BEAT_MISTY to `MILESTONES` itself would break three existing tests unchanged:
   `test_goals.py::test_milestones_are_the_spine_in_order` (exact id list), and `MILESTONES[-1]` being Brock in
   `test_loop.py::test_the_battle_question_carries_the_milestone_the_run_is_working_towards` and
   `test_starter.py` (and the live `loop.py` starter question + `record-fixtures.py` use `MILESTONES[-1]`, so it would
   also have changed the starter question Jev sees -> fixtures). `active_milestone` walks `ALL_MILESTONES` up to `until`.
   Added helpers: `DEFAULT_UNTIL`, `BADGE_MILESTONES`, `milestone_by_id`, `finish_words`.
2. **`Loop._refresh_milestone` calls `active_milestone(state)` with no `until` argument when `until` is the default**,
   and `active_milestone(state, until=...)` otherwise. `test_loop.py::test_tried_marks_expire_when_a_milestone_is_done`
   monkeypatches `active_milestone` with `lambda state: ...`; passing `until=` always would make it raise TypeError.
3. **`--until` choices are the milestones that end in a badge** (`beat_brock`, `beat_misty`), not every milestone id —
   matches the `{beat_brock,beat_misty}` in the brief, and guarantees the finish line has a badge (the description
   fallback is still there in `finish_words`).
4. `branch/alternatives.goal_by_id` now searches `ALL_MILESTONES` so a `beat_misty` decision can be branched.
5. README: one sentence on `--until beat_misty`.
6. Item 7: `PROGRESS_WORDS` already maps `beat_brock` -> "earned the Boulder Badge". `beat_misty` exists in
   `events.json` (191) but is not in `TRACKED_FLAGS`, so no word was added (per the brief).

## Not verified / concerns

- **Map ids 60–68 names and the Cerulean node ids (3, 64, 65, 67)** come from pokered's map constants; only 67's Mart
  inventory is ROM-verified. No save state in Cerulean exists to check them in-game.
- **`talk_leader`'s premise (Misty is the northernmost sprite; the tile below her is walkable and she faces down)** is
  unverified without a Cerulean Gym state. If a gym puts a trainer or a non-person sprite further north, it talks to
  the wrong one. Only the unit test with a fake emulator covers it.
- **`starter_state` still uses `MILESTONES[-1]` (Brock)** for a `--until beat_misty` run — deliberate (unchanged question,
  first gym is what the starter faces), but worth knowing.
- **Heal/shop past Pewter**: `options.CENTERS` was not extended with `cerulean_pokecenter` (out of the brief's scope),
  so a hurt party in Cerulean routes back to Pewter to heal. Likely the first follow-up a measurement run finds.
- **Branch replays** (`branch/runner.py`) build `LoopConfig` without `until`, so a replayed `beat_misty` decision runs
  under the default spine (its `_refresh_milestone` will see the Boulder Badge and finish). Not addressed.
- `--resume` does not read `until` back from run.json; pass `--until` again on resume.

---

## Follow-up: closing the two gaps

### Commits

- `2e21ed9` feat(executor): heal at the Cerulean and Mt. Moon Pokémon Centers once walked to
- `4ef5019` feat(cli): `until` survives --resume and `jevplays branch`

### What changed

1. **Healing past Pewter.** `options.CENTERS` gains `mt_moon_pokecenter` (68, new `MT_MOON_POKECENTER` node in
   `maps.NODE_NAMES`) and `cerulean_pokecenter` (64). Nothing goes into LINKS: `_heal_option` already takes the
   shortest route over LINKS plus the walked graph, so a center past Pewter is offered only once the run has been inside it.
2. **`until` on resume.** `--until` uses a small argparse Action that records that the flag was given
   (`until_given`). `cli.resolve_until(args, run_dir)`: an explicit `--until` wins; on `--resume` it reads
   `flags.until` from run.json (`goals.until_from_flags`; missing means beat_brock); otherwise the parsed value.
   `cmd_run` resolves it before building `LoopConfig`, so the finish line uses it too.
3. **`until` in branching.** `Job.until` (defaults to beat_brock, so the 10-argument `Job(...)` in `tests/rom/test_branch.py`
   still works); `runner.recorded_until(info)`; `runner.jobs_for(...)` (job construction moved out of `measure`
   unchanged apart from passing `until`); `runner.branch_config(job)` builds the branch's LoopConfig with `until`.
   Stopper: it returns "done" when `loop.finished` or when the active milestone is no longer the one the snapshot
   recorded. It assumes nothing about beat_brock being last. With `until` carried, a beat_brock decision from a
   misty run is "done" when the milestone moves on to beat_misty, and a beat_misty decision is "done" at badge two.
   Before this change it would have finished immediately. `candidates()`' reference frames come from `note_milestone`,
   which the loop writes for every milestone, beat_misty included.

### Tests added (seen failing first)

- `tests/test_options.py::test_a_hurt_lead_in_cerulean_heals_at_the_cerulean_center_once_the_run_has_walked_there`:
  Cerulean City, hurt lead, walked graph reaching cerulean_pokecenter -> "go heal at Cerulean Pokémon Center"
  with one warp leg into map 64; without that crossing -> "go heal at Pewter Pokémon Center"
- `tests/test_options.py::test_the_past_pewter_centers_heal_and_are_not_left_to_heal_in`
- `tests/test_cli.py::test_a_resumed_run_keeps_the_until_it_was_started_with` (run.json value / explicit wins / old run.json / fresh run)
- `tests/test_branch_runner.py::test_every_branch_carries_the_recorded_runs_until` (`recorded_until`, `jobs_for` skips done keys and carries `until`, `branch_config`)

No existing test edited.

### Check

`mise run check`: exit 0, **646 passed, 1 skipped** (the same pre-existing ROM skip). ruff clean.

### Not verified / concerns

- The heal macro talks to the nurse at the fixed `shop.NURSE_TILE`. Gen 1 Pokémon Centers share a layout, so it should
  hold in Cerulean and at Mt. Moon, but neither has a save state to prove it.
- CLAUDE.md still says "the three milestones in `executor/goals.py` are the only hand-written story". There are now
  four (the spec amends it). I left CLAUDE.md alone; the PR may want to change it.

---

## Round 3: rebase onto #122 and review fixes

### Rebase

`tylervick/misty` was rebased onto `origin/tylervick/clerk-loop` (3717aff, PR #122). There was one conflict,
in `tests/test_options.py`, where both branches had appended a test at the end of the file. I kept both. The
`executor/options.py` changes merged cleanly: #122's clerk/shopping_list skip in `_npc_options` and this branch's
destination rule in `_milestone_option`. The misty PR stacks on #122.

### Commits (new)

- `7254bf5` fix(executor): talk_leader picks the leader deterministically and stands where it can
- `5f9f10d` fix(cli): refuse an unknown `until` up front, and record a resume's explicit one

### What changed

- **a. `talk_leader`** (`Loop._talk_leader`):
  - returns False unless `state.map_id == maps.map_id_of(active milestone.destination)`, and False with no milestone;
  - the leader is the person with a non-zero picture and the smallest `(y, x, slot)`;
  - the tile and facing come from `options._npc_target(grid, blocked, state.tile, leader)`, as for NPC options;
  - returns False when `_npc_target` finds nothing.
- **b. Validation.** `goals.check_until` accepts only `BADGE_MILESTONES` and raises a ValueError that lists the valid
  ids. `until_from_flags` uses it.
  - `jevplays run --resume` exits 2 with that message. It now resolves `until` before `resolve_resume`, so a refused
    resume leaves the run dir untouched.
  - `jevplays branch` (`measure`) checks it straight after opening the run, before candidates, the store, the
    emulator or any worker, and exits 2.
  - `LoopConfig.__post_init__` also refuses an unknown `until`, so a bad value fails once at construction instead
    of on every turn.
  - The pyboy import in `measure` moved down to just before the emulator is opened.
- **c. Write-back.** `RunDir.set_flag(name, value)`. `resolve_until` on `--resume` with an explicit `--until` writes
  the value into run.json's flags.
- **d. Tests:** the beat_brock -> beat_misty handover with `until=beat_misty` clears the tried marks and announces
  "milestone done: beat_brock"; the no-route rule with the real `BEAT_MISTY`.

### Tests added (the new behaviour tests were seen failing first; the two in d. passed immediately, since they cover existing behaviour)

- `tests/test_loop.py`: `test_talk_leader_talks_from_a_reachable_side_when_the_tile_below_is_taken`,
  `test_talk_leader_breaks_a_tie_for_northernmost_by_x_then_slot`, `test_talk_leader_does_nothing_off_the_milestones_map`,
  `test_the_handover_from_brock_to_misty_clears_the_tried_marks`
- `tests/test_options.py::test_the_real_misty_milestone_is_withheld_until_the_run_has_walked_to_her_gym`
- `tests/test_cli.py`: `test_an_explicit_until_on_resume_is_written_back_to_run_json`,
  `test_an_unknown_until_in_run_json_is_refused_before_the_run_starts`
- `tests/test_branch_runner.py`: `test_an_unknown_until_is_refused_before_any_branch_runs`,
  `test_the_loop_refuses_an_unknown_until_when_it_is_built`

**One test edited:** `test_talk_leader_talks_to_the_northernmost_person_from_the_tile_below` (added earlier on this
branch, never on main). The review's map check needs an active milestone, so the test now sets
`loop.milestone = BEAT_MISTY`. It also puts the player directly south of the leader, so the nearest talking tile
`_npc_target` finds is still `(4, 3)` facing up. The expected call `(4, 3, "up")` is unchanged.

### Check

`mise run check`: exit 0, **656 passed, 1 skipped** (the same pre-existing ROM skip).

### Still unverified

The Cerulean Gym layout, and whether Misty is the northernmost sprite there, still need a save state in the gym.
