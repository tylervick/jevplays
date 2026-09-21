# jevplays

Jev, TypeSafe's System One model, plays Pokémon Red on a headless emulator while a local web
dashboard shows the game next to live probability bars for every decision. Code reads the game's
memory, asks Jev narrow typed questions, and presses the buttons; Jev supplies the judgment.

Design: `docs/superpowers/specs/2026-09-20-jevplays-design.md`. Status: milestone 4a, battle
macros and the accuracy script. The emulator boots, walks the intro or loads a save state, parses
game state including the party, an active battle, story flags, and nearby sprites, and streams it
all to the dashboard. At the battle menu, the loop asks Jev, publishes the decision, and the
executor presses the buttons; all five actions execute now, so battles can heal with a Potion,
catch a wild Pokémon, and switch in a bench member, not just attack or run. In the overworld,
Jev picks a goal from the table in `executor/goals.py` (through Brock's badge), code walks
there using a walkability grid read live from the map in RAM rather than a hand-written route,
and the Pokémon Center nurse and the Mart clerk are scripted counters that Jev only decides
whether to visit, never what to press once there -- Poké Balls at the Viridian Mart, Potions at
the Pewter one. Prompts and menus along the way are Jev's to
answer. Every run writes its decisions and periodic checkpoints to `runs/`, `--resume`
continues one, and `jevplays replay` plays a logged run back through the dashboard for demos.

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
judgment -- which move, whether to run, which goal to pursue, yes or no -- and every answer
arrives with a probability the dashboard draws as a bar.

The cost is that code has to be right about more things. A walkability grid, a macro per menu,
and the goal table in `executor/goals.py` are all ours to write and keep correct, and each one is
a question Jev is never asked and therefore can never get right for us. What it buys is that
every failure has an address. A wrong turn is a bug in the pathfinder, not a model that misread a
map; a lost battle is a judgment, and `decisions.jsonl` says exactly what Jev was asked and how
sure it was. Hand the model the tilemap instead and it will often do fine, but the run stops
being evidence about the model and becomes evidence about the harness -- and this is meant to be
a demonstration of what a System One model is for.

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
and menus still make progress using code's own fallbacks (the first available goal, YES, closing
the menu). The objective sent with a battle question is the overworld goal Jev is pursuing plus a
standing clause ("Build a party of three and keep them healthy"), so what a fight is for changes
as the goal does; `--battle-goal` (aliased as the older `--goal`) is the fallback used before a
goal has been picked, not an override.

Recording API fixtures: TypeSafe responses used by the unit tests are recorded, not called live
in CI. After changing a question's wording or the state fields Jev sees, re-record them with
`mise exec -- uv run Scripts/record-fixtures.py` and commit the updated files under
`tests/fixtures/responses/` in the same PR.

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

`uv run Scripts/accuracy.py runs/<stamp> [--verbose]` reports two numbers over that run. From
`decisions.jsonl`, accuracy: how often Jev's `move` matched the best-typed attack (STAB
included), the number to watch before adding a computed effectiveness hint. From
`outcomes.jsonl`, calibration: a Brier score over every resolved faint prediction and a
reliability table by probability band, which says whether things Jev called 80% likely happened
about 80% of the time. Every battle bundle carries that prediction; no policy reads it, and code
settles it by reading the party at the next decision point.

`--runs-dir DIR` puts new run directories under `DIR` instead of `runs/`. `--no-log` skips the run
directory entirely -- no log, no checkpoints -- for a throwaway run you don't want to keep.

`jevplays run --resume runs/<stamp>` loads that run's newest checkpoint, `checkpoint-<n>.state`,
and appends to the same `decisions.jsonl` rather than starting a new directory; `--state` and
`--resume` are mutually exclusive, and `--resume` cannot be combined with `--no-log`. That
checkpoint is the game just after decision `n`, so any decision the log holds past `n` -- written
between the last checkpoint and the crash -- was rolled back with it; those lines move to
`decisions.orphaned.jsonl` so replay and the checkpoint numbering stay honest, and the run says how
many moved. A resumed run reloads the game but not the loop's memory, so goals it had given up on
are offered again and the goal choice starts fresh.

`jevplays replay runs/<stamp> --delay 1` reads `decisions.jsonl` back and pushes the same
`decision` events to the dashboard at `http://127.0.0.1:8765` with a pause between them (`--delay`,
seconds; `--limit`, stop after N decisions), plus a `status` update naming its progress. It holds
the first decision until a browser connects, for up to `--wait` seconds (default 30; `--wait 0`
starts at once), so nothing is played to an empty room. It needs no ROM and no
`TYPESAFE_API_KEY` -- the game screen stays blank, since frames were never logged, only
decisions.

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
