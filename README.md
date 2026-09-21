# jevplays

Jev, TypeSafe's System One model, plays Pokémon Red on a headless emulator while a local web
dashboard shows the game next to live probability bars for every decision. Code reads the game's
memory, asks Jev narrow typed questions, and presses the buttons; Jev supplies the judgment.

Design: `docs/superpowers/specs/2026-09-20-jevplays-design.md`. Status: milestone 2, battles.
The emulator boots, walks the intro or loads a save state, parses game state including the
party and an active battle, and streams to the dashboard. At the battle menu, the loop asks Jev,
publishes the decision, and the executor presses the buttons; `move` and `run` are executed,
`heal`, `catch`, and `switch` are asked and recorded but fall back to `move` until milestone 4.

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
mise run states       # write states/*.state (sixteen states) from the ROM so tests/rom/ run
uv run jevplays run   # boot, walk the intro, serve http://127.0.0.1:8765
uv run jevplays state states/overworld.state   # print the parsed GameState
```

The quickest way to watch a decision: `mise exec -- uv run jevplays run --state
states/battle_wild.state` (loads straight into a wild battle; needs `TYPESAFE_API_KEY`, which
`mise exec` loads from `mise.local.toml`). Add `--no-brain` to idle at decision points without
calling TypeSafe, or `--goal` to override the overworld goal.

Recording API fixtures: TypeSafe responses used by the unit tests are recorded, not called live
in CI. After changing a question's wording or the state fields Jev sees, re-record them with
`mise exec -- uv run Scripts/record-fixtures.py` and commit the updated files under
`tests/fixtures/responses/` in the same PR.

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
