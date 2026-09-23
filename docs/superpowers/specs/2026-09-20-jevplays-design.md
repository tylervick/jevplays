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

This is the one decision in the project a reader could reasonably argue with, so the README
states it up front under "What Jev sees" along with what it costs and what it buys. That section
is the summary; this one is the design, and it wins if the two ever disagree.

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
      explore.py      questions + decode for the overworld explore decision point
      prompt.py       questions + decode for yes/no prompts and menus
      policy.py       thresholds and priorities, named constants, nothing else
      decision.py     the Decision record (section 8)
    executor/
      __init__.py
      macros.py       button sequences for battle menus, prompts, menus
      navigate.py     A* over the collision window, waypoint following, warps
      maps.py         hand-written waypoint graph for the early game
      options.py      the options a map affords, generated fresh every decision
      goals.py        the three milestones: where each happens and when it is done
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
  flags: frozenset[str]       the subset of story event flags the milestones read
  sprites: [Sprite]           NPCs and other on-screen actors, for the executor only
  map_size: (w, h)            the current map's size in grid cells, for the executor only
Move: name, type, power, pp, max_pp
Sprite: slot, picture, x, y
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

Milestone 4b replaced the `OVERWORLD` branch's `brain.goal(state)` with the explore decision
point (8.2), and changed what runs before it. `_overworld_turn`, every call, in order: refresh
the active milestone (`executor.goals.active_milestone`) -- when the one just worked on is done,
advance to the next and publish `status_event("running", "milestone done: <id>")`; when none
remain, publish `status_event("finished", "Boulder Badge")`, a status the pseudocode above did
not have, and stop the run. Then, if the navigator has a plan running, step it, same as before.
Otherwise, with an option already in hand: drop it and mark it `tried` once its budget
(`OPTION_BUDGET_S`, 90 s) is spent, or run its `after` macro once its legs have arrived. Only
with no option in hand does the loop generate what the map affords
(`executor.options.generate`), ask Jev, and start what it picked. The budget governs the macro
phase only -- a walk to the option is bounded by the navigator's own stuck detector (9), not the
clock, so a long walk never gets an option marked `tried` before its macro has had a turn to
run.

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
  "enemy_pokemon": {"name": "PIDGEY", "level": 5, "types": ["Normal", "Flying"], "hp": "healthy", "status": "none"},
  "battle": {"kind": "wild"},
  "bench": [{"name": "PIDGEY", "level": 4, "types": ["Normal", "Flying"], "hp": "full", "label": "PIDGEY"}],
  "party": "two",
  "bag": {"poke_balls": true, "potions": true},
  "goal": "Deliver Oak's parcel and get the Pokédex. Build a party of three and keep them healthy."
}
```

Milestone 4a added `enemy_pokemon.status`, the `party` size word (`"one"` | `"two"` | `"three or
more"`, counting party members with hp above zero), and `bench[].label`: a bench member's
nickname, with a word suffix (`" (second)"`, `" (third)"`, ...) appended when an earlier bench
slot has the same nickname, so two same-species Pokémon never share a label. The label is the only
handle Jev gets on a bench member -- `brain/battle.py`'s `bench_slots(state)` is the sole place a
label's party index lives; `state_json` never carries one, matching the "no raw numbers besides
levels" rule.

`goal` is the active milestone's description (`executor/goals.py`, `active_milestone`), plus
the standing clause in the same module (`battle_goal`). It moves with the milestone rather than
being fixed for the run: `catch`'s criteria already speak of wanting a party of three, and
against a goal string that said nothing about a party they read as a distraction from it.
`--battle-goal` is the fallback before any milestone is active -- a battle fought before the loop
has ever stood in the overworld.

Questions, all in one request, each included only when it can apply:

| id | primitive | instructions (summary) | criteria |
| --- | --- | --- | --- |
| `move` | Choice | Which move should `our_pokemon` use this turn to win as quickly and safely as possible, given the types of both Pokémon? | usable moves, each with its type and kind as the rubric |
| `switch` | Noul | Should we switch out `our_pokemon` this turn instead of using a move? | yes when a bench member would clearly do better or ours is about to faint |
| `switch_to` | Choice | If we switch, which bench Pokémon should come in? | the bench labels, each with its types, level, and hp as the rubric |
| `heal` | Noul | Should we use a Potion on `our_pokemon` this turn instead of attacking? | |
| `run` | Noul | Should we run from this wild battle rather than fight it? | wild only |
| `catch` | Noul | Should we throw a Poké Ball at `enemy_pokemon` this turn? | wild only, balls in bag; criteria mention that we want a party of at least three, `enemy_pokemon` is worth having, and its hp is low enough for a ball to work -- asleep or paralyzed status helps |
| `faint` | Noul | Will `our_pokemon` faint before we get to choose again? | always asked, never acted on: the scored prediction (13) |

Policy, in `policy.py`, evaluated in this order with named thresholds. The first rule that fires
wins:

1. `heal` yes-probability above `HEAL_THRESHOLD` (0.7) and ours is `low` or `critical`: use Potion.
2. `catch` above `CATCH_THRESHOLD` (0.6): throw a ball.
3. `run` above `RUN_THRESHOLD` (0.7): run.
4. `switch` above `SWITCH_THRESHOLD` (0.7): switch to `switch_to`.
5. Otherwise use `move`.

As of milestone 4a all five actions execute; the macros are in 9.

`faint` is not part of the policy and no rule reads it. It is there to be checked: it is the one
question whose answer the game itself settles a turn later, which is what makes a calibration
number possible at all. Code resolves it (`calibration.py`) by reading the party at the next
decision point -- the battle menu is back, or the battle ended -- and appends the outcome to the
run's `outcomes.jsonl` (11). The observation is latched the moment the slot reads zero HP, not read at resolution time: a blackout heals the party before the loop is back at a decision point, so the evidence is gone by then (#36). The cost is one more judgment in a request that was being sent
anyway.

Code does not compute type effectiveness in this version. Judging Fire against Grass from the
type names is the kind of common sense the demo is meant to show, and the decision log makes it
measurable. If the measured move choice is poor, a later version can pass a computed
effectiveness hint as a named field.

### 8.2 Explore (overworld idle)

Milestone 4b retired the goal table and `brain/goal.py`: the goal decision point above became
the **explore** decision point below. What the loop can do at any moment is generated from the
map it is standing on rather than looked up in a hand-written table; the design is
`docs/superpowers/specs/2026-09-21-generated-options-design.md`, and what follows is the explore
decision point as built.

State sent: current map, `progress` (a short list of story flags in words, from
`TRACKED_FLAGS`), party (names, levels, hp buckets), money bucket, bag summary, the active
milestone's description, and `options` -- one text per generated option
(`executor/options.py`), each carrying a memory word in parentheses (`new`, `visited`, `talked
already`, `tried`) because Jev has no memory between calls. Levels are the only raw numbers in
this state; a route number inside a map name ("Route 2") is a proper name, not a quantity, and
is allowed the same way a level is.

Questions, one request:

| id | primitive | instructions | criteria |
| --- | --- | --- | --- |
| `explore` | Choice | Which of `options` should we do next to make progress in the game, given `progress` and the `milestone`? | the options' texts, keyed by option id, each ending in its memory word |
| `needs_heal` | Noul | Should the party heal before doing anything else? | true when the party is hurt enough that the next battle could be lost |

Policy (`policy.py`, `choose_explore`): `needs_heal` above `HEAL_FIRST_THRESHOLD` (0.7) with a
`heal` option on offer that this map has not already marked `tried` wins, before Jev's
`explore` choice is even consulted (a heal that already failed from here would otherwise fire
every turn while the lead is still hurt, and the run would loop); otherwise the
`explore` choice, so long as it names an option actually on the list; a choice naming anything
else, or no usable `explore` answer at all, falls back to `milestone` when that option is on
offer, else the first option -- code decided that, not Jev, so it is marked `fallback`. This is
the harness's only heal-first rule: code never overrides Jev's choice for any other reason. There
is no "stays active until complete": Jev is asked fresh every idle overworld turn, because it has
no memory between calls, and the memory word on each option is how it is told what this run has
already done.

### 8.3 Prompts and menus

`PROMPT`: one Noul, "Should we answer YES to the question in `text` in order to make progress
on `goal`?", with the goal description in state. Yes above `PROMPT_YES_THRESHOLD` (0.5) presses A
on YES, else NO.

`MENU`: one Choice over `menu_items` with the same goal context, plus a Noul "Should we close
this menu without choosing anything?". Close above `MENU_CLOSE_THRESHOLD` (0.6) presses B; else
the executor walks the cursor down to the chosen item and presses A -- unless that item is not
actually one of `menu_items` as sent (a hallucinated label, or one that scrolled away before the
response came back), in which case the menu decision falls back to closing it instead of pressing
A on whatever the cursor happens to be sitting on. Selecting the wrong thing in a shop or a PC
costs money or a Pokémon, so a menu never guesses.

The starter confirmation ("So! You want CHARMANDER?") is scripted YES rather than asked, for the
same reason a menu never guesses: Jev has just chosen which ball to take (a question of its own
since 2026-09-23, see `2026-09-23-starter-choice-design.md`), and re-asking it at the confirmation
box only gives it a way to answer NO and leave its own goal exactly where it started. The nickname box in the same macro is scripted NO, by the policy above.

The Pokémon Center nurse and the Mart clerk are not Jev-answered menus, even though their screens
look like ones. Both are mechanical -- a HEAL confirmation, a BUY quantity box -- so
`executor/talk.py` walks up to the sprite and presses A through its dialog, and `executor/shop.py`
layers a scripted counter on top for each one, pressing every button of the HEAL or BUY sequence
itself. Jev's only say is whether to go there at all -- the `heal` option, or the option for the clerk
standing behind the counter (8.2); once the legs get there, code runs the whole counter.

The BUY sequence takes the item's shelf label, so one counter serves both purchases: a clerk
option runs `shop.restock`, which tops the bag up to five Poké Balls and then five Potions with
the money left, balls first (#33). The Viridian shelf has no Potion -- read off the ROM, it
stocks Poké Ball, Antidote, Parlyz Heal and Burn Heal -- so Potions come from Pewter, the last
counter before Brock, the first fight where a Potion decides anything. A full bag is not a
failure (there was nothing to do); wanting something and buying nothing marks the option
`tried`. A shelf without the item is an ordinary outcome
either way: the scan runs out, the counter backs out to the overworld, the bag count does not
move, and the option is marked `tried` rather than a guessed inventory being written down.

### 8.4 Decision record

```
Decision
  id, ts, kind (battle | explore | prompt | menu)
  state_summary: the JSON that was sent as state
  questions: {id: {primitive, instructions, options}}
  answers: {id: {choice | noul | score, probabilities, confidence, applied: bool}}
  action: what the executor will do, as a short string ("use EMBER", "throw Poké Ball")
  fallback: bool, true when policy could not act on the answers and code picked instead
  model, input_tokens, latency_ms
```

`applied` marks which speculative answers the policy consumed. The dashboard dims the rest.

## 9. The executor

`executor/battle.py` turns an action into button presses using the current `GameState` for cursor
positions: FIGHT then the move's slot, PKMN then the bench slot, ITEM then the item's slot, RUN.
It reads the cursor's label from the screen buffer before every A press, so a wrong cursor
position is caught before it can select anything; the loop retries a failed macro once, then uses
the first move, then pauses until the screen changes.

Milestone 4a added the heal, catch, and switch macros to `executor/battle.py`. Heal opens ITEM,
walks the visible slots down to POTION, and picks the active Pokémon off the item's target
screen; a Potion that would have no effect -- the target already at full HP -- raises
`MacroError` rather than leaving the cursor on a screen nothing consumed. Catch opens the same
ITEM list and picks POKé BALL. Switch opens PKMN, walks the party list to the chosen slot, and
presses A into the SWITCH option that appears in the sub-menu below it; choosing a fainted
Pokémon there raises the same way heal does, instead of leaving a half-finished switch. All
three check the cursor before every A press, the same rule `select_command` and `select_move`
already followed -- but on the party list the check is positional, `CURSOR in
rows[PARTY_ROWS[slot]]`, because the cursor sits on the slot's HP row and the label there reads
the HP text ("22/ 22") and never a name. Every failure inside a macro goes through `_back_out`
first, which presses B until FIGHT is back on the battle menu row (at most four times), so a
failed macro always leaves the game on the battle menu, which is the one screen the loop knows
how to pick up from; the loop's own retry then needs no blind presses of its own. A bench label
like `PIDGEY (second)` is resolved to its party slot by `bench_slots` in `brain/battle.py` before
the executor ever runs -- the label is what Jev answered with, never a raw index.

Milestone 3a replaced the collision-window waypoint design this section originally called for with
navigation over the full current map, read from the running game rather than hand-written.
`executor/world.py` builds a walkability grid from `wOverworldMap`, the map's block ids, together
with the current tileset's block table and collision list, both read from ROM through
`Emulator.rom`. One grid cell is one player step -- a block's own 2x2-tile quadrant -- and the
quadrant's bottom-left tile decides whether the cell is walkable, the same rule PyBoy's own
collision window applies to the visible screen. A cell whose tile matches the map's grass tile is
marked as grass: still walkable, but where a wild battle can start, which is what the `grass`
option's `wander` macro uses to move around inside a patch until a battle interrupts it. Sprites
(NPCs, the rival, signposts) are read fresh from RAM every turn and treated as additional blocked
cells; warps and the map's edge connections are read from RAM the same way, never hand-recorded.

`maps.py` is the one hand-written piece, and it is deliberately small: a link table naming, per
map node (`"route_1"`, `"viridian_pokecenter"`, ...), the compass-direction edges and the
destination-map warps that lead out of it -- never a tile or a step. `route()` runs a
breadth-first search over that table to turn "get to the Pewter Gym from here" into an ordered
list of edges and warps.

`Navigator` (`navigate.py`) turns a list of legs -- `walk` (a target tile), `edge` (walk to the
map's edge in a direction), `warp` (walk to the nearest walkable warp toward a destination map),
or `face` (turn without moving) -- into movement, one tile per call to `step()`. Each call
re-reads the full-map grid, the current sprites, and the warp table before planning, so an NPC
that wanders into the way is routed around by the next call rather than a stale plan; a sprite
standing on the goal tile itself waits rather than failing the leg. `step()` runs A* on the grid,
treating sprite positions and any cell marked blocked as obstacles, and takes the first step of
the path. Each step that does not move the player marks the cell it aimed at as blocked, so the
next call routes around it; after `STUCK_STEPS` (6) such steps the leg is given up on and started
again from scratch, which clears those marks (whatever was in the way has usually moved by then),
and after `STUCK_LEGS` (3) failed legs the navigator gives up, clears its plan, and reports
`"stuck"`.

A plan is only good for the map it was built on. If the map id changes under a `walk` leg, or
an `edge` or `warp` leg comes out somewhere other than its `dest_map` -- a blackout teleports the
player to a Pokémon Center from anywhere -- `step()` returns `"lost"` without pressing anything.
The loop throws the plan away and the option with it: the option list was generated for a map the
run is not on any more, so the next turn generates a fresh one and asks Jev again from where the
player actually is. Nothing is charged against the option that was running. A leg that cannot
name the map it lands on -- a `WARP_LAST_MAP` warp, whose destination is only in `wLastMap` --
cannot be checked this way, and finishes on any change (#8).

A battle or a dialog interrupting a walk makes `step()` return `"interrupted"` with the plan
intact -- nothing is cleared. The loop hands control to the brain (or to whatever advances dialog
and battle), then calls `step()` again once `OVERWORLD` is back, so the same legs resume where
they left off.

Milestone 4b replaced the goal table this paragraph described with three milestones
(`executor/goals.py`: `get_starter`, `get_pokedex`, `beat_brock`, in order, the active one always
the first not yet done) as the only hand-written story left. Everything else Jev may do at a
given moment -- talk to someone, walk out an exit, go through a door, train in the grass, go
heal -- is an option `executor/options.py` generates fresh from the map (section 2 of the
generated-options design). An NPC standing behind a counter, like the Pokémon Center nurse or a
Mart clerk, is still offered: the option is talked to across the counter, from the near side,
rather than left out for having no adjacent walkable tile. An exit is offered only when the
navigator could actually walk to that edge from here (`world.reachable_edge`) -- Route 2's north
connection is behind Viridian Forest, so it is not offered from the route's south half, where the
walk would only fail.

There is also no `GOAL_RETRIES` counter any more: an option that comes back `"stuck"`, whose
macro (`after`, 8.3) fails or raises, or whose budget runs out (7) is marked `tried` for that map
and dropped, once, with no retry -- the memory word is the record, and Jev sees "tried" the next
time the option is offered and decides for itself whether to try again. `paused` is now
published only when a map affords no options at all to generate; `finished` (10), a separate
status, is what the run publishes once the last milestone is done.

## 10. The dashboard

`server.py` is a Starlette app on `127.0.0.1:8765` serving `static/` and a websocket at `/ws`.
`--host` moves it off loopback (`0.0.0.0` for watching from another device on the network);
the page is unauthenticated and read-only, and stays on loopback by default.
The loop pushes four event types, each a JSON object with a `type` field:

- `frame`: JPEG bytes base64, at most 15 per second, and close to 15 rather than the 1.4 the
  page used to get (#31). The emulator advances in batches -- a walking step is one batch -- so a
  frame published per batch was a frame per lurch. With `capture_every` set (the loop sets it for
  a paced run only), the emulator renders and keeps the last frame of every fourth frame as it
  ticks, and the loop plays that batch's frames out across the pacing sleep that follows. The
  page runs one batch behind and looks like the game instead of a slideshow.
- `state`: the `GameState`, including `tile` for the dashboard's debugging readout (`tile` is
  never part of what the brain sends to Jev), on every loop iteration where it changed.
- `decision`: the full `Decision` record.
- `status`: `running | waiting_for_api | paused | stopped | finished` with a message. Milestone
  4b added `finished`: the run reaching its last milestone (`beat_brock` done), as opposed to
  `stopped`, which is the process going away for any reason at all (#29 -- a finished run no
  longer ends the page on "paused"). The page gives `finished` its own pill colour rather than
  reusing `stopped`'s, so the two are told apart at a glance.

The page, plain ES modules with no build step:

- Left: the game screen scaled 4x with nearest-neighbor filtering. Under the screen: a party
  strip (nickname, level, HP bar in the bucket's colour).
- Right: the latest decision. The action taken, in words, as the panel's headline above the
  bars, so a viewer reads the outcome first. One horizontal bar per option for each Choice,
  winner highlighted, the probability as a label. Each Noul as a single yes/no split bar. A
  confidence badge on each Choice. Questions whose `applied` is false are dimmed and labelled
  "not used". Latency and token count small at the bottom. Below the panel: the current
  goal, and a scrolling log of the last 50 decisions with kind, action, and confidence. The
  `faint` prediction is never applied, so its badge reads "prediction" rather than "not used".
- A `?layout=stream` query switches to a fixed 1920x1080 arrangement for OBS.

Milestone 4b needed no new event type for exploration: the explore Choice renders as bars like
any other, the goal line under the panel shows the active milestone's description (read from the
decision's `state_summary.milestone`, not the option just picked, which is already in the log
line below), and a log entry for an explore decision already reads as its action text, "explore:
go north to Route 2", so the log never doubles the "explore" kind onto it the way it prefixes
other kinds.

`jevplays replay runs/<dir>` reads `decisions.jsonl` and pushes each logged `decision` event with
a delay between them, plus a `status` naming its progress before each one and a final `stopped`
when it finishes, so the page can be developed and demonstrated without an API key or a running
emulator. `frame` and `state` are never replayed, since the log never held them, so the screen
stays blank throughout.

A paced run keeps wall time by the emulator's own frame counter, not by what `advance` returns:
`_walk` reports `NAV_STEP_FRAMES` whatever the navigator actually spent, so pacing by the
returned counts slept out time the game never had and ran the game at roughly a third of real
speed. The returned counts remain the fallback for a fake emulator with no counter.

## 11. Runs, logs, and resume

Each `jevplays run` creates `runs/<YYYYMMDD-HHMMSS>/` by default (`--runs-dir` points it at a
different root; `--no-log` skips the directory, and its checkpoints, entirely for a throwaway
run) holding `run.json` (`rom_sha256`, `started_at`, the flags it was started with, `model` --
the id from the first response, `models` -- every distinct model id seen since, `resumed_at` --
a timestamp appended on each `--resume`, and `checkpoint_every`), `decisions.jsonl` (one Decision
per line), and `checkpoint-<n>.state` every `checkpoint_every` (25) decisions plus one at exit,
whether that exit is a normal stop, Ctrl-C, or a `kill` (SIGTERM) -- both signals take the same
shutdown path, so short of a `kill -9` the exit checkpoint is written. `jevplays run --resume
runs/<dir>` loads the newest checkpoint and appends to the same log.

Milestone 3b added the rule that makes that resume sound: `checkpoint-<n>.state` is the game just
after decision `n`, so decisions the log holds past `n` -- written between the last checkpoint and
the crash -- were rolled back with it. `--resume` moves them, in order, to
`decisions.orphaned.jsonl` before the loop starts, so replay never shows a decision the game
undid and the next checkpoint is numbered from what actually happened; `resumed_at` records the
checkpoint resumed from and how many lines moved. A torn last line in `decisions.jsonl` (a crash
mid-write) is skipped when the log is read and closed off by the next append, so one lost
decision never makes the log unreadable.

Milestone 4b added `memory.json`: the run's `Memory` (section 3 of the generated-options design --
visited maps, NPCs talked to, options `tried`), written after every change and read back by
`--resume`, so a resumed run reloads what it already knows instead of asking Jev to rediscover
it. Nothing about `decisions.jsonl` or the checkpoint rule above changed to make room for it; it
is its own small file, replaced wholesale on every write rather than appended to.

A run also holds `outcomes.jsonl`, one resolved `faint` prediction per line (`decision_id`,
`question`, `predicted`, `observed`, `ts`). It is a second stream rather than a field on the
decision line because the decision it scores was written turns earlier and `decisions.jsonl` is
append-only: the torn-line repair and the checkpoint numbering both depend on that. Nothing
prunes it on resume; `Scripts/accuracy.py` joins on `decision_id`, so an outcome whose decision
was rolled back into `decisions.orphaned.jsonl` drops out of the score on its own.

## 12. Error handling

- The SDK retries with backoff and honors `retry-after`. On a request that still fails, the loop
  sets status `waiting_for_api`, shows it on the page, waits with capped backoff, and retries the
  same decision. It never presses buttons on a failed request.
- A request that neither answers nor fails is bounded by `client.REQUEST_TIMEOUT_S` and becomes
  the same `BrainUnavailable`. Without it the await never returns and the run stops dead with
  nothing on the page to say so (#47): the SDK retries what fails, and an open connection that
  never answers has not failed.
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
- `executor`: A* on synthetic collision grids, stuck detection, macro cursor math, option
  generation and memory words on a synthetic map, milestone availability and completion from
  synthetic flags.
- `dashboard`: event schemas serialize and deserialize; `replay` feeds a fixture log end to end
  through the websocket.

Integration tests under `tests/rom/` load save states from a local directory named by
`JEVPLAYS_STATES` and are skipped when `JEVPLAYS_ROM` is unset. One save state per `Mode` pins
the detector. One checks every address in `ram.py` against a known value. Save states are not
committed: they contain game memory.

Milestone 4a added the accuracy check for battles as a script, not a test: `Scripts/accuracy.py
RUN_DIR [--verbose]` reads a run's `decisions.jsonl` and reports how often Jev's `move` answer
matched the best-typed attack -- the damaging move with the highest effectiveness against the
enemy's types, STAB (same-type attack bonus) included, computed by `state/types.py`'s
`best_moves`. It is the number to watch before adding a computed effectiveness hint to the battle
state Jev sees.

The same script reports calibration from `outcomes.jsonl`: the Brier score over every resolved
`faint` prediction, plus a reliability table by probability band. Accuracy says whether the
choice was right; calibration says whether the confidence meant anything, which is the claim a
System One model actually makes. Both numbers come from one run directory and one command, and
both are measured before a change to the questions, not reconstructed after it.

Milestone 4b added an exploration block to the same script, after the battle numbers: decisions
by kind (battle, explore, prompt, menu); explore decisions broken down by the kind of option
that was actually run (exit, door, npc, grass, milestone, heal); the share of explore decisions
that were the milestone option versus everything else Jev could have chosen instead; how many
distinct maps the run saw; and the total decision count. It is read off a run recorded, unpaced,
from `states/route1.state` to the Boulder Badge, and reported next to move accuracy so the two
questions -- did exploring get somewhere, did the battle judgment stay good while doing it -- are
answered from the same run. That run's decision count is also the milestone's measure against
the #17 baseline, the nine-goal table's 84 decisions to the badge: the numbers themselves are
reported in the pull request and in a comment on #17, not repeated here.

## 14. Milestones

Each is a separate plan and pull request set.

1. **Harness.** Repo scaffold with the tooling above. Emulator wrapper, `ram.py`, `GameState`
   and `Mode`, the dashboard showing the screen and raw state, `jevplays state` and a `run` that
   walks through the intro and stops at the first `OVERWORLD`. No TypeSafe calls.
2. **Battles.** The battle builder, policy, macros, and the decision panel with bars, and the
   executor's window pathfinder (`executor/navigate.py`), delivered early because the save-state
   script needs to reach a battle; milestone 3a builds full-map navigation on top of it. Demo:
   start from a save state on Route 1 and watch Jev fight; catching lands with the ITEM macros in
   milestone 4.
3a. **Goals and navigation.** Goal table through Brock, the full-map grid and the `maps.py` link
    table in place of hand-written waypoints (9), the goal builder, prompts and menus, the
    scripted Pokémon Center and Mart counters (8.3), and goal retries with the `paused` status
    when every goal is blocked (9).
3b. **Run logging, resume, and replay.** `runs/<dir>/run.json` and `decisions.jsonl` (11),
    checkpointing and `jevplays run --resume`, `jevplays replay`, and the dashboard's
    `?layout=stream` arrangement (10) -- all still as designed, none yet built.
4a. **Battle macros and the accuracy script.** `heal`, `catch`, and `switch` execute (shops and
    the PC counter are already scripted as of 3a); `Scripts/accuracy.py` measures how often Jev's
    move choice matches the best-typed attack.
4b. **The real run, as built.** Generated options (`executor/options.py`) replaced the goal
    table: exits, doors, reachable NPCs, the grass, and a heal trip, each with a memory word,
    hybridized with three hand-written milestones (`get_starter`, `get_pokedex`, `beat_brock`)
    that stay the spine guaranteeing progress; the explore decision point (8.2) and its policy;
    `memory.json` (11); the `finished` status (10); and the exploration block in
    `Scripts/accuracy.py` (13), run to the Boulder Badge and compared against the #17 baseline.
    The party-reorder macro and adding Route 22 to `maps.py`'s link table (9) were left for a
    later milestone -- exits are read from RAM regardless, so Jev can already walk there; only
    milestone routing needs the table.
