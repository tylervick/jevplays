# jevplays

Jev, TypeSafe's System One model, plays Pokémon Red on a headless emulator while a local web
dashboard shows the game next to live probability bars for every decision. Code reads the game's
memory, asks Jev narrow typed questions, and presses the buttons; Jev supplies the judgment.

Design: `docs/superpowers/specs/2026-09-20-jevplays-design.md`. Status: milestone 1, the
harness. The emulator boots, walks the intro, parses game state, and streams to the dashboard.
No TypeSafe calls yet.

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
mise run states       # write states/*.state from the ROM so tests/rom/ run
uv run jevplays run   # boot, walk the intro, serve http://127.0.0.1:8765
uv run jevplays state states/overworld.state   # print the parsed GameState
```

## Layout

- `src/jevplays/emulator/` wraps PyBoy and knows the RAM map and the Gen 1 text encoding.
- `src/jevplays/state/` turns bytes into a `GameState` with a detected `Mode`.
- `src/jevplays/dashboard/` is the Starlette app and the static page it serves.
- `src/jevplays/loop.py` and `cli.py` tie them together.
- `tests/` runs without a ROM; `tests/rom/` needs one and skips otherwise.
