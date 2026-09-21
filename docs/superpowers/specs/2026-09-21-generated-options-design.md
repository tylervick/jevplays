# Generated options: Jev picks what to do next (milestone 4b)

**Status:** approved design, 2026-09-21. Amends `2026-09-20-jevplays-design.md` sections 8.2, 9, 11, 13, 14; the base spec's rules (Jev judges, code executes; no raw numbers, coordinates, or screenshots to Jev; counters are scripted) all still apply.

## 1. Purpose

Milestone 3a taught the loop the first hour of the story as nine hand-written goals, one per beat. That works, and the #17 baseline run reaches the Boulder Badge in 84 decisions with it, but every later beat would need another entry, and the run never shows Jev deciding *where to go*. This design replaces most of the table with options that code generates from the world Jev is standing in, so the story emerges from Jev's choices, and keeps a short list of badge-level milestones as the spine that guarantees progress. The measure is the same run to the Boulder Badge, compared with the baseline.

Decisions made with Tyler: hybrid (milestones plus generated options); the milestone is always one of the options, never a forced takeover; success is the badge within about three times the baseline's decisions; options come from the map (RAM), not from the screen, and carry memory words because Jev has no memory.

## 2. Options

An **option** is something the loop can carry out from where the player stands, described in words. `executor/options.py` builds the list at every overworld decision point (the navigator idle, no macro running) from the same RAM reads the navigator already uses:

| kind | one per | text | plan |
| --- | --- | --- | --- |
| `exit` | map connection (`read_connections`) | "go north to Route 2" | an `edge` leg |
| `door` | distinct warp destination on the map (`read_warps`, grouped by destination; `WARP_LAST_MAP` inside a building) | "enter Viridian Pokémon Center", "enter Viridian School", "go back outside" | a `warp` leg |
| `npc` | sprite reachable from the player (A* to any of its four neighbours), capped at the six nearest | "talk to the nurse behind the counter", "talk to a youngster to the north" | walk to the neighbour, face, `talk_to`; a nurse runs `heal_at_nurse`, a Mart clerk runs `buy_pokeballs` (counters stay scripted, base spec 8.3) |
| `grass` | map with grass cells | "train in the tall grass here" | the wander macro until a battle interrupts |
| `milestone` | active milestone whose map is not the current one | "head for <milestone description>" | the milestone's legs (`legs_to`) and its `after` macro |
| `heal` | lead below half HP and a Pokémon Center node reachable in `maps.LINKS` | "go heal at Viridian Pokémon Center" | legs to the Center, then `heal_at_nurse` |

Text rules: map names from `names.map_name`; NPC nouns from `state/data/sprites.json` (sprite picture id to a noun phrase, transcribed from pokered's `constants/sprite_constants.asm`: `SPRITE_NURSE` "the nurse", `SPRITE_OAK` "Professor Oak", `SPRITE_POKE_BALL` "an item on the ground", unknown ids "someone"); places from the sprite's position relative to the player as compass words ("to the north", "to the south-east") plus "near" when within four tiles, and "behind the counter" when the sprite is a nurse or clerk. No numbers, no coordinates.

Order as built (`generate`): the `milestone` option first, then `heal`, then the exits, the doors, the NPCs nearest-first, and the grass last. The order matters because it is code's fallback, not Jev's: `choose_explore` takes the first option when there is no usable `explore` answer, and a brainless run takes the first one not marked `tried` -- so the two options that keep a run moving and keep it alive lead, and both of those runs still walk the story. After them the generated options follow the order the RAM is read in (connections, warps, sprites by walked distance), with the grass, which is under the player's feet rather than somewhere to go, at the end. The verb an NPC option starts with follows its noun: "talk to" for a person, "pick up" for an item lying on the ground (the macro is `talk_<slot>` either way, which is how an item ball is picked up).

Option ids are stable slugs the loop and the log key on: `exit_north`, `door_<dest map id>`, `npc_<slot>`, `grass`, `milestone`, `heal`. An option carries its `kind`, `text`, `memory`, and a `plan` (a list of `Leg` plus an optional `after` macro name), so the loop executes it the way it executes a goal today.

## 3. Memory

Jev is asked fresh each time, so code tells it what has already happened through one **memory word** per option:

- `new`: never done from this map.
- `visited`: an exit or door whose destination map has been entered before in this run.
- `talked already`: an NPC this run has talked to (keyed by map id and sprite slot).
- `tried`: chosen before from this map with no change afterwards (no new map, flag, party member, or item), so the option is on the table but marked.

`Memory` (in `executor/options.py`) holds `visited_maps`, `talked`, and `tried` (keyed by map id and option id). The loop owns one per run, updates it when an option's plan finishes, and writes it to `runs/<stamp>/memory.json` after each change; `--resume` reloads it. The memory word goes into the option text Jev sees, in parentheses.

## 4. What Jev sees (amends base spec 8.2)

The goal decision point becomes the **explore** decision point. State sent:

```json
{
  "map": "Viridian City",
  "progress": ["got a starter", "delivered Oak's parcel", "got the Pokédex"],
  "party": [{"name": "CHARMANDER", "level": 9, "hp": "hurt"}],
  "money": "comfortable",
  "bag": {"POKE BALL": "few"},
  "milestone": "Challenge Brock at the Pewter Gym and earn the Boulder Badge",
  "options": {
    "exit_north": "go north to Route 2 (new)",
    "door_41": "enter Viridian Pokémon Center (visited)",
    "npc_3": "talk to an old man to the north (talked already)",
    "grass": "train in the tall grass here (tried)",
    "milestone": "head for the Pewter Gym (new)"
  }
}
```

`progress` is the set story flags as words (a small table in `brain/explore.py` from `TRACKED_FLAGS`; unlisted flags are omitted). Party, money, and bag use the buckets `brain/goal.py` already has. Levels are the only raw numbers.

Questions, one request:

| id | primitive | instructions | criteria |
| --- | --- | --- | --- |
| `explore` | Choice | Which of `options` should we do next to make progress in the game, given `progress`, the `milestone`, and what each option says about whether we have done it before? | the options' texts, keyed by option id |
| `needs_heal` | Noul | Should the party heal before doing anything else? | true when the party is hurt enough that the next battle could be lost |

Policy (`policy.py`): `needs_heal` above `HEAL_FIRST_THRESHOLD` (0.7) with a `heal` option present wins; otherwise the `explore` choice; a choice not in the option list falls back to `milestone` if present, else the first option, marked `fallback`. Decision kind `explore`, action text "explore: <option text>", `action_value = ExploreAction(option_id, kind)`.

`brain/goal.py`'s `decide_goal` and `goal_questions` are retired with this design (the loop no longer chooses among goals; milestones are sequential), together with the `goal_*` fixtures and their tests. Its bucket helpers move to `brain/explore.py`.

## 5. Milestones (amends base spec 9's goal table)

`executor/goals.py` keeps `Goal`, `legs_to`, `battle_goal`, and three milestones, in order:

1. `get_starter`: done when `got_starter`; legs and `after` as today.
2. `get_pokedex`: available after the starter, done when `got_pokedex`; legs to the Mart until `got_oaks_parcel`, then to the lab; `after="talk_oak"` as today.
3. `beat_brock`: available after the Pokédex, done when `beat_brock`; legs to the Pewter Gym, walk to Brock, `after="talk_brock"`.

The active milestone is the first one not done. `wake_old_man`, `buy_pokeballs`, `buy_potions`, `train_to_level_12`, `cross_viridian_forest`, `heal_at_center`, and `train_nearby` are removed: each is now something Jev can choose as an option (the old man is an NPC, the shops are clerks, training is the grass, healing is the `heal` option). The milestone's legs still use `maps.LINKS` for routing; if the current map is not in the link table the milestone option is omitted and Jev has only the generated options until it walks back onto a known map.

The battle goal (`battle_goal`) composes the milestone's description with the standing clause, as #21 built it.

## 6. The loop (amends base spec 7 and 9)

`_overworld_turn`, in order: if the active milestone is done, advance to the next and publish `status_event("running", "milestone done: <id>")`; if the last milestone is done, publish `status_event("finished", "Boulder Badge")` and stop the run (a new status value; the page shows it in the pill; this is the fix for #29, so a finished run no longer ends on "paused"). If a plan is busy, walk it as today. Otherwise generate options, ask, and start the chosen option's plan.

Budgets: an option has a wall-clock budget (`OPTION_BUDGET_S`, 90 s) after which it is dropped and marked `tried`; a stuck navigator or a macro returning False marks it `tried` too (no retry counter: the memory word replaces `GOAL_RETRIES`; Jev sees "tried" and decides). Interruptions (battles, prompts, menus) work as today.

Without a brain: the first option in table order that is not `tried`, milestone first when present (so an offline run still walks the story).

## 7. Runs and the dashboard (amends base spec 10 and 11)

`memory.json` joins the run dir and is reloaded on `--resume`. `decisions.jsonl` carries the explore decisions (kind `explore`) with the full option list in `state_summary`, so replay shows them. The page needs no new events: the explore Choice renders as bars, the goal line shows the milestone (from the `milestone` field in the decision's state summary), and log entries read `explore: go north to Route 2`. The `finished` status is styled like `stopped`.

## 8. Measurement (amends base spec 13)

`Scripts/accuracy.py` adds an exploration section after the battle numbers: decisions by kind; explore decisions split by option kind (exit, door, npc, grass, milestone, heal); how many explore choices were `milestone` versus everything else; distinct maps seen; total decisions. The 4b run is recorded from `states/route1.state`, unpaced, to the Boulder Badge; success is the badge within about 250 decisions (three times the #17 baseline's 84), with move accuracy reported alongside for comparison. The numbers go in the PR body and in a comment on #17.

## 9. Testing (amends base spec 13)

- Unit, on `FakeEmulator` with `install_map`: option generation for a map with two connections, two warps to one destination and one to another, three sprites of which one is unreachable, and grass; memory words for each state of `Memory`; NPC nouns and places; the explore state JSON's number-leak test; policy (heal first, fallback to milestone); the loop executing an exit, a door, an NPC, and the milestone option, and marking `tried` after a stuck navigator.
- ROM: options generated on `viridian.state` include the north exit to Route 2, the Center and Mart doors, and the old man; executing the old man option from `viridian_oldman.state` talks to him and he moves.
- Fixture: `explore_viridian.json` recorded on `viridian_oldman.state` and replayed through `decide_explore`.
- The run itself is the last task of the plan, with its numbers.

## 10. Out of scope, filed as issues

- The party-reorder macro (base spec 14's 4b line): catches are rare at the current threshold, so leading with a caught Pokémon has no run to serve yet.
- Route 22 in `maps.LINKS`: exits come from RAM, so Jev can walk there; only milestone routing needs the table.
- Replacing `maps.LINKS` with routes discovered from `memory.visited_maps` (a later milestone; it would let milestones route through any map the run has seen).
