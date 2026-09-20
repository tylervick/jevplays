# Jev plays Pokémon: a System One agent with a live probability dashboard

Date: 2026-09-20
Status: approved design (sections reviewed in conversation), awaiting spec review

## 1. Purpose

Jev, TypeSafe's System One model, plays Pokémon Red on a headless emulator while a local web
dashboard shows the game screen next to live probability bars for every decision Jev makes. It is
a showcase of the TypeSafe programming model: code owns the workflow and executes, Jev supplies
the judgments, and the audience sees exactly what the model was asked and how sure it was.

The name is a nod to Twitch Plays Pokémon. Here Jev replaces the crowd.

## 2. What Jev is, and what that forces

Jev accepts text only and returns typed answers with calibrated probabilities. It does not
generate text, plan, or remember anything between calls. The documented weak spots that matter
here are literal reading, arithmetic and counting, spatial reasoning from raw coordinates,
multi-hop indirection, and accuracy loss when state fills with irrelevant detail.

So the design is: **Jev judges, code executes.** Code reads the game state from emulator RAM,
recognizes decision points, sends Jev a small state and a bundle of narrow questions, applies an
explicit policy to the answers, and presses the buttons. Jev never sees a screenshot or a
coordinate pair. It sees names, types, and words like "low" for HP.

Pricing and limits (jev-1.13 as of 2026-09-17): 4.2 cents per million input tokens, 1,200
requests per minute, 64k tokens per request. A few decisions per second is well within budget.
Rate limits are documented as adjusting dynamically, so the loop must tolerate stalls.

## 3. Non-goals for this version

- No Twitch, OBS, or chat integration. The dashboard is a local page. It has a fixed
  1920x1080 layout so it can later be an OBS browser source without changes.
- No image input. Jev is text-only.
- No generations beyond Pokémon Red/Blue. The RAM map and PyBoy wrapper are Gen 1 specific.
- No RAM writes to cheat progress. The one scripted shortcut is PyBoy's `start_game`, which
  presses buttons through the intro like a player would.
- No attempt to beat the game in this version. The measurable goal is the first badge (Brock).
- No persistence beyond a decision log and save states on disk.
- No ROM in the repository, ever. The player supplies their own dump.

## 4. Repository

`github.com/tylervick/jevplays`, public, MIT. Tooling copies graphghan: mise pins the tools, uv
owns Python, hk runs the hooks, Renovate bumps the pins, CI runs on SHA-pinned actions.

```
jevplays/
  README.md  LICENSE  CLAUDE.md  pyproject.toml  uv.lock  .python-version  .gitignore
  mise.toml  hk.pkl  orca.yaml  renovate.json
  .github/workflows/ci.yml
  src/jevplays/
    __init__.py
    cli.py            `jevplays` entry point: run, replay, state
    loop.py           the orchestrator (section 6)
    emulator/
      __init__.py
      pyboy.py        Emulator: headless PyBoy, tick, buttons, save/load state, frame grab
      ram.py          named WRAM addresses from the pokered symbol file, plus text decoding
    state/
      __init__.py
      snapshot.py     GameState dataclasses and `snapshot(emulator) -> GameState`
      modes.py        decision-point detection: `mode(emulator) -> Mode`
      names.py        species, move, type, map and item name tables
    brain/
      __init__.py
      client.py       one thin wrapper over AsyncTypeSafeClient with logging and timing
      battle.py       questions + decode for the battle decision point
      goal.py         questions + decode for the overworld idle decision point
      prompt.py       questions + decode for yes/no prompts and menus
      policy.py       thresholds and priorities, named constants, nothing else
      decision.py     the Decision record (section 8)
    executor/
      __init__.py
      macros.py       button sequences for battle menus, prompts, menus
      navigate.py     A* over the collision window, waypoint following, warps
      maps.py         hand-written waypoint graph for the early game
      goals.py        the goal table: availability and completion from event flags
    dashboard/
      __init__.py
      server.py       Starlette app: static page + websocket event stream
      events.py       event schemas (frame, state, decision, status)
      static/         index.html, app.js (ES modules, no build step), styles.css
  tests/              unit tests (no ROM, no API key)
  tests/rom/          integration tests, skipped unless JEVPLAYS_ROM is set
  tests/fixtures/     recorded TypeSafe responses, synthetic collision maps
  docs/superpowers/{specs,plans}/
  runs/               gitignored: one directory per run
```

Environment: `JEVPLAYS_ROM` is the path to a Pokémon Red or Blue `.gb` file. `TYPESAFE_API_KEY`
is read by the SDK. `.gitignore` covers `roms/`, `runs/`, `*.gb`, `*.gbc`, `*.state`, `.venv/`
and the usual caches.

Dependencies: `pyboy` 2.7, `typesafe-sdk` 0.7, `numpy`, `pillow`, `starlette`, `uvicorn`,
`websockets`. Dev group: `pytest`, `pytest-asyncio`, `ruff`. Python 3.12.

CLAUDE.md carries the rules from graphghan and waddle: GitHub Issues is the only backlog,
conventional commits, work lands through pull requests, never edit a test to make it pass,
learnings that can be checks become checks.

## 5. Emulator layer

`Emulator` wraps `pyboy.PyBoy(rom, window="null")`.

- `tick(frames: int)` advances the emulator. Rendering is on only when the dashboard wants a
  frame, at most 15 per second of wall clock.
- `press(button: str, hold_frames=8, settle_frames=8)` presses and releases one of
  `a b start select up down left right`, then ticks so the game registers it.
- `save(path)` and `load(path)` wrap PyBoy save states.
- `frame() -> bytes` returns the current screen as JPEG, from `screen.ndarray` (144x160x4).
- `mem[addr]` reads one byte; `mem.u16(addr)` reads big-endian pairs, which is how Gen 1 stores
  HP and money.

`ram.py` names every address the state layer reads, using the pokered symbol names as the
constant names so a reader can look each one up in the disassembly. The set needed is:
`wIsInBattle`, `wCurMap`, `wXCoord`, `wYCoord`, `wPartyCount`, `wPartySpecies`, `wPartyMons`
(with the per-mon layout: species, HP, level, status, types, moves, PP), `wBattleMonHP`,
`wBattleMonMaxHP`, `wEnemyMonSpecies`, `wEnemyMonHP`, `wEnemyMonMaxHP`, `wEnemyMonLevel`,
`wEnemyMonType`, `wObtainedBadges`, `wPlayerMoney`, `wNumBagItems`, `wBagItems`, `wEventFlags`,
`wCurrentMenuItem`, `wMaxMenuItem`, `wTopMenuItemY`, `wMenuWatchedKeys`, and `wTextBoxID`. PyBoy's
Gen 1 game wrapper already reads the party, bag, money, badges, and event flags, and its
constants module is the first source for those values. Every address is verified by an
integration test that loads a save state and checks a known value.

Screen text is read from the background tilemap (`pyboy.tilemap_background`) and decoded with
the wrapper's text table. That is how the state layer sees dialog text, prompt text, and menu
items without OCR.

## 6. State and decision points

`GameState` is a frozen dataclass built by `snapshot(emulator)` every loop iteration. It is the
only thing the brain and the dashboard ever see.

```
GameState
  mode: Mode                  OVERWORLD | BATTLE_MENU | BATTLE_WAIT | DIALOG | PROMPT | MENU | TRANSITION
  map: str                    "Pallet Town"
  tile: (x, y)                player tile, used by the executor only, never sent to Jev
  party: [Mon]                name, nickname, level, types, hp, max_hp, status, moves: [Move]
  enemy: Mon | None           present in battle; includes level and types
  battle: Battle | None       is_trainer, trainer_class
  badges: [str]
  money_bucket: str           "broke" | "some" | "comfortable" | "rich"
  bag: BagSummary             has_balls, has_potions, has_repel, item names
  text: str                   decoded on-screen text, empty when none
  menu_items: [str]           decoded items when a menu is open
  flags: EventFlags           the subset the goal table reads
Move: name, type, power, pp, max_pp
```

`GameState` carries raw numbers (HP, PP, money) because it is the harness's record of the truth;
the brain's builders convert them to bucket words at its own boundary (`brain/buckets.py`), and a
test asserts the JSON sent to Jev carries no HP, PP, or money numbers. Levels are sent as numbers.
`hp_bucket`, `pp_bucket`, and `power_bucket` (full | healthy | hurt | low | critical; out | low |
plenty; none | weak | medium | strong) are the brain's vocabulary, not `GameState` fields.

`Mode` is the decision-point detector. The contract:

- `BATTLE_MENU`: in battle and the FIGHT / PKMN / ITEM / RUN menu is accepting input.
- `BATTLE_WAIT`: in battle, animation or text playing. The loop advances with A presses.
- `PROMPT`: a YES / NO box is open. `text` holds the question above it.
- `MENU`: some other selectable list is open. `menu_items` holds the choices.
- `DIALOG`: text is printing or waiting for A, with no choice to make.
- `OVERWORLD`: player can move and no macro is running.
- `TRANSITION`: warp, fade, or unknown. The loop ticks and re-checks.

Detection combines RAM flags (`wIsInBattle`, the menu variables) with tilemap reads (the battle
menu box, the YES / NO box). The exact heuristics are settled in milestone 1 against save states
and pinned by integration tests, one save state per mode.

## 7. The loop

```
while running:
    state = snapshot(emu)
    publish(state); publish(frame) at most 15/s
    match state.mode:
        BATTLE_WAIT | DIALOG | TRANSITION:  emu.press("a") or tick; continue
        BATTLE_MENU:  decision = await brain.battle(state)
        PROMPT:       decision = await brain.prompt(state)
        MENU:         decision = await brain.menu(state)
        OVERWORLD:    if navigator.busy: navigator.step(); continue
                      decision = await brain.goal(state)
    publish(decision); log(decision)
    executor.apply(decision, emu)
```

One TypeSafe request per decision point. The loop never asks Jev "should we act now", because
the mode already answers that. Speculative questions are bundled into that one request and code
consumes only the ones that apply.

Frame publishing and the websocket server run on the same asyncio loop. Emulator ticks are
synchronous and short, so nothing is offloaded to threads in this version.

## 8. The brain

Every decision kind has a `questions(state) -> dict[str, Question]` builder and a
`decode(state, response) -> Decision` function. Builders are pure. Decoders apply the policy.

### 8.1 Battle

State sent (only what the questions need):

```json
{
  "our_pokemon": {"name": "CHARMANDER", "level": 8, "types": ["Fire"], "hp": "hurt",
                  "status": "none",
                  "moves": [{"name": "EMBER", "type": "Fire", "kind": "attack", "power": "medium", "pp": "plenty"},
                            {"name": "GROWL", "type": "Normal", "kind": "status", "power": "none", "pp": "plenty"}]},
  "enemy_pokemon": {"name": "PIDGEY", "level": 5, "types": ["Normal", "Flying"], "hp": "healthy"},
  "battle": {"kind": "wild"},
  "bench": [{"name": "PIDGEY", "level": 4, "hp": "full"}],
  "bag": {"poke_balls": true, "potions": true},
  "goal": "Reach Viridian City"
}
```

Questions, all in one request, each included only when it can apply:

| id | primitive | instructions (summary) | criteria |
| --- | --- | --- | --- |
| `move` | Choice | Which move should `our_pokemon` use this turn to win as quickly and safely as possible, given the types of both Pokémon? | usable moves, each with its type and kind as the rubric |
| `switch` | Noul | Should we switch out `our_pokemon` this turn instead of using a move? | yes when a bench member would clearly do better or ours is about to faint |
| `switch_to` | Choice | If we switch, which bench Pokémon should come in? | bench members with types and hp |
| `heal` | Noul | Should we use a Potion on `our_pokemon` this turn instead of attacking? | |
| `run` | Noul | Should we run from this wild battle rather than fight it? | wild only |
| `catch` | Noul | Should we throw a Poké Ball at `enemy_pokemon` this turn? | wild only, balls in bag; criteria mention that low enemy HP helps and that we want a party of at least three |

Policy, in `policy.py`, evaluated in this order with named thresholds. The first rule that fires
wins:

1. `heal` yes-probability above `HEAL_THRESHOLD` (0.7) and ours is `low` or `critical`: use Potion.
2. `catch` above `CATCH_THRESHOLD` (0.6): throw a ball.
3. `run` above `RUN_THRESHOLD` (0.7): run.
4. `switch` above `SWITCH_THRESHOLD` (0.7): switch to `switch_to`.
5. Otherwise use `move`.

Milestone 2 executes `move` and `run`; `heal`, `catch`, and `switch` are asked and recorded but
fall back to the move answer with `fallback` set until their macros land (milestone 4).

Code does not compute type effectiveness in this version. Judging Fire against Grass from the
type names is the kind of common sense the demo is meant to show, and the decision log makes it
measurable. If the measured move choice is poor, a later version can pass a computed
effectiveness hint as a named field.

### 8.2 Goal (overworld idle)

The goal table in `executor/goals.py` lists goals for the early game through the first badge,
each with an id, a one-sentence description Jev sees, the map and tile to reach, the event flags
that make it available, and the flags or conditions that complete it. Examples: leave the house,
talk to Oak, choose a starter, deliver the parcel, reach Viridian City, buy Poké Balls, catch a
Pokémon on Route 1, train until the lead is level 12, cross Viridian Forest, beat Brock. Plus two
always-available goals: heal at the nearest Pokémon Center, and train on the current route.

State sent: current map, party (names, levels, hp buckets), badges, money bucket, bag summary,
and the list of available goals with descriptions.

Questions: `goal` (Choice over available goal ids with descriptions as rubric) and `needs_heal`
(Noul: does the party need healing before doing anything else?). Policy: if `needs_heal` above
`HEAL_FIRST_THRESHOLD` (0.7) and a Pokémon Center is known, heal first; else pursue `goal`. A goal
stays active until complete, and Jev is only asked again when it completes or the navigator
gives up.

### 8.3 Prompts and menus

`PROMPT`: one Noul, "Should we answer YES to the question in `text` in order to make progress
on `goal`?", with the goal description in state. Yes above 0.5 presses A on YES, else NO.

`MENU`: one Choice over `menu_items` with the same goal context, plus a Noul "Should we close
this menu without choosing anything?". Close above 0.6 presses B, else select the choice.

Shops and the PC are menus like any other in this version. Buying Poké Balls is a goal whose
steps are menu decisions.

### 8.4 Decision record

```
Decision
  id, ts, kind (battle | goal | prompt | menu)
  state_summary: the JSON that was sent as state
  questions: {id: {primitive, instructions, options}}
  answers: {id: {choice | noul | score, probabilities, confidence, applied: bool}}
  action: what the executor will do, as a short string ("use EMBER", "throw Poké Ball")
  fallback: bool, true when policy could not act on the answers and code picked instead
  model, input_tokens, latency_ms
```

`applied` marks which speculative answers the policy consumed. The dashboard dims the rest.

## 9. The executor

`macros.py` turns an action into button presses using the current `GameState` for cursor
positions: FIGHT then the move's slot, PKMN then the bench slot, ITEM then the item's slot, RUN.
It reads the cursor's label from the screen buffer before every A press, so a wrong cursor
position is caught before it can select anything; the loop retries a failed macro once, then uses
the first move, then pauses until the screen changes.

`navigate.py` owns overworld movement. The collision window from PyBoy's Gen 1 wrapper covers the
visible screen, so navigation is waypoint-based: `maps.py` lists, per map, the tiles that matter
(doors, warps, exits, the Pokémon Center counter, the Mart counter) and the sequence of waypoints
between them. The navigator runs A* within the visible window toward the next waypoint, takes one
step, re-snapshots, and re-plans, so NPCs and ledges are handled by the map itself. Reaching a
warp tile ends the current leg. If the player tile has not changed after `STUCK_STEPS` (6)
attempts, the navigator re-plans with the blocked tile marked; after `STUCK_LEGS` (3) failed
legs it gives up, marks the goal blocked for this run, and hands control back to the loop so Jev
picks another goal.

A wild battle interrupting a walk suspends the navigator. When the battle ends, the loop returns
to `OVERWORLD`, sees the navigator is busy, and resumes.

## 10. The dashboard

`server.py` is a Starlette app on `127.0.0.1:8765` serving `static/` and a websocket at `/ws`.
The loop pushes four event types, each a JSON object with a `type` field:

- `frame`: JPEG bytes base64, at most 15 per second.
- `state`: the `GameState`, including `tile` for the dashboard's debugging readout (`tile` is
  never part of what the brain sends to Jev), on every loop iteration where it changed.
- `decision`: the full `Decision` record.
- `status`: `running | waiting_for_api | paused | stopped` with a message.

The page, plain ES modules with no build step:

- Left: the game screen scaled 4x with nearest-neighbor filtering. Under the screen: a party
  strip (nickname, level, HP bar in the bucket's colour).
- Right: the latest decision. The action taken, in words, as the panel's headline above the
  bars, so a viewer reads the outcome first. One horizontal bar per option for each Choice,
  winner highlighted, the probability as a label. Each Noul as a single yes/no split bar. A
  confidence badge on each Choice. Questions whose `applied` is false are dimmed and labelled
  "not used". Latency and token count small at the bottom. Below the panel: the current
  goal, and a scrolling log of the last 50 decisions with kind, action, and confidence.
- A `?layout=stream` query switches to a fixed 1920x1080 arrangement for OBS.

`jevplays replay runs/<dir>` reads `decisions.jsonl` and pushes the same events with a delay, so
the page can be developed and demonstrated without an API key or a running emulator.

## 11. Runs, logs, and resume

Each `jevplays run` creates `runs/<YYYYMMDD-HHMMSS>/` holding `run.json` (ROM hash, model id
from the first response, start time, CLI flags), `decisions.jsonl` (one Decision per line), and
`checkpoint-<n>.state` every `CHECKPOINT_EVERY` (25) decisions plus one at exit. `jevplays run
--resume runs/<dir>` loads the last checkpoint and appends to the same log.

## 12. Error handling

- The SDK retries with backoff and honors `retry-after`. On a request that still fails, the loop
  sets status `waiting_for_api`, shows it on the page, waits with capped backoff, and retries the
  same decision. It never presses buttons on a failed request.
- If the response is missing an answer the builder sent, the decision is marked `fallback` and
  code takes the safest legal action for that mode: the first usable move, NO on a prompt, B on
  a menu. Fallbacks are visible on the page.
- Confidence is displayed but not acted on in this version; a wrong move costs little. The
  thresholds in `policy.py` are the only tunables and are named so the plan can test them.
- Emulator or ROM errors are fatal and print the cause; a run can be resumed from its checkpoint.
- Every decision logs the versioned model id from the response, so behaviour changes across Jev
  releases are traceable.

## 13. Testing

Unit tests need no ROM and no API key. CI runs these.

- `state`: bucket functions, text decoding, `GameState` construction from a fake memory map.
- `brain`: each builder produces the expected question set for representative states, including
  what is omitted (no `run` in a trainer battle, no `catch` without balls). Decoders and policy are
  tested against recorded TypeSafe responses in `tests/fixtures/responses/`, one per scenario,
  captured once with the real API and checked in.
- `executor`: A* on synthetic collision grids, stuck detection, macro cursor math, goal
  availability and completion from synthetic flags.
- `dashboard`: event schemas serialize and deserialize; `replay` feeds a fixture log end to end
  through the websocket.

Integration tests under `tests/rom/` load save states from a local directory named by
`JEVPLAYS_STATES` and are skipped when `JEVPLAYS_ROM` is unset. One save state per `Mode` pins
the detector. One checks every address in `ram.py` against a known value. Save states are not
committed: they contain game memory.

An accuracy check for battles is a script, not a test: replay logged battle decisions and report
how often Jev's `move` matched the highest-effectiveness attack. It is the number to watch when
deciding whether to add the effectiveness hint.

## 14. Milestones

Each is a separate plan and pull request set.

1. **Harness.** Repo scaffold with the tooling above. Emulator wrapper, `ram.py`, `GameState`
   and `Mode`, the dashboard showing the screen and raw state, `jevplays state` and a `run` that
   walks through the intro and stops at the first `OVERWORLD`. No TypeSafe calls.
2. **Battles.** The battle builder, policy, macros, and the decision panel with bars, and the
   executor's window pathfinder (`executor/navigate.py`), delivered early because the save-state
   script needs to reach a battle; milestone 3 adds the waypoint graph on top of it. Demo: start
   from a save state on Route 1 and watch Jev fight; catching lands with the ITEM macros in
   milestone 4.
3. **Goals and navigation.** Goal table through Brock, waypoint maps for Pallet, Route 1,
   Viridian, Route 2, Viridian Forest, Pewter, the goal builder, prompts and menus, run logging
   and resume, replay.
4. **Long tail.** Shops, the PC, trainer battles with switching, the stream layout, the accuracy
   script, and whatever the first full run to Brock exposes.
