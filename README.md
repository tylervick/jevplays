# jevplays

Jev, TypeSafe's System One model, plays Pokémon Red on a headless emulator while a local web
dashboard shows the game next to live probability bars for every decision. Code reads the game's
memory, asks Jev narrow typed questions, and presses the buttons; Jev supplies the judgment.

![The dashboard mid-battle: the game on the left, and on the right the move Jev chose with the
probability it gave each option, alongside the run and faint questions](docs/media/jevplays-demo.webp)

*[`docs/media/jevplays-demo.mp4`](docs/media/jevplays-demo.mp4) is the whole run, start to the
Boulder Badge, in 24 seconds — 105 decisions, unpaced, recorded at 25fps. The loop above is eight
seconds of it. `Scripts/record-demo.py` regenerates both.*

Design: `docs/superpowers/specs/2026-09-20-jevplays-design.md`, amended by
`docs/superpowers/specs/2026-09-21-generated-options-design.md`. Status: milestone 4b, generated
options and the first full run to Brock. The emulator boots, walks the intro or loads a save
state, parses game state including the party, an active battle, story flags, and nearby sprites,
and streams it all to the dashboard. At the battle menu, the loop asks Jev, publishes the
decision, and the executor presses the buttons; all five actions execute, so battles can heal
with a Potion, catch a wild Pokémon, and switch in a bench member, not just attack or run. In the
overworld, code reads the map Jev is standing on and generates a list of things it could do next
-- an exit, a door, someone to talk to, the grass, a milestone, a heal trip -- and Jev picks one;
see "How Jev explores" below. Code walks there using a walkability grid read live from the map in
RAM rather than a hand-written route, and the Pokémon Center nurse and the Mart clerk are
scripted counters that Jev only decides whether to visit, never what to press once there. Prompts
and menus along the way are Jev's to answer. Every run writes its decisions, its memory of what
it has already done, and periodic checkpoints to `runs/`, `--resume` continues one, and `jevplays
replay` plays a logged run back through the dashboard for demos.

## What Jev sees

Jev is a System One model: it takes text and returns typed answers with calibrated probabilities.
It does not generate prose, plan, or remember anything between calls, and its documented weak
spots include arithmetic, counting, and spatial reasoning over raw coordinates. So the line this
project draws is **Jev judges, code executes**, and it is drawn strictly. Jev never sees a
screenshot, a coordinate pair, a tilemap, or a raw number. It sees names, types, words like "low"
for HP, and a short list of options, usually with a sentence saying what each one means.

Everything else follows from that. Code owns the route: `executor/world.py` reads a walkability
grid live out of the map in RAM and runs A* over it, and the one piece of routing written by hand
is the map-to-map graph in `executor/maps.py`, which names the next map and says nothing about
where to stand in it. Jev is never asked which way to step. Code owns the counters: the Pokémon
Center nurse and the Mart clerk are scripted button sequences, and Jev decides only whether going
there is the right goal, never what to press once it is inside. Code owns the arithmetic: HP
becomes "low", move power becomes a bucket, PP becomes "out" or not. What is left for Jev is the
judgment -- which move, whether to run, which option to try next, yes or no -- and every answer
arrives with a probability the dashboard draws as a bar.

The cost is that code has to be right about more things. A walkability grid, a macro per menu,
and the options generated in `executor/options.py` are all ours to write and keep correct, and
each one is a question Jev is never asked and therefore can never get right for us. What it buys
is that every failure has an address. A wrong turn is a bug in the pathfinder, not a model that
misread a map; a lost battle is a judgment, and `decisions.jsonl` says exactly what Jev was asked
and how sure it was. Hand the model the tilemap instead and it will often do fine, but the run
stops being evidence about the model and becomes evidence about the harness -- and this is meant
to be a demonstration of what a System One model is for.

## How Jev explores

At every idle overworld turn, code reads the map Jev is standing on -- the same RAM the
navigator already reads -- and builds a list of options: one per reachable exit, one per door
(grouped by destination, so both doors of a building are one option, "enter Viridian School"),
one per NPC it can reach (capped at the six nearest, described by sprite type and where they are
standing), the grass if there is any, a trip to heal if the lead needs it and a Pokémon Center is
reachable, and the active milestone. Jev picks one by id; the navigator walks its legs and a
scripted macro finishes it off (talking, healing, buying, wandering the grass until a battle
starts).

Jev has no memory between calls, so every option's text ends with a word saying whether this run
has done it before: `new`, `visited` (an exit or door whose destination has been entered this
run), `talked already` (an NPC whose macro only has something to say once -- the nurse and the
Mart clerk are never "talked already", since going back is the point), or `tried` (chosen before
from here and nothing came of it -- its budget ran out, its macro failed, or the navigator gave
up). This is a real list, recorded standing in Viridian City partway through a run:

```
milestone   work on the milestone: Challenge Brock at the Pewter Gym and earn the Boulder Badge (new)
heal        go heal at Viridian Pokémon Center (new)
exit_north  go north to Route 2 (new)
exit_south  go south to Route 1 (new)
exit_west   go west to Route 22 (new)
door_41     enter Viridian Pokémon Center (new)
door_42     enter Viridian Mart (new)
door_43     enter Viridian School (new)
door_44     enter Viridian Nickname House (new)
door_45     enter Viridian Gym (new)
npc_1       talk to a youngster to the north-west (new)
npc_2       talk to a gambler to the north-east (new)
npc_3       talk to a youngster to the north-east (new)
npc_4       talk to a girl to the north-west (new)
npc_5       talk to an old man to the north-west (new)
npc_7       talk to a gambler to the north-west (new)
```

`executor/goals.py` keeps three hand-written milestones as the spine that guarantees the run
keeps moving: `get_starter`, `get_pokedex` (deliver Oak's parcel and get the Pokédex), and
`beat_brock`. The active one -- the first not yet done -- is always offered as an option, never
forced; everything else Jev might do to get there is generated, not written down.

Which starter to take is Jev's too. At Oak's table it is asked once -- BULBASAUR, CHARMANDER, or
SQUIRTLE, each described by its type, with the Boulder Badge as the goal -- and code walks to that
ball. It is never told which type beats which; whether it knows what Brock fields is its own
judgment. A run without TypeSafe takes CHARMANDER, as every run did before.

## Quick start

Tooling is managed by [mise](https://mise.jdx.dev) (uv, hk, and the linters) and
[hk](https://hk.jdx.dev) (git hooks). Once, in a fresh checkout:

```bash
mise trust && mise install    # uv, hk, actionlint, gitleaks, zizmor, pinact
mise run setup                # uv sync --all-groups, then install the git hooks
```

Per-machine settings live in `mise.local.toml` (gitignored):

```toml
[env]
TYPESAFE_API_KEY = "..."
JEVPLAYS_ROM = "/absolute/path/to/pokemon-red.gb"   # your own dump; never committed
```

Then:

```bash
mise run check        # lint + tests, the same pair CI runs
mise run states       # write states/*.state (eighteen states) from the ROM so tests/rom/ run
uv run jevplays run   # boot, walk the intro, serve http://127.0.0.1:8765
uv run jevplays state states/overworld.state   # print the parsed GameState
```

The quickest way to watch a run: `mise exec -- uv run jevplays run --state states/route1.state`
(starts on Route 1 with a starter already in hand; needs `TYPESAFE_API_KEY`, which `mise exec`
loads from `mise.local.toml`). Add `--no-brain` to skip calling TypeSafe: battle decisions idle
(no move is chosen) since there is no policy to run without answers, while the overworld, prompts,
and menus still make progress using code's own fallbacks (the first untried option, milestone
first when it is offered, so the story still moves; YES; closing the menu). The objective sent
with a battle question is the active milestone plus a standing clause ("Build a party of three
and keep them healthy"), so what a fight is for changes as the run's progress does;
`--battle-goal` (aliased as the older `--goal`) is the fallback used before a milestone has been
picked, not an override.

Recording API fixtures: TypeSafe responses used by the unit tests are recorded, not called live
in CI. After changing a question's wording or the state fields Jev sees, re-record them with
`mise exec -- uv run Scripts/record-fixtures.py` and commit the updated files under
`tests/fixtures/responses/` in the same PR.

## A demo anyone can watch

    mise run demo                  # 0.0.0.0:8765, six times the game's own clock
    mise run demo -- --speed 1     # real time
    mise run demo -- --host 127.0.0.1

Each run starts from the intro, so the first decision a viewer sees is Jev choosing its starter
(`--state` starts every run from a save instead). One run ends at the Boulder Badge, so an
always-on demo needs something to start the next one.
`Scripts/demo-loop.py` is that: it starts a run, restarts it when it finishes or dies, and kills
and restarts one that has stopped making decisions (a run can hang in `BATTLE_WAIT` while the
process stays up and the log ends on an ordinary battle turn, so nothing inside the run notices).
The startup line prints the address to share; the page reconnects by itself, so a viewer sees the
next run begin without touching anything.

Speed is the thing to choose. Real time is the game's own 60fps and takes about two hours to
reach Brock -- right for watching a moment, long for a demo. Unpaced is not offered here: the
whole run would be over in half a minute and the demo would be a restart loop. `--speed`
multiplies the game's clock: the pacing sleep is computed against it, and frames are captured
`speed` times further apart in game time, so the page still gets 15 a second. The same frames are
emulated and the same decisions are made; they just arrive sooner.

It serves the local network by default.

### A public link

Whatever you put in front of the local port to share it, anyone who has the URL can watch, with
no login, and the ROM never leaves the machine running the demo.

Nobody can steer anything from the page: it is read-only, and nothing a viewer sends is acted on.
It does stream a commercial game to whoever has the link, and every decision a run makes is
TypeSafe quota. Three limits keep that bounded, all flags on `Scripts/demo-loop.py`:

- `--pause-after 60`: a run stops stepping the game once no dashboard has been open for this many
  seconds -- no frames, no decisions -- and carries on where it left off when a tab opens. The
  page says "unwatched" meanwhile. A crawler or a link preview fetches the page without running it,
  so it never opens the socket and never wakes the game, and a tab in the background lets go of its
  socket until it is shown again.
- `--daily-decisions 1500`: the day's budget (UTC), about five watched hours at 6x. It is counted
  from `decisions.jsonl` across every run, so a restart does not reset it, and each run is started
  with only what is left. A run that reaches it rests with the page up and says so; the next day's
  run starts after midnight UTC. The run enforces the number it was given, so a supervisor that
  dies does not leave a run spending past it.
- `--max-viewers 20`: tabs served at once; the next one is told the demo is full and retries. Each
  tab is its own frame stream, about 115 KiB/s (0.9 Mbit/s) at any speed, from this machine's
  upload.

`GET /health` answers `{"status": ..., "viewers": n}`; the supervisor polls it so that a run
paused or resting on purpose is not mistaken for a hung one. Run directories last written more than
two days ago are pruned before each start: logging stays on because the watchdog and the budget
both read it, and a run directory is save-state data that should not pile up.

## Runs

Every `jevplays run` (unless started with `--no-log`) creates `runs/<YYYYMMDD-HHMMSS>/` and keeps
writing to it for the life of the process. `runs/` is gitignored; nothing under it is ever
committed. Each run directory holds:

- `run.json`: `rom_sha256` (the ROM this run loaded), `started_at`, `flags` (the CLI flags it was
  started with), `model` (the id from the first decision's response), `models` (every distinct
  model id seen since, in case Jev is upgraded mid-run), `resumed_at` (an entry appended each time
  `--resume` continues this run, naming the checkpoint it resumed from and how many decisions were
  orphaned), and `checkpoint_every` (25).
- `decisions.jsonl`: one `Decision` per line, appended as the loop makes them.
- `checkpoint-<n>.state`: a PyBoy save state, written every 25 decisions and once more at exit,
  whether that exit is a normal stop, Ctrl-C, or a plain `kill` (SIGTERM) from a supervisor -- both
  signals run the same shutdown path, so short of a `kill -9` the exit checkpoint is written.
- `decisions.orphaned.jsonl`: only if a resume had to set decisions aside (see below).
- `outcomes.jsonl`: one line per faint prediction the game went on to answer -- the decision it
  came from, what Jev said, and what happened. Written as they resolve; absent if none did.
- `memory.json`: what the run already knows in the words Jev is shown -- maps visited, NPCs
  talked to, options tried and dropped (`executor/options.py`'s `Memory`). Rewritten after every
  change and reloaded on `--resume`. It is the *last* thing the run did, not the last thing it
  logged: after a resume rolls decisions back to the newest checkpoint, the memory can be a step
  or two ahead of `decisions.jsonl`, which only means Jev is told about something the log no
  longer shows.

`uv run Scripts/accuracy.py runs/<stamp> [--verbose]` reports two numbers over that run. From
`decisions.jsonl`, accuracy: how often Jev's `move` matched the best-typed attack (STAB
included), the number to watch before adding a computed effectiveness hint. From
`outcomes.jsonl`, calibration: a Brier score over every resolved faint prediction and a
reliability table by probability band, which says whether things Jev called 80% likely happened
about 80% of the time. Every battle bundle carries that prediction; no policy reads it, and code
settles it by reading the party at the next decision point. It also prints an exploration block
off `decisions.jsonl`: the count of decisions by kind, explore decisions broken down by the kind
of option that ran (exit, door, npc, grass, milestone, heal), the share of explore decisions that
were the milestone versus everything else, and how many maps the run saw -- that last from
`memory.json` when the run kept one, since it counts the maps walked through as well as the ones
stopped on.

### Did Jev choose well?

One run of 123 decisions, branched with K=8 seeds per alternative -- see `Scripts/branch-report.py`
and `docs/superpowers/specs/2026-09-23-counterfactual-branching-design.md` for how this measures a
decision and what each number means. Of 4848 branches, 4764 finished; 68 hit the frame cap and 16
stalled (all 16 on one alternative, across two decisions), and those 84 are left out of every mean
below rather than counted as at least the cap -- which does not make the means unbiased, only
honest about what was measured. The determinism check found a largest answer spread of 0.0900
across 20 repeated questions; the branch store caches Jev's calls, so every distinct question gets
one sampled answer, not a fresh one per branch.

Per decision kind, mean regret (seconds of game time against the best alternative, scored on
held-out seeds) and the share "as good as best" -- the held-out best, or no later than it on at
least half the scoring seeds, paired by seed, with a seed where both capped counting as no later:

- battle (89 decisions, 87 scored): regret 3.1s [-42.8, 46.7], as good as best 69%. The interval
  crosses zero, so this measurement cannot tell Jev's choice apart from the best move, from a
  random move (rule − Jev +11.1s [-23.0, 48.1]), or from the strongest move by power (+4.5s
  [-44.5, 52.7]).
- explore (34 decisions, all scored): regret -13.1s [-96.2, 67.0], as good as best 79%. Against a
  random option the interval again crosses zero (+39.0s [-5.5, 89.9]), so that comparison is also
  a wash; against the offline milestone-first pick, though, Jev's choice measurably cost less
  (rule − Jev +114.6s [11.5, 220.1], an interval that excludes zero).

#88 -- a navigator loop at Pewter's east exit -- was found by the first branching measurement and
fixed before this one.

`--runs-dir DIR` puts new run directories under `DIR` instead of `runs/`. `--no-log` skips the run
directory entirely -- no log, no checkpoints -- for a throwaway run you don't want to keep.

`jevplays run --resume runs/<stamp>` loads that run's newest checkpoint, `checkpoint-<n>.state`,
and appends to the same `decisions.jsonl` rather than starting a new directory; `--state` and
`--resume` are mutually exclusive, and `--resume` cannot be combined with `--no-log`. That
checkpoint is the game just after decision `n`, so any decision the log holds past `n` -- written
between the last checkpoint and the crash -- was rolled back with it; those lines move to
`decisions.orphaned.jsonl` so replay and the checkpoint numbering stay honest, and the run says how
many moved. A resumed run reloads its memory (`memory.json`) along with the game, so it does not
ask Jev to rediscover what this run already tried.

`jevplays replay runs/<stamp> --delay 1` reads `decisions.jsonl` back and pushes the same
`decision` events to the dashboard at `http://127.0.0.1:8765` with a pause between them (`--delay`,
seconds; `--limit`, stop after N decisions), plus a `status` update naming its progress. It holds
the first decision until a browser connects, for up to `--wait` seconds (default 30; `--wait 0`
starts at once), so nothing is played to an empty room. It needs no ROM and no
`TYPESAFE_API_KEY` -- the game screen stays blank, since frames were never logged, only
decisions.

`--host 0.0.0.0` serves the dashboard to the local network instead of loopback, for watching a
run from another device; the startup line then prints this machine's address rather than
`0.0.0.0`, which is not somewhere a browser can go. It is an unauthenticated read-only page, so
only do that on a network you trust.

For streaming or recording, add `http://127.0.0.1:8765/?layout=stream` as an OBS browser source at
1920x1080; it lays the game, the decision panel, and the log out to fill that fixed canvas instead
of the responsive page layout.

## Layout

- `src/jevplays/emulator/` wraps PyBoy and knows the RAM map and the Gen 1 text encoding.
- `src/jevplays/state/` turns bytes into a `GameState` with a detected `Mode`.
- `src/jevplays/brain/` turns state into typed questions for Jev and decodes the answers into a
  `Decision`, applying the policy.
- `src/jevplays/executor/` presses the buttons: battle macros, a dialog skipper, and a window
  pathfinder.
- `src/jevplays/dashboard/` is the Starlette app and the static page it serves.
- `src/jevplays/loop.py` and `cli.py` tie them together.
- `tests/` runs without a ROM; `tests/rom/` needs one and is not collected otherwise (an
  individual test there still skips if the ROM is set but a save state is missing).
