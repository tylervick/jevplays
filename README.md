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
no login, and the ROM never leaves the machine running the demo. The hosted demo runs this same
supervisor on Fly.io; see "Production" below.

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
  dies does not leave a run spending past it. To give today a little more without touching the
  supervisor, `mise run demo-topup -- 3000` adds 3,000 decisions to the current UTC day only: a
  resting run is replaced with the extra, and the next day starts at `--daily-decisions` again.
- `--max-viewers 20`: tabs served at once; the next one is told the demo is full and retries. Each
  tab is its own frame stream, about 115 KiB/s (0.9 Mbit/s) at any speed, from this machine's
  upload.

`GET /health` answers `{"status": ..., "viewers": n}`; the supervisor polls it so that a run
paused or resting on purpose is not mistaken for a hung one. Run directories last written more than
two days ago are pruned before each start: logging stays on because the watchdog and the budget
both read it, and a run directory is save-state data that should not pile up.

## Production

The public demo runs on one Fly.io Machine (`fly.toml`, `Dockerfile`), deployed by CI from `main`.
Design: `docs/superpowers/specs/2026-09-24-fly-deploy-design.md`. The ROM is never in the image or
the repository: it lives on the Machine's volume, uploaded once by hand.

One-time setup (flyctl is pinned in `mise.toml`: run these as `mise exec -- flyctl ...`, written
below by its short name `fly`):

```bash
fly apps create jevplays
fly volumes create jevplays_data --region sjc --size 1
fly secrets set TYPESAFE_API_KEY=... NTFY_URL=https://<ntfy server>/<topic> NTFY_TOKEN=...
fly deploy --detach               # the Machine starts and waits for its ROM
fly ssh sftp put /path/to/your/pokemon-red.gb /data/rom/pokemon-red.gb
```

(`--detach` because nothing answers the health check on 8765 until the ROM is there, so waiting
on it would fail the first deploy. `sftp put` does not create directories: first
`fly ssh console -C "mkdir -p /data/rom"`.)

Then in the GitHub repository settings: secrets `FLY_API_TOKEN` (`fly tokens create deploy`),
`NTFY_URL` and `NTFY_TOKEN`; variables `FLY_DEPLOY=true` and `DEMO_URL=https://jevplays.fly.dev`.

From then on every push to `main` that passes CI deploys. A deploy stops the Machine with SIGTERM;
the run writes its exit checkpoint and the next Machine resumes it, so viewers see the page
reconnect about a minute later on the same run. `fly logs` shows the supervisor's `[demo]` lines.

What ntfy says, and what it means:

- `demo started, new run` / `demo started, resuming run <stamp>`: a deploy or restart.
- `no ROM at ...; waiting for it`: the volume has no ROM; upload it as above.
- `run N made no decision for 300s; restarting it`: the #67 watchdog fired.
- `daily budget of 3000 decisions spent; resting until 00:00 UTC`, then
  `new UTC day; starting a run with today's budget`.
- `5 runs in a row died within 30s; exiting so the machine restarts`: runs cannot start; Fly
  restarts the Machine, and after ten tries stops it; with `auto_start_machines = true` Fly's
  proxy starts it again on the next request to the page. `fly logs` says why.
- `deploy success: <sha>` / `deploy failure: <sha>`: from CI.
- `demo is down: ...` / `demo is back up`: from the `uptime` workflow, every 10 minutes (GitHub
  runs it late at times). GitHub disables scheduled workflows in a public repository after 60 days
  without repository activity; if these go quiet, re-enable `uptime` from the Actions tab.

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

`jevplays branch` replays every alternative Jev didn't take from the same saved state, 8 seeds
each, and measures game time to the active milestone; `Scripts/branch-report.py` scores it
(`--by-choice` splits it by what Jev chose, and it reports the party size each branch ends with).
Five runs from `route1.state` to the Boulder Badge -- 868 decisions, 33,640 branches -- measured
after the navigator and map fixes (#88, #94, #100, #102, #116) and the changes that let Jev shop
and catch (#112, #113, #117, #118):

- **Overworld: Jev's choices beat simple rules.** Choosing the way Jev did saved 57.7s [19.5, 94.8]
  of game time against a random option and 142.3s [75.9, 205.9] against always heading straight
  for the milestone; against the best alternative in hindsight it is indistinguishable (20.8s
  [-31.6, 67.5]). It trained in the grass on 192 of 301 decisions, and that no longer costs
  measurable time (28.2s [-40.8, 96.3]): the grass now says when there is no ball to catch with.
- **Battles: indistinguishable from the rules.** Against the best alternative 3.3s [-26.9, 34.3];
  against a random move -7.6s [-30.8, 14.6] and the strongest move -20.0s [-47.6, 8.6], intervals
  that cross zero.
- **The party is where the choices differ.** Where Jev could have entered the Viridian Mart before
  the grass and did something else (23 decisions), the branches that entered it ended with a
  party of three or more 48% of the time (mean 3.2 Pokémon), against 1% after Jev's choice (mean
  1.07), for about five minutes more to the badge (median 1,637s against 1,322s). Jev passed that
  up every time; across 16 recorded runs it shopped there once, and that run caught four Pokémon
  and fought Brock with four (#110).

Caveats: the intervals treat decisions as independent, while decisions in one run share a
trajectory, so the true uncertainty is somewhat wider. 6.5% of branches hit the frame cap and are
left out of the time means rather than counted as at least the cap; capped branches ended with two
or more Pokémon far more often (26%) than finished ones (7%), so the time means lean against the
branches that caught. Jev is not deterministic -- the same question's probabilities vary by up to
0.16 across repeats -- so each distinct question was answered once and cached. Earlier series:
#104 and #111 (before the shop and catch changes). Design:
`docs/superpowers/specs/2026-09-23-counterfactual-branching-design.md`.

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
