# jevplays

Read `README.md` for what this is and how to run it. The design is
`docs/superpowers/specs/2026-09-20-jevplays-design.md`; read it before changing how
Jev is asked anything.

## Build & test

- `mise run setup` once, then `mise run check` (lint + tests) before every push. The hk
  hooks run the same steps.
- Tests under `tests/rom/` need `JEVPLAYS_ROM` and the save states in `states/`
  (`mise run states` writes them). They skip, not fail, without either. CI has no ROM, so a
  ROM-dependent assertion never moves out of `tests/rom/`.
- `import pyboy` lives in `src/jevplays/emulator/pyboy.py` and nowhere else, so every unit
  test imports cleanly on a runner with no display.
- Never commit a ROM, a save state, a `.ram` file, or `mise.local.toml`.

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
