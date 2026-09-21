# jevplays

Read `README.md` for what this is and how to run it. The design is
`docs/superpowers/specs/2026-09-20-jevplays-design.md`; read it before changing how
Jev is asked anything.

## Build & test

- `mise run setup` once, then `mise run check` (lint + tests) before every push. The hk
  hooks run the same steps.
- Tests under `tests/rom/` need `JEVPLAYS_ROM` and the save states in `states/`
  (`mise run states` writes them). Without `JEVPLAYS_ROM` pointing at a file, `tests/rom/`'s
  test modules are not collected at all (so pyboy is never imported); with the ROM set but a
  save state missing, the individual test skips. CI has no ROM, so a ROM-dependent assertion
  never moves out of `tests/rom/`.
- `import pyboy` lives in `src/jevplays/emulator/pyboy.py` and nowhere else, so every unit
  test imports cleanly on a runner with no display.
- `import typesafe_sdk` lives in `src/jevplays/brain/client.py` (and the fixture script) and
  nowhere else; unit tests replay `tests/fixtures/responses/`, never the API.
- Never commit a ROM, a save state, a `.ram` file, or `mise.local.toml`.
- `runs/` is per-run output (logs and checkpoints), gitignored; tests write runs under `tmp_path`.

## Backlog

GitHub Issues is the only backlog. Nothing goes in a TODO file or a spec's follow-ons list
without an issue behind it.

- When Tyler says "log that", "note that for later", "add to the backlog", or describes a bug
  or idea that is not the current task, file an issue with `gh issue create` right then.
- Search first: `gh issue list --search "<words>" --state all`. If one exists, comment on it.
- Labels: one type (`bug` or `enhancement`), one area (`emulator`, `state`, `brain`,
  `executor`, `dashboard`, `tooling`), and for enhancements one stage:
  - `idea`: a sentence. May never happen.
  - `shaped`: what, why, rough size, and what it waits on are written down.
  - `spec`: a design doc exists under `docs/superpowers/specs/`; the issue links to it.
  - Add `blocked` when it cannot start yet and say why in the body.
- Picking one up: brainstorm from the issue text, and put `Closes #N` in the PR body.

## Changes

- Conventional commits: `feat(state):`, `fix(intro):`, `docs:`, `chore(tooling):`.
- Work lands through pull requests, never directly on `main`.
- Never edit or delete a test to make it pass.
- Jev judges, code executes. The model never receives coordinates, raw numbers, or
  screenshots; buckets, arithmetic, and policy stay in code.
- Type effectiveness lives in `state/types.py` for measurement only; never pass it to Jev.
- A change to a question's wording or a state field Jev sees re-records the fixtures
  (`Scripts/record-fixtures.py`) in the same PR.
- Story facts (goals, flags, scripted macros) live in `src/jevplays/executor/goals.py`.
- RAM facts (addresses, layouts) live in `src/jevplays/emulator/ram.py`.
- Never hand-write map waypoints; read the map (`src/jevplays/executor/world.py`).
