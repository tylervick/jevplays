# Milestone 1: Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A headless Pokémon Red emulator wrapped in Python that walks through the intro on its own, parses the game's RAM and screen buffer into a typed `GameState` with a detected decision-point `Mode`, and streams the screen plus that state to a local web dashboard. No TypeSafe calls yet.

**Architecture:** One Python package `jevplays` in a `src/` layout. `emulator/` wraps PyBoy and knows the RAM addresses and the Gen 1 text encoding. `state/` is pure: bytes in, `GameState` out. `dashboard/` is a Starlette app with a websocket broadcaster. `loop.py` ties them together on one asyncio loop and `cli.py` exposes `jevplays run` and `jevplays state`. Unit tests never touch the ROM; ROM tests under `tests/rom/` skip themselves without one.

**Tech Stack:** Python 3.12, uv, PyBoy 2.7, numpy, Pillow, Starlette, uvicorn, websockets, pytest, ruff. Tooling copied from graphghan: mise, hk, Renovate, SHA-pinned GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-20-jevplays-design.md` (sections 4, 5, 6, 7, 10, 13, 14). This plan implements milestone 1 of section 14. Section 6's full `GameState` (party members, moves, bag summary, event flags) lands in milestone 2; here it carries what the harness can show today: mode, map, tile, player name, party count, badges, money, bag count, on-screen text, menu items.

## Global Constraints

- Python `>=3.12`; `.python-version` is `3.12`. Dependencies: `pyboy>=2.7,<3`, `numpy>=2.3`, `pillow>=11`, `starlette>=0.47`, `uvicorn>=0.35`, `websockets>=15`. Dev: `pytest>=8`, `ruff>=0.6`, `httpx>=0.28`.
- ruff line length 110, `select = ["E", "F", "I", "B"]`, `ignore = ["E501"]`, target py312.
- `import pyboy` happens only inside `src/jevplays/emulator/pyboy.py`. Every other module, and every unit test, must import without PyBoy loading SDL, so CI (no display, no ROM) stays green.
- Nothing game-derived is committed: no ROM, no `.state`, no `.ram`, no `runs/`. `mise.local.toml` is gitignored and holds `TYPESAFE_API_KEY` and `JEVPLAYS_ROM`.
- The ROM lives at `/Users/builder/orca/projects/jevplays/roms/pokemon-red.gb` on this machine and `JEVPLAYS_ROM` already points there. Save states go in `states/` (gitignored), the default for `JEVPLAYS_STATES`.
- ROM tests live only under `tests/rom/` and use the `rom` and `state_path` fixtures from `tests/rom/conftest.py`, which skip when the ROM or state is missing.
- Commits: conventional commits (`feat(emulator): ...`, `test(state): ...`, `chore(tooling): ...`). Work happens on the branch `tylervick/milestone-1-harness`, branched from `tylervick/jevplays-design`. Never commit directly to `main`.
- Verified facts this plan relies on (measured 2026-09-20 with PyBoy 2.7.0 and this ROM): the cartridge title is `POKEMON RED`; the released PyBoy Gen 1 wrapper has no party/inventory API (that is unreleased master code), so all RAM parsing is ours; the game's screen text buffer `wTileMap` is at `0xC3A0`, 20x18 bytes; new game starts on map 38 at x=3, y=6 with 3000 money and player name `RED`, rival `BLUE`; the "press A" arrow is tile `0xEE` at row 16, column 18 and it blinks; the menu cursor is tile `0xED`; `wFontLoaded` `0xCFC4` is 1 while the START menu is open; the tile `'s` is one byte (`0xBD`) that decodes to two characters, which is why rows are lists of cells.

---

## File structure

```
jevplays/
  .github/ISSUE_TEMPLATE/{bug.yml,idea.yml,config.yml}
  .github/workflows/ci.yml
  .gitignore  .python-version  CLAUDE.md  LICENSE  README.md
  hk.pkl  mise.toml  orca.yaml  pyproject.toml  renovate.json  uv.lock
  Scripts/update-blink-pin.sh          copied from graphghan, unchanged
  Scripts/make-states.py               writes states/*.state from the ROM (Task 5)
  src/jevplays/__init__.py             __version__
  src/jevplays/emulator/__init__.py
  src/jevplays/emulator/text.py        CHARMAP, decode_cells, decode_name, encode, row_text, has_text
  src/jevplays/emulator/ram.py         pokered-named addresses, Memory protocol, bcd_to_int, read_* helpers
  src/jevplays/emulator/pyboy.py       Emulator: the only module that imports pyboy
  src/jevplays/emulator/intro.py       walk_intro: title screen to the first overworld step
  src/jevplays/state/__init__.py
  src/jevplays/state/modes.py          Mode enum and detect()
  src/jevplays/state/names.py          map_name()
  src/jevplays/state/snapshot.py       GameState and snapshot()
  src/jevplays/dashboard/__init__.py
  src/jevplays/dashboard/events.py     frame_event, state_event, status_event, encode
  src/jevplays/dashboard/server.py     Broadcaster, create_app, serve
  src/jevplays/dashboard/static/{index.html,app.js,styles.css}
  src/jevplays/loop.py                 Loop: snapshot, publish, advance
  src/jevplays/cli.py                  jevplays run | state
  tests/__init__.py  tests/support.py  tests/test_*.py
  tests/rom/__init__.py  tests/rom/conftest.py  tests/rom/test_*.py
```

---

### Task 1: Repository scaffold and tooling

**Files:**
- Create: `pyproject.toml`, `.python-version`, `.gitignore`, `mise.toml`, `hk.pkl`, `orca.yaml`, `renovate.json`, `.github/workflows/ci.yml`, `.github/ISSUE_TEMPLATE/idea.yml`, `.github/ISSUE_TEMPLATE/bug.yml`, `.github/ISSUE_TEMPLATE/config.yml`, `LICENSE`, `CLAUDE.md`, `README.md`, `src/jevplays/__init__.py`, `tests/__init__.py`, `tests/test_package.py`
- Copy: `Scripts/update-blink-pin.sh` from `/Users/builder/orca/workspaces/graphghan/Xcode-28/Scripts/update-blink-pin.sh`

**Interfaces:**
- Produces: `jevplays.__version__ == "0.1.0"`; `mise run setup|lint|fix|test|check|states`; the `uv run pytest -q` and `hk check --all` commands every later task uses.

- [ ] **Step 1: Create the branch**

```bash
cd /Users/builder/orca/projects/jevplays
git checkout tylervick/jevplays-design
git checkout -b tylervick/milestone-1-harness
```

- [ ] **Step 2: Write `pyproject.toml`, `.python-version`, `.gitignore`**

`pyproject.toml`:

```toml
[project]
name = "jevplays"
version = "0.1.0"
description = "Jev, TypeSafe's System One model, plays Pokémon Red with a live probability dashboard"
readme = "README.md"
requires-python = ">=3.12"
license = {text = "MIT"}
dependencies = [
    "pyboy>=2.7,<3",
    "numpy>=2.3",
    "pillow>=11",
    "starlette>=0.47",
    "uvicorn>=0.35",
    "websockets>=15",
]

[project.scripts]
jevplays = "jevplays.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/jevplays"]

[dependency-groups]
dev = [
    "httpx>=0.28",
    "pytest>=8",
    "ruff>=0.6",
]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 110
target-version = "py312"
extend-exclude = ["docs"]

[tool.ruff.lint]
select = ["E", "F", "I", "B"]
ignore = ["E501"]
```

`.python-version`:

```
3.12
```

`.gitignore`:

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
dist/

# Per-machine settings: the TypeSafe key and the ROM path (see README.md).
mise.local.toml
.mise.local.toml

# Game data never enters the repository. The ROM is the player's own dump; save
# states and PyBoy battery files are copies of its memory; runs/ holds per-run
# logs and checkpoints.
roms/
states/
runs/
*.gb
*.gbc
*.state
*.ram

# brainstorming visual companion sessions
.superpowers/
.worktrees/
.agents/
```

- [ ] **Step 3: Write `mise.toml`**

```toml
# Dev tooling for jevplays.
#
# mise owns the *tools*; uv owns Python and the package environment. Nothing
# here pins Python on purpose -- `.python-version` + `uv.lock` already do.
#
# In a fresh checkout:
#   mise trust && mise install && mise run setup
#
# (An Orca worktree does this for you -- see orca.yaml.)
#
# Per-machine settings go in mise.local.toml, which is gitignored:
#   [env]
#   TYPESAFE_API_KEY = "..."
#   JEVPLAYS_ROM = "/absolute/path/to/pokemon-red.gb"

# Every tool is pinned exactly rather than "latest", for two reasons: it is what
# makes `hk check --all` mean the same thing on this laptop and in CI, and
# Renovate's mise manager can only propose bumps against a concrete version.
# renovate.json groups them into one PR.
[tools]
uv = "0.11.29"
# Must match the `amends`/`import` URLs at the top of hk.pkl. hk evaluates that
# file with its own embedded pkl, and a config written against one release is not
# guaranteed to evaluate under another. renovate.json has a custom manager that
# bumps hk.pkl in the same PR so the two cannot drift apart.
hk = "1.55.0"
# Invoked by hk steps rather than directly.
actionlint = "1.7.12"
gitleaks = "8.30.1"
zizmor = "1.29.0"
# Only needed when a workflow gains or bumps an action; see `mise run pin-actions`.
pinact = "4.1.1"

# Blink (https://blink.review) reviews each Claude Code turn's diff and hands the
# findings back to the agent. Its own installer drops an unpinned "latest" in
# ~/.local/bin, invisible to everyone else here. This pins it through mise's
# `http` backend instead. The CDN URL is content-addressed by the binary's own
# SHA-256, so the URL and the checksum are one fact and cannot drift apart.
#
# Renovate cannot see this (nothing to query), so bumps are manual: run
# `Scripts/update-blink-pin.sh`; do not hand-edit the values below. CI never runs
# Blink, so both workflows set MISE_DISABLE_TOOLS=http:blink and skip the download.
# blink-pin:begin -- managed by Scripts/update-blink-pin.sh, do not hand-edit
[tools."http:blink"]
version = "0.1.2"
platforms.macos-arm64.url = "https://blink.review/downloads/cli/blink-darwin-arm64-2656629b96cb79471e4759c82b6b22e31167ad5239135edca5e6ff603d5cfc75.gz"
platforms.macos-arm64.checksum = "sha256:2656629b96cb79471e4759c82b6b22e31167ad5239135edca5e6ff603d5cfc75"
platforms.macos-x64.url = "https://blink.review/downloads/cli/blink-darwin-x64-b0d58f861a3dafed5f7d6c34acd711e19014f2ec2fba4da0434e5dff0e7efa2f.gz"
platforms.macos-x64.checksum = "sha256:b0d58f861a3dafed5f7d6c34acd711e19014f2ec2fba4da0434e5dff0e7efa2f"
platforms.linux-x64.url = "https://blink.review/downloads/cli/blink-linux-x64-8636962e073a50dddfbeb3498768c2ec473562c749c3f615ff516930f6ae1824.gz"
platforms.linux-x64.checksum = "sha256:8636962e073a50dddfbeb3498768c2ec473562c749c3f615ff516930f6ae1824"
platforms.linux-arm64.url = "https://blink.review/downloads/cli/blink-linux-arm64-5121fdbac9caa4110450a814a8e90e10516f354668721eaf0b3701dfaf0a880c.gz"
platforms.linux-arm64.checksum = "sha256:5121fdbac9caa4110450a814a8e90e10516f354668721eaf0b3701dfaf0a880c"
# blink-pin:end

[tasks.setup]
description = "Create .venv from uv.lock and install the git hooks"
run = """
uv sync --all-groups
hk install
"""

[tasks.lint]
description = "Everything hk checks: ruff, formatting, file hygiene, workflow + secret scans"
run = "hk check --all"

[tasks.fix]
description = "Apply every fix hk can make"
run = "hk fix --all"

[tasks.test]
description = "The pytest suite; tests/rom/ skip without JEVPLAYS_ROM and states/"
run = "uv run pytest -q"

[tasks.check]
description = "Lint and test -- the same pair CI runs"
depends = ["lint", "test"]

[tasks.states]
description = "Regenerate the save states tests/rom/ load (needs JEVPLAYS_ROM; writes states/)"
run = "uv run Scripts/make-states.py"

[tasks.pin-actions]
description = "Re-pin .github/workflows actions to commit SHAs (run after adding or bumping one)"
# zizmor enforces that actions are hash-pinned but cannot pin them itself; this
# is the fix side of that rule. It hits the GitHub API, which is why it is a
# task you run deliberately rather than an hk step on every commit.
run = "pinact run --verify .github/workflows/*.yml"

[tasks.blink-setup]
description = "Sign in to Blink and install its Claude Code review hooks (once per machine)"
# Per-developer, not per-checkout: `blink setup` writes to the USER-level
# ~/.claude/settings.json, which is not something this repository can carry.
# What the repository DOES carry is the pinned CLI above, so everyone who opts in
# runs the same build. Undo with `blink setup claude-code --remove`.
run = '''
if blink auth status >/dev/null 2>&1; then
  echo "already signed in to Blink"
else
  blink auth login
fi
blink setup claude-code

# `blink setup` writes a BARE `blink review --hook claude-code` into that
# user-level settings file. A mise-managed blink answers that bare name only
# through the shims directory, so the hook resolves only if the shims directory
# is on the PATH Claude Code inherited. `mise doctor --json` has already
# resolved where that directory is and whether it is on PATH; ask it rather
# than rebuilding the path by hand. Its exit status is ignored on purpose: doctor
# exits 1 on ANY problem it finds while still printing complete JSON.
probe="$(mise doctor --json 2>/dev/null | uv run --no-project python -c '
import json, sys
doctor = json.load(sys.stdin)
print(doctor["dirs"]["shims"])
print("yes" if doctor["shims_on_path"] else "no")
' 2>/dev/null || true)"
shims="$(printf '%s\n' "$probe" | sed -n 1p)"

case "$(printf '%s\n' "$probe" | sed -n 2p)" in
  yes)
    echo "ok - $shims is on PATH, so the hook will resolve blink"
    ;;
  no)
    echo "ERROR: $shims is not on your PATH." >&2
    echo "The hook just installed runs a bare 'blink', so it would fail with" >&2
    echo "'command not found' at the end of every Claude Code turn." >&2
    echo "Add this to your shell profile, then open a new terminal:" >&2
    echo "  export PATH=\"$shims:\$PATH\"" >&2
    exit 1
    ;;
  *)
    echo "ERROR: could not read shims_on_path out of 'mise doctor --json'." >&2
    echo "Check by hand that mise's shims directory is on your PATH -- the hook" >&2
    echo "just installed runs a bare 'blink' and resolves it only through there." >&2
    exit 1
    ;;
esac
'''
```

- [ ] **Step 4: Write `hk.pkl`**

```pkl
amends "package://github.com/jdx/hk/releases/download/v1.55.0/hk@1.55.0#/Config.pkl"
import "package://github.com/jdx/hk/releases/download/v1.55.0/hk@1.55.0#/Builtins.pkl"

// Python tooling goes through `uv run` rather than hk's Builtins.ruff so that the
// hooks, CI and a bare `uv run ruff` all use the one ruff pinned by pyproject.toml's
// dev dependency-group. A mise-managed ruff would be a second pin, free to drift.
local ruff: Step = new Step {
  glob = "**/*.py"
  check = "uv run ruff check {{files}}"
  fix = "uv run ruff check --fix {{files}}"
}

local ruffFormat: Step = new Step {
  glob = "**/*.py"
  check = "uv run ruff format --check {{files}}"
  fix = "uv run ruff format {{files}}"
  // The linter rewrites code (import sorting, `B` autofixes); the formatter
  // rewrites layout. Ordering them keeps the two from racing on one file.
  depends = "ruff"
}

local gitleaks: Step = new Step {
  // Deliberately not Builtins.gitleaks, which runs `gitleaks dir ... {{files}}`:
  // `gitleaks dir` accepts one positional path and, handed more than one, silently
  // scans the working directory instead. Scanning git objects is both what a
  // secret check means and structurally out of reach of untracked files such as
  // mise.local.toml, which holds the TypeSafe key.
  check = "gitleaks git --redact --verbose --no-banner"
}

local pytest: Step = new Step {
  // No glob: tests/rom/ loads save states, so a change to a fixture or a state
  // can break the suite as easily as a change to a .py file.
  exclusive = true
  check = "uv run pytest -q"
}

// Fast enough to sit in front of every commit -- all of these are either
// incremental over the staged files or pure local I/O.
local fast = new Mapping<String, Step> {
  ["ruff"] = ruff
  ["ruff-format"] = ruffFormat
  ["trailing-whitespace"] = Builtins.trailing_whitespace
  ["newlines"] = Builtins.newlines
  ["merge-conflict"] = Builtins.check_merge_conflict
  ["private-key"] = Builtins.detect_private_key
  ["large-files"] = Builtins.check_added_large_files
}

// What `hk check --all` means, and therefore what CI enforces. The three added
// here scan the workflow, or the repository's whole history, rather than one
// edited file, so they are worth a couple of seconds on push and in CI but not on
// every commit.
local lint = (fast) {
  ["actionlint"] = Builtins.actionlint
  ["zizmor"] = Builtins.zizmor
  ["gitleaks"] = gitleaks
}

hooks {
  ["pre-commit"] {
    fix = true
    stash = "git"
    steps = fast
  }
  ["pre-push"] {
    // Everything CI will run, run before the push rather than after it.
    steps = (lint) {
      ["pytest"] = pytest
    }
  }
  // `hk check --all` / `mise run lint`. pytest is deliberately absent: CI runs it
  // as its own step so a test failure reads separately from a lint failure.
  ["check"] {
    steps = lint
  }
  ["fix"] {
    fix = true
    steps = lint
  }
}
```

- [ ] **Step 5: Write `orca.yaml`, `renovate.json`, `.github/workflows/ci.yml`**

`orca.yaml`:

```yaml
# Orca (onorca.dev) worktree hooks. `scripts.setup` runs in the freshly created
# worktree under non-interactive bash; ORCA_ROOT_PATH points at the main checkout.
#
# THIS FILE MUST STAY TRACKED IN GIT. `git worktree add` only materializes tracked
# files, so an untracked orca.yaml is simply absent from every new worktree and the
# hook never fires once.
#
# What a fresh jevplays worktree is missing: `.venv/` (gitignored, rebuilt from
# uv.lock), `mise.local.toml` (the TypeSafe key and ROM path, per machine), and
# `roms/` + `states/` (game data, gitignored). The last three are copied from the
# main checkout so tests/rom/ run here too.
scripts:
  setup: |
    set -euo pipefail

    # Orca runs this under bash without sourcing the shell rc that puts mise on
    # PATH, so point at the binary's real home first.
    export PATH="/opt/homebrew/bin:$HOME/.local/bin:$PATH"

    if [ -f "$ORCA_ROOT_PATH/mise.local.toml" ]; then
      cp "$ORCA_ROOT_PATH/mise.local.toml" mise.local.toml
    fi
    for d in roms states; do
      if [ -d "$ORCA_ROOT_PATH/$d" ]; then
        mkdir -p "$d"
        cp -R "$ORCA_ROOT_PATH/$d/." "$d/"
      fi
    done

    # `mise trust` covers mise.local.toml as well, so it runs after the copy.
    mise trust && mise install

    # Delegate to mise.toml rather than repeating the steps: `mise run` resolves
    # uv and hk through mise's own environment, and "what setup means" stays
    # defined in one file. Deliberately NOT seeded from $ORCA_ROOT_PATH/.venv --
    # a virtualenv records absolute paths, so a copied one still points at the
    # main checkout. uv rebuilds it from uv.lock in a second or two.
    mise run setup
```

`renovate.json`:

```json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "description": [
    "Three managers cover everything pinned in this repo:",
    "  github-actions -- the SHA-pinned action refs in .github/workflows/ci.yml",
    "  mise           -- uv, hk, actionlint, gitleaks, zizmor and pinact in mise.toml",
    "  pep621         -- the runtime and dev dependencies in pyproject.toml, with",
    "                    uv.lock refreshed alongside",
    "",
    "Blink's CLI is the one pin no manager covers: it ships from the vendor's own",
    "CDN with no repository, tag or registry entry, so there is nothing to query.",
    "`Scripts/update-blink-pin.sh` is its bump path; the rule below keeps Renovate",
    "from guessing at it should its mise manager ever learn the `http` backend.",
    "",
    "config:best-practices keeps the actions SHA-pinned with a trailing # vX.Y.Z",
    "comment, which is the form `mise run pin-actions` already writes and the form",
    "zizmor's unpinned-uses audit demands -- so a Renovate action bump stays green",
    "through the pre-push hook without anyone re-running pinact by hand."
  ],
  "extends": [
    "config:best-practices",
    ":semanticCommits"
  ],
  "labels": ["dependencies"],
  "schedule": ["before 9am on monday"],
  "customManagers": [
    {
      "customType": "regex",
      "description": [
        "hk.pkl names its hk release twice per line -- once in the download URL",
        "path (v1.55.0) and once in the pkl package coordinate (hk@1.55.0) -- across",
        "both the `amends` and `import` lines. hk evaluates that file with its own",
        "embedded pkl, so these MUST move in lockstep with `hk` in mise.toml; the",
        "packageRules entry below groups them into a single PR."
      ],
      "managerFilePatterns": ["/^hk\\.pkl$/"],
      "datasourceTemplate": "github-releases",
      "depNameTemplate": "jdx/hk",
      "extractVersionTemplate": "^v?(?<version>.+)$",
      "matchStrings": [
        "download/v(?<currentValue>\\d+\\.\\d+\\.\\d+)/",
        "hk@(?<currentValue>\\d+\\.\\d+\\.\\d+)#"
      ]
    }
  ],
  "packageRules": [
    {
      "description": [
        "One PR for hk's two pins. `hk` comes from the mise manager reading",
        "mise.toml; `jdx/hk` from the custom manager above reading hk.pkl. Split",
        "across two PRs, either one merged alone leaves the binary and its config",
        "on different releases."
      ],
      "matchDepNames": ["hk", "jdx/hk"],
      "groupName": "hk"
    },
    {
      "description": [
        "Group the linters hk shells out to. They are only ever exercised together",
        "by `hk check --all`, and each one's bump needs the same thing proven: that",
        "a full lint pass over this tree is still clean."
      ],
      "matchManagers": ["mise"],
      "matchDepNames": ["actionlint", "gitleaks", "zizmor"],
      "groupName": "hk linters"
    },
    {
      "description": [
        "A new zizmor or actionlint release can add an audit that fires on a",
        "workflow which was clean the day before, and a new ruff minor can add a",
        "lint or change formatting. That is a real finding worth reading, not a",
        "broken bot -- it should never land unattended."
      ],
      "matchPackageNames": ["zizmor", "actionlint", "ruff"],
      "automerge": false
    },
    {
      "description": [
        "mise.toml's `[tools.\"http:blink\"]` block is generated by",
        "Scripts/update-blink-pin.sh and is content-addressed: the URL contains the",
        "same SHA-256 as the checksum beside it. Renovate's mise manager ignores the",
        "`http` backend today, so this is a no-op; it is here so that stays true."
      ],
      "matchManagers": ["mise"],
      "matchPackageNames": ["http:blink", "blink"],
      "enabled": false
    }
  ]
}
```

`.github/workflows/ci.yml`:

```yaml
name: ci
on:
  push:
    branches: [main]
  pull_request:
permissions:
  contents: read
# Blink is a local agent-review tool nobody runs on a runner (see mise.toml), and a
# vendor CDN has no business standing between a push and a green build: skip its
# download rather than have a pruned pin fail `mise install` here.
env:
  MISE_DISABLE_TOOLS: http:blink
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0
        # Nothing in this job pushes; leaving the token in .git/config only widens
        # what a compromised later step could reach. fetch-depth 0 because hk's
        # gitleaks step scans commit history rather than the working tree, and a
        # shallow clone would have it report a clean scan of a single commit.
        with: {persist-credentials: false, fetch-depth: 0}
      # mise installs the uv/hk/linter versions mise.toml pins, so `hk check --all`
      # below runs the same tools as the local pre-commit hook.
      - uses: jdx/mise-action@c37c93293d6b742fc901e1406b8f764f6fb19dac # v2.4.4
        with: {cache: true}
      - name: Cache uv packages
        uses: actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830 # v4.3.0
        with:
          path: ~/.cache/uv
          key: uv-${{ runner.os }}-${{ hashFiles('uv.lock') }}
          restore-keys: uv-${{ runner.os }}-
      - run: uv sync --all-groups
      - run: hk check --all
      # A runner has no ROM: tests/rom/ skip themselves when JEVPLAYS_ROM is unset.
      - run: uv run pytest -q
```

- [ ] **Step 6: Write the issue templates, `LICENSE`, `CLAUDE.md`, `README.md`, package init, first test**

`.github/ISSUE_TEMPLATE/idea.yml`:

```yaml
name: Idea
description: A feature, improvement, or follow-on to keep track of. Fill in what you know; leave the rest.
labels: [enhancement, idea]
body:
  - type: textarea
    id: what
    attributes:
      label: What
      description: One or two sentences. What would exist or change?
    validations:
      required: true
  - type: textarea
    id: why
    attributes:
      label: Why
      description: Who wants it and what it fixes or enables.
  - type: dropdown
    id: size
    attributes:
      label: Rough size
      options:
        - unknown
        - an afternoon
        - a plan (one branch, one PR)
        - a spec first (several plans)
      default: 0
  - type: textarea
    id: waits-on
    attributes:
      label: Waits on
      description: Anything this cannot start without (another issue, a decision, a release). Add the `blocked` label if so.
```

`.github/ISSUE_TEMPLATE/bug.yml`:

```yaml
name: Bug
description: Something is wrong in the agent, the dashboard, or the CLI.
labels: [bug]
body:
  - type: textarea
    id: steps
    attributes:
      label: Steps
      description: What you did, what happened, what you expected.
    validations:
      required: true
  - type: input
    id: where
    attributes:
      label: Where
      description: Map and mode from the dashboard, or the CLI command. A run directory name if there is one.
  - type: textarea
    id: notes
    attributes:
      label: Notes
      description: A screenshot, a decision log line, a save state name.
```

`.github/ISSUE_TEMPLATE/config.yml`:

```yaml
# Blank issues stay on so a one-line "idea" can be filed without a form.
blank_issues_enabled: true
```

`LICENSE`: the MIT license text with the line `Copyright (c) 2026 Tyler Vick`.

`CLAUDE.md`:

```markdown
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
```

`README.md`:

```markdown
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
```

`src/jevplays/__init__.py`:

```python
"""Jev plays Pokémon: a System One agent with a live probability dashboard."""

__version__ = "0.1.0"
```

`tests/__init__.py`: empty.

`tests/test_package.py`:

```python
import jevplays


def test_version():
    assert jevplays.__version__ == "0.1.0"
```

- [ ] **Step 7: Copy the Blink pin script, sync, install hooks, run the checks**

```bash
mkdir -p Scripts
cp /Users/builder/orca/workspaces/graphghan/Xcode-28/Scripts/update-blink-pin.sh Scripts/
chmod +x Scripts/update-blink-pin.sh
mise trust && mise install
mise run setup
mise run check
```

Expected: `uv sync` writes `uv.lock` and `.venv/`; `hk install` writes the hooks; `hk check --all` passes; `pytest` reports `1 passed`. If `mise install` fails on the Blink download, run `Scripts/update-blink-pin.sh --write` and retry, then keep the rewritten block.

- [ ] **Step 8: Commit**

```bash
git add -A
git status --short   # confirm: no roms/, states/, mise.local.toml, *.state
git commit -m "chore(tooling): scaffold jevplays with the mise/hk/uv stack"
```

---

### Task 2: Gen 1 text decoding

**Files:**
- Create: `src/jevplays/emulator/__init__.py` (empty), `src/jevplays/emulator/text.py`
- Test: `tests/test_text.py`

**Interfaces:**
- Produces: `CHARMAP: dict[int, str]`, `TERMINATOR = 0x50`, `SPACE = 0x7F`, `CURSOR = "▶"`, `ARROW = "▼"`, `NON_TEXT = "·"`, `decode_cells(data) -> list[str]`, `decode_name(data) -> str`, `encode(text: str) -> list[int]`, `row_text(cells) -> str`, `has_text(cells) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_text.py
import pytest

from jevplays.emulator.text import (
    ARROW,
    CURSOR,
    NON_TEXT,
    decode_cells,
    decode_name,
    encode,
    has_text,
    row_text,
)


def test_decode_cells_one_cell_per_tile_even_for_two_character_glyphs():
    # H e l l o <space> 's <map tile>
    cells = decode_cells([0x87, 0xA4, 0xAB, 0xAB, 0xAE, 0x7F, 0xBD, 0x10])
    assert cells == ["H", "e", "l", "l", "o", " ", "'s", NON_TEXT]


def test_decode_cells_marks_cursor_and_arrow():
    assert decode_cells([0xED, 0xEE]) == [CURSOR, ARROW]


def test_decode_cells_digits_and_punctuation():
    assert row_text(decode_cells([0xF6, 0xF9, 0xF6, 0xF0, 0xE8, 0xE7, 0xE6])) == "030¥.!?"


def test_decode_name_stops_at_terminator():
    assert decode_name([0x91, 0x84, 0x83, 0x50, 0x80, 0x80]) == "RED"


def test_decode_name_without_terminator_reads_everything():
    assert decode_name([0x81, 0x8B, 0x94, 0x84]) == "BLUE"


def test_encode_round_trips_single_character_glyphs():
    assert decode_cells(encode("NEW GAME")) == list("NEW GAME")
    assert encode("A") == [0x80]
    assert encode(" ") == [0x7F]


def test_encode_rejects_unknown_characters():
    with pytest.raises(ValueError):
        encode("~")


def test_has_text_ignores_blanks_map_tiles_cursor_and_arrow():
    assert not has_text([" ", NON_TEXT, CURSOR, ARROW])
    assert has_text([NON_TEXT, "S", "A", "V", "E"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_text.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'jevplays.emulator'`

- [ ] **Step 3: Write the implementation**

```python
# src/jevplays/emulator/text.py
"""Gen 1 text: the font tile ids the game writes into its screen buffer, and how to read them.

Pokémon Red draws every piece of text by writing font tile ids into wTileMap (see ram.py), a
20x18 byte buffer copied to VRAM each frame. The ids come from the game's character map
(pokered's charmap.asm): 0x80..0x99 are A..Z, 0xA0..0xB9 a..z, 0xF6..0xFF the digits, 0x7F the
space tile, and a handful are punctuation, the menu cursor (▶, 0xED) and the "press A" arrow
(▼, 0xEE). Ids below 0x7F are map graphics, not text, so they decode to NON_TEXT.

Some ids stand for more than one character ("'s" is one tile). Rows are therefore decoded to a
list of cells, one per tile, so column indexes stay true to the screen; row_text joins them.
"""

from collections.abc import Iterable

CHARMAP: dict[int, str] = {
    0x7F: " ", 0x80: "A", 0x81: "B", 0x82: "C", 0x83: "D", 0x84: "E", 0x85: "F",
    0x86: "G", 0x87: "H", 0x88: "I", 0x89: "J", 0x8A: "K", 0x8B: "L", 0x8C: "M", 0x8D: "N",
    0x8E: "O", 0x8F: "P", 0x90: "Q", 0x91: "R", 0x92: "S", 0x93: "T", 0x94: "U", 0x95: "V",
    0x96: "W", 0x97: "X", 0x98: "Y", 0x99: "Z", 0x9A: "(", 0x9B: ")", 0x9C: ":", 0x9D: ";",
    0x9E: "[", 0x9F: "]", 0xA0: "a", 0xA1: "b", 0xA2: "c", 0xA3: "d", 0xA4: "e", 0xA5: "f",
    0xA6: "g", 0xA7: "h", 0xA8: "i", 0xA9: "j", 0xAA: "k", 0xAB: "l", 0xAC: "m", 0xAD: "n",
    0xAE: "o", 0xAF: "p", 0xB0: "q", 0xB1: "r", 0xB2: "s", 0xB3: "t", 0xB4: "u", 0xB5: "v",
    0xB6: "w", 0xB7: "x", 0xB8: "y", 0xB9: "z", 0xBA: "é", 0xBB: "'d", 0xBC: "'l", 0xBD: "'s",
    0xBE: "'t", 0xBF: "'v", 0xE0: "'", 0xE1: "PK", 0xE2: "MN", 0xE3: "-", 0xE4: "'r",
    0xE5: "'m", 0xE6: "?", 0xE7: "!", 0xE8: ".", 0xEC: "▷", 0xED: "▶", 0xEE: "▼", 0xEF: "♂",
    0xF0: "¥", 0xF1: "×", 0xF2: ".", 0xF3: "/", 0xF4: ",", 0xF5: "♀", 0xF6: "0", 0xF7: "1",
    0xF8: "2", 0xF9: "3", 0xFA: "4", 0xFB: "5", 0xFC: "6", 0xFD: "7", 0xFE: "8", 0xFF: "9",
}
"""Font tile id to text. 0xE1/0xE2 are the two halves of the POKéMON logo glyph."""

TERMINATOR = 0x50
"""Ends a name or string in RAM ("@" in the disassembly)."""
SPACE = 0x7F
CURSOR = "▶"
ARROW = "▼"
NON_TEXT = "·"
"""What a non-font tile (map graphics, box borders) decodes to."""
UNKNOWN = "?"

_REVERSE = {text: tile for tile, text in CHARMAP.items() if len(text) == 1}
_REVERSE["."] = 0xE8  # 0xF2 is the second "." glyph; encode the common one


def decode_cells(data: Iterable[int]) -> list[str]:
    """One cell per tile id. Font tiles become their text; anything else becomes NON_TEXT."""
    return [
        " " if b == SPACE else CHARMAP.get(b, UNKNOWN) if b >= 0x80 else NON_TEXT
        for b in data
    ]


def decode_name(data: Iterable[int]) -> str:
    """Read a terminated string such as a player name. Stops at TERMINATOR if present."""
    out: list[str] = []
    for b in data:
        if b == TERMINATOR:
            break
        out.append(" " if b == SPACE else CHARMAP.get(b, UNKNOWN))
    return "".join(out)


def encode(text: str) -> list[int]:
    """Text to tile ids, for tests and fixtures. Only single-character glyphs are supported."""
    try:
        return [_REVERSE[ch] for ch in text]
    except KeyError as exc:
        raise ValueError(f"no Gen 1 tile for {exc.args[0]!r}") from None


def row_text(cells: Iterable[str]) -> str:
    return "".join(cells)


def has_text(cells: Iterable[str]) -> bool:
    """True when the cells hold something a person would read: not blanks, borders, or markers."""
    return any(c not in (" ", NON_TEXT, CURSOR, ARROW) for c in cells)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_text.py -q`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/emulator tests/test_text.py
git commit -m "feat(emulator): decode Gen 1 font tiles into per-tile cells"
```

---

### Task 3: Named RAM addresses and number decoding

**Files:**
- Create: `src/jevplays/emulator/ram.py`, `tests/support.py`
- Test: `tests/test_ram.py`

**Interfaces:**
- Produces: address constants `wTileMap`, `TILEMAP_WIDTH`, `TILEMAP_HEIGHT`, `TILEMAP_SIZE`, `wTopMenuItemY`, `wTopMenuItemX`, `wCurrentMenuItem`, `wMaxMenuItem`, `wMenuWatchedKeys`, `wJoyIgnore`, `wFontLoaded`, `wIsInBattle`, `wPlayerName`, `NAME_LENGTH`, `wPartyCount`, `wNumBagItems`, `wBagItems`, `wPlayerMoney`, `wRivalName`, `wObtainedBadges`, `wCurMap`, `wYCoord`, `wXCoord`, `wEventFlags`; `class Memory(Protocol)`; `bcd_to_int(data) -> int`; `read_bytes(mem, addr, n) -> bytes`; `read_name(mem, addr) -> str`; `read_tilemap(mem) -> bytes`.
- `tests/support.py` produces `FakeMemory` (used by every later unit test).

- [ ] **Step 1: Write the test support module and the failing tests**

```python
# tests/support.py
"""Fakes shared by the unit tests. Nothing here imports pyboy."""

from jevplays.emulator.ram import TILEMAP_HEIGHT, TILEMAP_SIZE, TILEMAP_WIDTH, wTileMap
from jevplays.emulator.text import NON_TEXT, encode


class FakeMemory:
    """64 KiB of zeros with PyBoy's memory indexing: an int gives a byte, a slice gives a list."""

    def __init__(self) -> None:
        self.data = bytearray(0x10000)

    def __getitem__(self, key: int | slice) -> int | list[int]:
        if isinstance(key, slice):
            return list(self.data[key])
        return self.data[key]

    def __setitem__(self, key: int | slice, value: int | bytes | list[int]) -> None:
        if isinstance(key, slice):
            self.data[key] = bytes(value)
        else:
            self.data[key] = value


MAP_TILE = 0x10
"""A tile id that is map graphics, not font: what "·" in a fixture row becomes."""


def tilemap_bytes(lines: list[str]) -> bytes:
    """Encode fixture rows into a wTileMap buffer. "·" is a map tile; short rows are padded with it."""
    out = bytearray()
    for r in range(TILEMAP_HEIGHT):
        line = lines[r] if r < len(lines) else ""
        for c in range(TILEMAP_WIDTH):
            ch = line[c] if c < len(line) else NON_TEXT
            out.append(MAP_TILE if ch == NON_TEXT else encode(ch)[0])
    assert len(out) == TILEMAP_SIZE
    return bytes(out)


def write_tilemap(mem: FakeMemory, lines: list[str]) -> None:
    mem[wTileMap : wTileMap + TILEMAP_SIZE] = tilemap_bytes(lines)


def rows_from(lines: list[str]) -> list[list[str]]:
    """Fixture rows as the cell lists detect() and snapshot() work on."""
    padded = [(line + NON_TEXT * TILEMAP_WIDTH)[:TILEMAP_WIDTH] for line in lines]
    padded += [NON_TEXT * TILEMAP_WIDTH] * (TILEMAP_HEIGHT - len(padded))
    return [list(line) for line in padded]
```

```python
# tests/test_ram.py
from jevplays.emulator import ram
from jevplays.emulator.text import encode
from tests.support import FakeMemory, write_tilemap


def test_addresses_are_the_documented_wram_locations():
    assert ram.wTileMap == 0xC3A0
    assert ram.TILEMAP_SIZE == 360
    assert ram.wCurrentMenuItem == 0xCC26
    assert ram.wMaxMenuItem == 0xCC28
    assert ram.wFontLoaded == 0xCFC4
    assert ram.wIsInBattle == 0xD057
    assert ram.wPlayerName == 0xD158
    assert ram.wPartyCount == 0xD163
    assert ram.wPlayerMoney == 0xD347
    assert ram.wObtainedBadges == 0xD356
    assert ram.wCurMap == 0xD35E
    assert (ram.wYCoord, ram.wXCoord) == (0xD361, 0xD362)


def test_bcd_to_int_reads_big_endian_packed_decimal():
    assert ram.bcd_to_int([0x00, 0x30, 0x00]) == 3000
    assert ram.bcd_to_int([0x99, 0x99, 0x99]) == 999999
    assert ram.bcd_to_int([0x00, 0x00, 0x00]) == 0


def test_read_name_decodes_until_terminator():
    mem = FakeMemory()
    mem[ram.wPlayerName : ram.wPlayerName + 4] = encode("RED") + [ram.TERMINATOR]
    assert ram.read_name(mem, ram.wPlayerName) == "RED"


def test_read_tilemap_returns_the_whole_buffer():
    mem = FakeMemory()
    write_tilemap(mem, ["▶NEW GAME"])
    raw = ram.read_tilemap(mem)
    assert len(raw) == 360
    assert raw[0] == 0xED
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_ram.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'jevplays.emulator.ram'`

- [ ] **Step 3: Write the implementation**

```python
# src/jevplays/emulator/ram.py
"""Named WRAM addresses for Pokémon Red, plus decoders for the game's number formats.

Names are pokered's (https://github.com/pret/pokered, ram/wram.asm) so each can be looked up in
the disassembly. Every value was checked against the running game on 2026-09-20 and is pinned by
tests/rom/test_ram.py against a save state.
"""

from collections.abc import Iterable
from typing import Protocol

from jevplays.emulator.text import TERMINATOR, decode_name

# The game's own screen buffer: 20 columns x 18 rows of tile ids, copied to VRAM each frame.
# Every menu, dialog box, and battle message is written here first, so it is the one place to
# read on-screen text without scroll math.
wTileMap = 0xC3A0
TILEMAP_WIDTH = 20
TILEMAP_HEIGHT = 18
TILEMAP_SIZE = TILEMAP_WIDTH * TILEMAP_HEIGHT

# Menu state. wCurrentMenuItem is the cursor's index (0-based) and wMaxMenuItem the last index.
wTopMenuItemY = 0xCC24
wTopMenuItemX = 0xCC25
wCurrentMenuItem = 0xCC26
wMaxMenuItem = 0xCC28
wMenuWatchedKeys = 0xCC29

wJoyIgnore = 0xCD6B
# 1 while the START menu (and other overworld menus) has the font loaded into VRAM.
wFontLoaded = 0xCFC4

# 0 outside battle, 1 in a wild battle, 2 in a trainer battle.
wIsInBattle = 0xD057

wPlayerName = 0xD158
NAME_LENGTH = 11  # 10 characters plus the terminator

wPartyCount = 0xD163
wNumBagItems = 0xD31D
wBagItems = 0xD31E
wPlayerMoney = 0xD347  # 3 bytes, packed BCD, big-endian
wRivalName = 0xD34A
wObtainedBadges = 0xD356  # one bit per badge, Boulder Badge is bit 0
wCurMap = 0xD35E
wYCoord = 0xD361
wXCoord = 0xD362
wEventFlags = 0xD747


class Memory(Protocol):
    """What PyBoy's memory view and the test fake have in common."""

    def __getitem__(self, key: int | slice) -> int | list[int]: ...


def bcd_to_int(data: Iterable[int]) -> int:
    """Packed binary-coded decimal, two digits per byte, most significant byte first."""
    value = 0
    for b in data:
        value = value * 100 + (b >> 4) * 10 + (b & 0x0F)
    return value


def read_bytes(mem: Memory, addr: int, n: int) -> bytes:
    return bytes(mem[addr : addr + n])


def read_name(mem: Memory, addr: int) -> str:
    return decode_name(read_bytes(mem, addr, NAME_LENGTH))


def read_tilemap(mem: Memory) -> bytes:
    return read_bytes(mem, wTileMap, TILEMAP_SIZE)
```

`TERMINATOR` is re-exported by the import at the top, so `ram.TERMINATOR` works in tests.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ram.py tests/test_text.py -q`
Expected: `12 passed`

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/emulator/ram.py tests/support.py tests/test_ram.py
git commit -m "feat(emulator): name the WRAM addresses and decode BCD"
```

---

### Task 4: The Emulator wrapper and the ROM test fixtures

**Files:**
- Create: `src/jevplays/emulator/pyboy.py`, `tests/rom/__init__.py` (empty), `tests/rom/conftest.py`
- Test: `tests/rom/test_emulator.py`

**Interfaces:**
- Consumes: `read_tilemap`, `decode_cells`, `TILEMAP_WIDTH`, `TILEMAP_HEIGHT`.
- Produces: `class Emulator` with `title: str`, `mem: Memory`, `tick(frames=1, *, render=False) -> int`, `press(button, *, hold=8, settle=8) -> int`, `tilemap() -> bytes`, `rows() -> list[list[str]]`, `frame_jpeg(quality=80) -> bytes`, `save(path)`, `load(path)`, `close()`, context manager. `BUTTONS` tuple. Fixtures `rom` (Path) and `state_path(name) -> Path` in `tests/rom/conftest.py`.

- [ ] **Step 1: Write the ROM conftest and the failing test**

```python
# tests/rom/conftest.py
"""Fixtures for tests that need the real game.

JEVPLAYS_ROM points at a Pokémon Red or Blue dump. JEVPLAYS_STATES (default: states/) holds
the save states Scripts/make-states.py writes. Missing either skips the test rather than failing
it, so CI, which has neither, stays green while a developer with both gets full coverage.
"""

import os
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def rom() -> Path:
    path = os.environ.get("JEVPLAYS_ROM")
    if not path or not Path(path).is_file():
        pytest.skip("JEVPLAYS_ROM is not set or does not point at a file")
    return Path(path)


@pytest.fixture(scope="session")
def states_dir() -> Path:
    return Path(os.environ.get("JEVPLAYS_STATES", "states"))


@pytest.fixture
def state_path(states_dir: Path) -> Callable[[str], Path]:
    def _state(name: str) -> Path:
        path = states_dir / f"{name}.state"
        if not path.is_file():
            pytest.skip(f"{path} is missing; run `mise run states`")
        return path

    return _state
```

```python
# tests/rom/test_emulator.py
from jevplays.emulator.pyboy import BUTTONS, Emulator
from jevplays.emulator.ram import TILEMAP_HEIGHT, TILEMAP_SIZE, TILEMAP_WIDTH, wCurMap


def test_boots_headless_and_reports_the_cartridge(rom):
    with Emulator(rom) as emu:
        assert emu.title == "POKEMON RED"
        assert emu.tick(10) == 10
        assert emu.mem[wCurMap] == 0  # nothing loaded yet at the title screen


def test_tilemap_and_rows_have_the_screen_shape(rom):
    with Emulator(rom) as emu:
        emu.tick(120)
        assert len(emu.tilemap()) == TILEMAP_SIZE
        rows = emu.rows()
        assert len(rows) == TILEMAP_HEIGHT
        assert all(len(r) == TILEMAP_WIDTH for r in rows)


def test_frame_is_a_jpeg(rom):
    with Emulator(rom) as emu:
        emu.tick(120)
        jpeg = emu.frame_jpeg()
        assert jpeg[:2] == b"\xff\xd8"


def test_press_returns_frames_spent_and_rejects_unknown_buttons(rom):
    import pytest

    with Emulator(rom) as emu:
        assert emu.press("start", hold=4, settle=6) == 10
        assert "select" in BUTTONS
        with pytest.raises(ValueError):
            emu.press("x")


def test_save_and_load_round_trip(rom, tmp_path):
    with Emulator(rom) as emu:
        emu.tick(300)
        before = emu.tilemap()
        path = tmp_path / "t.state"
        emu.save(path)
        emu.tick(300)
        emu.load(path)
        assert emu.tilemap() == before
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/rom/test_emulator.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'jevplays.emulator.pyboy'` (with `JEVPLAYS_ROM` set; without it, `5 skipped`).

- [ ] **Step 3: Write the implementation**

```python
# src/jevplays/emulator/pyboy.py
"""The one module that imports PyBoy.

Everything else sees an Emulator: ticks, button presses, memory, the screen buffer, and JPEG
frames. Headless by default (window="null"); emulation speed is unlimited so the loop, not the
emulator, decides pacing.
"""

from io import BytesIO
from pathlib import Path

from pyboy import PyBoy

from jevplays.emulator.ram import TILEMAP_HEIGHT, TILEMAP_WIDTH, Memory, read_tilemap
from jevplays.emulator.text import decode_cells

BUTTONS = ("a", "b", "start", "select", "up", "down", "left", "right")


class Emulator:
    def __init__(self, rom: Path, *, window: str = "null") -> None:
        self._py = PyBoy(str(rom), window=window, sound_emulated=False)
        self._py.set_emulation_speed(0)

    def __enter__(self) -> "Emulator":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def title(self) -> str:
        return self._py.cartridge_title

    @property
    def mem(self) -> Memory:
        return self._py.memory

    def tick(self, frames: int = 1, *, render: bool = False) -> int:
        """Advance `frames` frames. Returns the frames spent so the loop can pace wall time."""
        self._py.tick(frames, render, False)
        return frames

    def press(self, button: str, *, hold: int = 8, settle: int = 8) -> int:
        """Hold a button for `hold` frames, then let the game settle for `settle` more."""
        if button not in BUTTONS:
            raise ValueError(f"unknown button {button!r}; expected one of {BUTTONS}")
        self._py.button(button, hold)
        return self.tick(hold + settle)

    def tilemap(self) -> bytes:
        return read_tilemap(self.mem)

    def rows(self) -> list[list[str]]:
        raw = self.tilemap()
        return [
            decode_cells(raw[r * TILEMAP_WIDTH : (r + 1) * TILEMAP_WIDTH]) for r in range(TILEMAP_HEIGHT)
        ]

    def frame_jpeg(self, quality: int = 80) -> bytes:
        """Render one frame and return it as JPEG bytes (160x144)."""
        self._py.tick(1, True, False)
        buf = BytesIO()
        self._py.screen.image.convert("RGB").save(buf, "JPEG", quality=quality)
        return buf.getvalue()

    def save(self, path: Path) -> None:
        with open(path, "wb") as f:
            self._py.save_state(f)

    def load(self, path: Path) -> None:
        with open(path, "rb") as f:
            self._py.load_state(f)
        self.tick(1)

    def close(self) -> None:
        self._py.stop(save=False)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/rom/test_emulator.py -q`
Expected: `5 passed` (PyBoy prints a `UserWarning` about SDL2 binaries; that is fine).

- [ ] **Step 5: Confirm the unit suite still imports without PyBoy side effects**

Run: `uv run pytest tests -q --ignore=tests/rom`
Expected: `13 passed`

- [ ] **Step 6: Commit**

```bash
git add src/jevplays/emulator/pyboy.py tests/rom
git commit -m "feat(emulator): wrap PyBoy headless with ticks, presses, frames, and states"
```

---

### Task 5: Walk the intro and write the save states

**Files:**
- Create: `src/jevplays/emulator/intro.py`, `Scripts/make-states.py`
- Test: `tests/test_intro.py` (unit, cursor label parsing), `tests/rom/test_intro.py`

**Interfaces:**
- Consumes: `Emulator.rows/press/tick/mem/save`, `CURSOR`, `ARROW`, `row_text`, `wYCoord`.
- Produces: `cursor_label(rows) -> str | None`, `walk_intro(emu, *, max_steps=600) -> int`, `class IntroError(RuntimeError)`. `states/overworld.state`, `states/dialog.state`, `states/menu.state`, `states/prompt.state`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_intro.py
from jevplays.emulator.intro import cursor_label
from tests.support import rows_from


def test_cursor_label_reads_the_text_after_the_cursor():
    rows = rows_from(["···············", "·             ·", "·▶NEW GAME    ·", "· OPTION      ·"])
    assert cursor_label(rows) == "NEW GAME"


def test_cursor_label_is_none_without_a_cursor():
    assert cursor_label(rows_from(["·Hello there!·"])) is None
```

```python
# tests/rom/test_intro.py
from jevplays.emulator.intro import walk_intro
from jevplays.emulator.pyboy import Emulator
from jevplays.emulator.ram import wCurMap, wPartyCount, wPlayerName, wRivalName, wXCoord, wYCoord, read_name


def test_walk_intro_reaches_reds_bedroom(rom):
    with Emulator(rom) as emu:
        steps = walk_intro(emu)
        assert 0 < steps < 600
        assert emu.mem[wCurMap] == 38  # REDS_HOUSE_2F
        assert (emu.mem[wXCoord], emu.mem[wYCoord]) == (3, 7)  # one step below the start tile
        assert emu.mem[wPartyCount] == 0
        assert read_name(emu.mem, wPlayerName) == "RED"
        assert read_name(emu.mem, wRivalName) == "BLUE"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_intro.py tests/rom/test_intro.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'jevplays.emulator.intro'`

- [ ] **Step 3: Write the implementation**

```python
# src/jevplays/emulator/intro.py
"""From power-on to the first step in Red's bedroom, driven by what is on screen.

The intro is a fixed script (title, NEW GAME, Oak's speech, two name menus, the shrink into the
bedroom), but its timing is not, so counting A presses is brittle. Instead each iteration looks
at the screen buffer: a NEW NAME menu gets "down, A" to pick the first preset name (RED, then
BLUE); the blinking "press A" arrow gets an A; once both names are chosen, a test step down that
actually moves the player means the overworld is live. Measured at 92 iterations and 0.2 s.
"""

from jevplays.emulator.ram import wYCoord
from jevplays.emulator.text import ARROW, CURSOR, NON_TEXT, row_text

ARROW_ROW, ARROW_COL = 16, 18
"""Where the ▼ arrow blinks while a dialog box waits for A."""


class IntroError(RuntimeError):
    pass


def cursor_label(rows: list[list[str]]) -> str | None:
    """The text to the right of the first ▶ on screen, or None when there is no cursor."""
    for cells in rows:
        if CURSOR in cells:
            c = cells.index(CURSOR)
            return row_text(cells[c + 1 :]).strip(" " + NON_TEXT)
    return None


def walk_intro(emu, *, max_steps: int = 600) -> int:
    """Press through the intro until the player can move. Returns the iterations it took."""
    emu.tick(120)
    for _ in range(400):
        if cursor_label(emu.rows()) == "NEW GAME":
            break
        emu.press("start", hold=4, settle=6)
    else:
        raise IntroError("the title screen never showed NEW GAME")
    emu.press("a", settle=60)

    names_chosen = 0
    for step in range(max_steps):
        rows = emu.rows()
        if cursor_label(rows) == "NEW NAME":
            emu.press("down")
            emu.press("a", settle=60)
            names_chosen += 1
            continue
        if rows[ARROW_ROW][ARROW_COL] == ARROW:
            emu.press("a", settle=30)
            continue
        if names_chosen == 2:
            y = emu.mem[wYCoord]
            emu.press("down", settle=16)
            if emu.mem[wYCoord] != y:
                return step
        emu.tick(30)
    raise IntroError(f"the intro did not reach the overworld within {max_steps} iterations")
```

```python
#!/usr/bin/env -S uv run
# Scripts/make-states.py
"""Write the save states tests/rom/ load, one per Mode the harness detects.

    uv run Scripts/make-states.py [--out states/]

Needs JEVPLAYS_ROM. Each state is a snapshot of the game a few frames into a known screen:

    overworld.state   Red's bedroom, player free to move
    dialog.state      Oak's "Hello there!" with the ▼ arrow waiting for A
    menu.state        the START menu open in the bedroom
    prompt.state      the SAVE yes/no question ("Would you like to SAVE the game?")

Save states are gitignored: they are copies of the game's memory.
"""

import argparse
import os
import sys
from pathlib import Path

from jevplays.emulator.intro import ARROW_COL, ARROW_ROW, cursor_label, walk_intro
from jevplays.emulator.pyboy import Emulator
from jevplays.emulator.text import ARROW
from jevplays.state.modes import yes_no_at


def wait_for(emu: Emulator, condition, *, frames: int = 600, every: int = 5) -> None:
    for _ in range(0, frames, every):
        if condition(emu.rows()):
            return
        emu.tick(every)
    raise SystemExit("timed out waiting for the screen to settle")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path(os.environ.get("JEVPLAYS_STATES", "states")))
    args = parser.parse_args(argv)
    rom = os.environ.get("JEVPLAYS_ROM")
    if not rom:
        print("JEVPLAYS_ROM is not set", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)

    with Emulator(Path(rom)) as emu:
        emu.tick(120)
        for _ in range(400):
            if cursor_label(emu.rows()) == "NEW GAME":
                break
            emu.press("start", hold=4, settle=6)
        emu.press("a", settle=60)
        wait_for(emu, lambda rows: rows[ARROW_ROW][ARROW_COL] == ARROW)
        emu.save(args.out / "dialog.state")

    with Emulator(Path(rom)) as emu:
        walk_intro(emu)
        emu.tick(30)
        emu.save(args.out / "overworld.state")

        emu.press("start", settle=30)
        wait_for(emu, lambda rows: cursor_label(rows) == "POKéMON")
        emu.save(args.out / "menu.state")

        for _ in range(3):
            emu.press("down")
        emu.press("a", settle=60)
        # cursor_label would read "YES·IME…" here because the box overlaps the trainer card,
        # so use the same YES/NO detector snapshot() relies on.
        wait_for(emu, lambda rows: yes_no_at(rows) is not None)
        emu.save(args.out / "prompt.state")

    for name in ("dialog", "overworld", "menu", "prompt"):
        print(f"wrote {args.out / name}.state")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests and write the states**

Run: `uv run pytest tests/test_intro.py tests/rom/test_intro.py -q`
Expected: `3 passed`

Run: `mise run states`
Expected: four `wrote states/....state` lines and four files of about 168 KB each under `states/`. `git status --short` must not list them.

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/emulator/intro.py Scripts/make-states.py tests/test_intro.py tests/rom/test_intro.py
git commit -m "feat(emulator): walk the intro by reading the screen, and write the test save states"
```

---

### Task 6: Mode detection

**Files:**
- Create: `src/jevplays/state/__init__.py` (empty), `src/jevplays/state/modes.py`
- Test: `tests/test_modes.py`

**Interfaces:**
- Consumes: `CURSOR`, `ARROW`, `row_text`, `has_text`, `SPACE`.
- Produces: `class Mode(StrEnum)` with `OVERWORLD, BATTLE_MENU, BATTLE_WAIT, DIALOG, PROMPT, MENU, TRANSITION`; `DIALOG_ROWS = range(13, 17)`; `find_cursor(rows) -> tuple[int, int] | None`; `yes_no_at(rows) -> tuple[int, int] | None`; `is_blank(raw: bytes) -> bool`; `detect(rows, *, in_battle: bool, blank: bool) -> Mode`.

- [ ] **Step 1: Write the failing tests**

The fixtures below are transcribed from the real screen buffer (Task 5's probes).

```python
# tests/test_modes.py
from jevplays.state.modes import Mode, detect, find_cursor, is_blank, yes_no_at
from tests.support import rows_from, tilemap_bytes

OVERWORLD = rows_from([])  # map tiles everywhere, nothing drawn on top

START_MENU = rows_from(
    [
        "····················",
        "···········        ·",
        "···········▶POKéMON·",
        "···········        ·",
        "··········· ITEM   ·",
        "···········        ·",
        "··········· RED    ·",
        "···········        ·",
        "··········· SAVE   ·",
        "···········        ·",
        "··········· OPTION ·",
        "···········        ·",
        "··········· EXIT   ·",
    ]
)

DIALOG_WAITING = rows_from(
    [
        "                    ",
        "                    ",
        "                    ",
        "                    ",
        "      ·······       ",
        "      ·······       ",
        "      ·······       ",
        "      ·······       ",
        "      ·······       ",
        "      ·······       ",
        "      ·······       ",
        "                    ",
        "····················",
        "·                  ·",
        "·Hello there!      ·",
        "·                  ·",
        "·Welcome to the   ▼·",
        "····················",
    ]
)

SAVE_PROMPT = rows_from(
    [
        "····················",
        "·····              ·",
        "·····PLAYER RED    ·",
        "·····              ·",
        "·····BADGES       0·",
        "·····              ·",
        "·····POKéDEX      0·",
        "······             ·",
        "·▶YES·IME      0·00·",
        "·    ···············",
        "· NO ······ OPTION ·",
        "···········        ·",
        "····················",
        "·                  ·",
        "·Would you like to ·",
        "·                  ·",
        "·SAVE the game?    ·",
        "····················",
    ]
)

BATTLE_MENU = rows_from(
    [""] * 12
    + [
        "····················",
        "·        ··········",
        "·        ·▶FIGHT PK·",
        "·        ··········",
        "·        · ITEM RUN·",
        "····················",
    ]
)

BATTLE_TEXT = rows_from(
    [""] * 12
    + [
        "····················",
        "·                  ·",
        "·Wild PIDGEY       ·",
        "·                  ·",
        "·appeared!        ▼·",
        "····················",
    ]
)


def test_overworld_when_nothing_is_drawn_over_the_map():
    assert detect(OVERWORLD, in_battle=False, blank=False) is Mode.OVERWORLD


def test_menu_when_a_cursor_is_on_screen():
    assert detect(START_MENU, in_battle=False, blank=False) is Mode.MENU
    assert find_cursor(START_MENU) == (2, 11)


def test_dialog_when_text_fills_the_bottom_box():
    assert detect(DIALOG_WAITING, in_battle=False, blank=False) is Mode.DIALOG


def test_prompt_when_yes_no_box_is_open():
    assert yes_no_at(SAVE_PROMPT) == (8, 1)
    assert detect(SAVE_PROMPT, in_battle=False, blank=False) is Mode.PROMPT


def test_prompt_with_cursor_on_no():
    rows = [list(r) for r in SAVE_PROMPT]
    rows[8][1], rows[10][1] = " ", "▶"
    assert yes_no_at(rows) == (8, 1)
    assert detect(rows, in_battle=False, blank=False) is Mode.PROMPT


def test_battle_menu_and_battle_wait():
    assert detect(BATTLE_MENU, in_battle=True, blank=False) is Mode.BATTLE_MENU
    assert detect(BATTLE_TEXT, in_battle=True, blank=False) is Mode.BATTLE_WAIT


def test_battle_flag_wins_over_screen_contents():
    assert detect(START_MENU, in_battle=True, blank=False) is Mode.BATTLE_WAIT


def test_transition_when_the_buffer_is_blank():
    assert detect(OVERWORLD, in_battle=False, blank=True) is Mode.TRANSITION


def test_is_blank_only_for_spaces_and_zeros():
    assert is_blank(bytes([0x7F] * 360))
    assert is_blank(bytes(360))
    assert not is_blank(tilemap_bytes([]))  # map tiles are not blank
    assert not is_blank(tilemap_bytes(["·▶NEW GAME"]))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_modes.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'jevplays.state'`

- [ ] **Step 3: Write the implementation**

```python
# src/jevplays/state/modes.py
"""Which kind of moment the game is in, read from its screen buffer and one RAM flag.

The loop (loop.py) acts on the Mode: a decision point (BATTLE_MENU, PROMPT, MENU, OVERWORLD)
is where Jev gets asked; DIALOG and BATTLE_WAIT get an A press; TRANSITION gets a wait.

Detection order matters and is tested: the battle flag wins over anything drawn on screen,
because a battle can show menus and prompts of its own that milestone 2 handles as battle
state; a yes/no box beats a plain menu because both show a cursor; a cursor beats a dialog
box because a menu can sit over one; text in the bottom box means a dialog; anything else is
the overworld.
"""

from enum import StrEnum

from jevplays.emulator.text import CURSOR, SPACE, has_text, row_text


class Mode(StrEnum):
    OVERWORLD = "overworld"
    BATTLE_MENU = "battle_menu"
    BATTLE_WAIT = "battle_wait"
    DIALOG = "dialog"
    PROMPT = "prompt"
    MENU = "menu"
    TRANSITION = "transition"


DIALOG_ROWS = range(13, 17)
"""The text lines of the standard bottom dialog box (its border is rows 12 and 17)."""
BATTLE_MENU_ROW = 14
"""FIGHT is written on this row of the battle command box."""


def find_cursor(rows: list[list[str]]) -> tuple[int, int] | None:
    """(row, column) of the first ▶ on screen."""
    for r, cells in enumerate(rows):
        if CURSOR in cells:
            return r, cells.index(CURSOR)
    return None


def yes_no_at(rows: list[list[str]]) -> tuple[int, int] | None:
    """(row, column) of a YES/NO box's cursor column: YES on one row, NO two rows below it."""
    for r in range(len(rows) - 2):
        cells = rows[r]
        for c in range(len(cells) - 3):
            if cells[c] not in (CURSOR, " "):
                continue
            if row_text(cells[c + 1 : c + 4]) == "YES" and row_text(rows[r + 2][c + 1 : c + 3]) == "NO":
                return r, c
    return None


def is_blank(raw: bytes) -> bool:
    """True when nothing at all is drawn: every tile is the space tile or zero (a fade)."""
    return all(b in (0, SPACE) for b in raw)


def detect(rows: list[list[str]], *, in_battle: bool, blank: bool) -> Mode:
    if blank:
        return Mode.TRANSITION
    if in_battle:
        if "FIGHT" in row_text(rows[BATTLE_MENU_ROW]):
            return Mode.BATTLE_MENU
        return Mode.BATTLE_WAIT
    if yes_no_at(rows) is not None:
        return Mode.PROMPT
    if find_cursor(rows) is not None:
        return Mode.MENU
    if any(has_text(rows[r]) for r in DIALOG_ROWS):
        return Mode.DIALOG
    return Mode.OVERWORLD
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_modes.py -q`
Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/state tests/test_modes.py
git commit -m "feat(state): detect the game's mode from the screen buffer and the battle flag"
```

---

### Task 7: Map names and the GameState snapshot

**Files:**
- Create: `src/jevplays/state/names.py`, `src/jevplays/state/snapshot.py`
- Test: `tests/test_names.py`, `tests/test_snapshot.py`, `tests/rom/test_snapshot.py`, `tests/rom/test_ram.py`
- Modify: `tests/support.py` (add `FakeEmulator`)

**Interfaces:**
- Consumes: `Mode`, `detect`, `find_cursor`, `is_blank`, `DIALOG_ROWS`, `ram.*`, `decode_cells`, `row_text`, `has_text`, `CURSOR`, `ARROW`, `NON_TEXT`.
- Produces: `map_name(map_id: int) -> str`; `class EmulatorLike(Protocol)` with `mem`, `tilemap()`; `@dataclass(frozen=True) class GameState` with fields `mode: Mode, map_id: int, map: str, tile: tuple[int, int], player_name: str, party_count: int, badges: int, money: int, bag_count: int, in_battle: bool, text: str, menu_items: tuple[str, ...], cursor: int | None` and `to_dict() -> dict`; `snapshot(emu: EmulatorLike) -> GameState`; `dialog_text(rows) -> str`; `menu_items(rows, mode) -> tuple[str, ...]`. `tests.support.FakeEmulator` with `mem`, `set_rows(lines)`, `tilemap()`, `tick()`, `press()`, `frame_jpeg()`, `presses: list[str]`, `frames: int`.

- [ ] **Step 1: Add `FakeEmulator` to `tests/support.py` and write the failing tests**

Append to `tests/support.py`:

```python
class FakeEmulator:
    """Enough of Emulator for snapshot() and Loop: memory, a screen buffer, and recorded input."""

    def __init__(self) -> None:
        self.mem = FakeMemory()
        self.presses: list[str] = []
        self.frames = 0
        self.set_rows([])

    def set_rows(self, lines: list[str]) -> None:
        write_tilemap(self.mem, lines)

    def tilemap(self) -> bytes:
        return bytes(self.mem.data[wTileMap : wTileMap + TILEMAP_SIZE])

    def tick(self, frames: int = 1, *, render: bool = False) -> int:
        self.frames += frames
        return frames

    def press(self, button: str, *, hold: int = 8, settle: int = 8) -> int:
        self.presses.append(button)
        return self.tick(hold + settle)

    def frame_jpeg(self, quality: int = 80) -> bytes:
        return b"\xff\xd8fake"
```

```python
# tests/test_names.py
from jevplays.state.names import map_name


def test_known_maps_have_display_names():
    assert map_name(0) == "Pallet Town"
    assert map_name(38) == "Red's House 2F"
    assert map_name(40) == "Oak's Lab"
    assert map_name(51) == "Viridian Forest"


def test_routes_are_derived_from_their_id():
    assert map_name(12) == "Route 1"
    assert map_name(36) == "Route 25"


def test_unknown_map_falls_back_to_its_number():
    assert map_name(200) == "Map 200"
```

```python
# tests/test_snapshot.py
from jevplays.emulator import ram
from jevplays.emulator.text import encode
from jevplays.state.modes import Mode
from jevplays.state.snapshot import GameState, dialog_text, menu_items, snapshot
from tests.support import FakeEmulator, rows_from


def bedroom(emu: FakeEmulator) -> None:
    emu.mem[ram.wCurMap] = 38
    emu.mem[ram.wXCoord] = 3
    emu.mem[ram.wYCoord] = 7
    emu.mem[ram.wPlayerName : ram.wPlayerName + 4] = encode("RED") + [ram.TERMINATOR]
    emu.mem[ram.wPlayerMoney : ram.wPlayerMoney + 3] = [0x00, 0x30, 0x00]
    emu.mem[ram.wObtainedBadges] = 0b00000101
    emu.mem[ram.wNumBagItems] = 2


def test_snapshot_in_the_overworld():
    emu = FakeEmulator()
    bedroom(emu)
    state = snapshot(emu)
    assert isinstance(state, GameState)
    assert state.mode is Mode.OVERWORLD
    assert state.map_id == 38 and state.map == "Red's House 2F"
    assert state.tile == (3, 7)
    assert state.player_name == "RED"
    assert state.money == 3000
    assert state.badges == 2
    assert state.bag_count == 2
    assert state.party_count == 0
    assert state.in_battle is False
    assert state.text == ""
    assert state.menu_items == ()
    assert state.cursor is None


def test_snapshot_reads_menu_items_and_cursor():
    emu = FakeEmulator()
    bedroom(emu)
    emu.set_rows(
        [
            "····················",
            "···········        ·",
            "···········▶POKéMON·",
            "···········        ·",
            "··········· ITEM   ·",
            "···········        ·",
            "··········· RED    ·",
            "···········        ·",
            "··········· SAVE   ·",
            "···········        ·",
            "··········· OPTION ·",
            "···········        ·",
            "··········· EXIT   ·",
        ]
    )
    emu.mem[ram.wCurrentMenuItem] = 3
    state = snapshot(emu)
    assert state.mode is Mode.MENU
    assert state.menu_items == ("POKéMON", "ITEM", "RED", "SAVE", "OPTION", "EXIT")
    assert state.cursor == 3


def test_snapshot_reads_dialog_text_without_the_arrow():
    emu = FakeEmulator()
    bedroom(emu)
    emu.set_rows(
        [""] * 12
        + [
            "····················",
            "·                  ·",
            "·Hello there!      ·",
            "·                  ·",
            "·Welcome to the   ▼·",
            "····················",
        ]
    )
    state = snapshot(emu)
    assert state.mode is Mode.DIALOG
    assert state.text == "Hello there! Welcome to the"


def test_prompt_items_are_yes_and_no():
    rows = rows_from(["·▶YES·", "·    ·", "· NO ·"])
    assert menu_items(rows, Mode.PROMPT) == ("YES", "NO")


def test_dialog_text_joins_only_the_text_rows():
    rows = rows_from([""] * 13 + ["·First, what is    ·", "·                  ·", "·your name?        ·"])
    assert dialog_text(rows) == "First, what is your name?"


def test_to_dict_is_json_ready():
    emu = FakeEmulator()
    bedroom(emu)
    d = snapshot(emu).to_dict()
    assert d["mode"] == "overworld"
    assert d["tile"] == [3, 7]
    assert d["menu_items"] == []
```

```python
# tests/rom/test_snapshot.py
import pytest

from jevplays.emulator.pyboy import Emulator
from jevplays.state.modes import Mode
from jevplays.state.snapshot import snapshot


@pytest.mark.parametrize(
    "name, mode",
    [
        ("overworld", Mode.OVERWORLD),
        ("dialog", Mode.DIALOG),
        ("menu", Mode.MENU),
        ("prompt", Mode.PROMPT),
    ],
)
def test_each_saved_state_is_detected_as_its_mode(rom, state_path, name, mode):
    with Emulator(rom) as emu:
        emu.load(state_path(name))
        assert snapshot(emu).mode is mode


def test_overworld_state_details(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("overworld"))
        state = snapshot(emu)
        assert state.map == "Red's House 2F"
        assert state.player_name == "RED"
        assert state.money == 3000
        assert state.party_count == 0
        assert state.badges == 0


def test_menu_state_lists_the_start_menu(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("menu"))
        state = snapshot(emu)
        assert "SAVE" in state.menu_items
        assert state.cursor == 0


def test_dialog_state_carries_oaks_greeting(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("dialog"))
        assert "Hello there!" in snapshot(emu).text


def test_prompt_state_offers_yes_no(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("prompt"))
        state = snapshot(emu)
        assert state.menu_items == ("YES", "NO")
        assert "SAVE the game?" in state.text
```

```python
# tests/rom/test_ram.py
"""Pins every address ram.py names against the running game, one save state at a time."""

from jevplays.emulator import ram
from jevplays.emulator.pyboy import Emulator


def test_overworld_addresses(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("overworld"))
        m = emu.mem
        assert m[ram.wCurMap] == 38
        assert m[ram.wXCoord] == 3 and m[ram.wYCoord] == 7
        assert m[ram.wIsInBattle] == 0
        assert m[ram.wPartyCount] == 0
        assert m[ram.wNumBagItems] == 0
        assert m[ram.wObtainedBadges] == 0
        assert ram.bcd_to_int(ram.read_bytes(m, ram.wPlayerMoney, 3)) == 3000
        assert ram.read_name(m, ram.wPlayerName) == "RED"
        assert ram.read_name(m, ram.wRivalName) == "BLUE"
        assert m[ram.wFontLoaded] == 0


def test_menu_addresses(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("menu"))
        m = emu.mem
        assert m[ram.wFontLoaded] == 1
        assert m[ram.wCurrentMenuItem] == 0
        assert m[ram.wMaxMenuItem] >= 4  # POKéMON, ITEM, RED, SAVE, OPTION, EXIT
        assert m[ram.wTopMenuItemX] == 11


def test_prompt_addresses(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("prompt"))
        m = emu.mem
        assert m[ram.wMaxMenuItem] == 1  # YES / NO
        assert m[ram.wTopMenuItemY] == 8
        assert m[ram.wTopMenuItemX] == 1


def test_tilemap_holds_the_screen(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("dialog"))
        # The ▼ arrow blinks (about 16 frames on, 16 off), so give it up to a second to show.
        for _ in range(30):
            if ram.read_tilemap(emu.mem)[16 * ram.TILEMAP_WIDTH + 18] == 0xEE:
                break
            emu.tick(2)
        else:
            raise AssertionError("the ▼ arrow never appeared at row 16, column 18")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_names.py tests/test_snapshot.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'jevplays.state.names'`

- [ ] **Step 3: Write the implementation**

```python
# src/jevplays/state/names.py
"""Display names for map ids. Species, moves, types, and items join in milestone 2."""

_CITIES = {
    0: "Pallet Town",
    1: "Viridian City",
    2: "Pewter City",
    3: "Cerulean City",
    4: "Lavender Town",
    5: "Vermilion City",
    6: "Celadon City",
    7: "Fuchsia City",
    8: "Cinnabar Island",
    9: "Indigo Plateau",
    10: "Saffron City",
}

_EARLY_GAME = {
    37: "Red's House 1F",
    38: "Red's House 2F",
    39: "Blue's House",
    40: "Oak's Lab",
    41: "Viridian Pokémon Center",
    42: "Viridian Mart",
    43: "Viridian School",
    44: "Viridian Nickname House",
    45: "Viridian Gym",
    46: "Diglett's Cave (Route 2)",
    47: "Viridian Forest North Gate",
    48: "Route 2 Trade House",
    49: "Route 2 Gate",
    50: "Viridian Forest South Gate",
    51: "Viridian Forest",
    52: "Museum 1F",
    53: "Museum 2F",
    54: "Pewter Gym",
    55: "Pewter Nidoran House",
    56: "Pewter Mart",
    57: "Pewter Speech House",
    58: "Pewter Pokémon Center",
    59: "Mt. Moon 1F",
}

MAP_NAMES: dict[int, str] = {**_CITIES, **_EARLY_GAME}
# Map ids 12..36 are Route 1..Route 25 in order.
MAP_NAMES.update({map_id: f"Route {map_id - 11}" for map_id in range(12, 37)})


def map_name(map_id: int) -> str:
    return MAP_NAMES.get(map_id, f"Map {map_id}")
```

```python
# src/jevplays/state/snapshot.py
"""GameState: everything the loop, the brain, and the dashboard know about the game right now.

snapshot() is a pure function of the emulator's memory. It never presses a button and never
keeps state between calls, which is what lets the brain be tested on recorded snapshots and
what keeps inferred state (later milestones) separate from observed facts (this).
"""

from dataclasses import asdict, dataclass
from typing import Protocol

from jevplays.emulator import ram
from jevplays.emulator.text import ARROW, CURSOR, NON_TEXT, decode_cells, has_text, row_text
from jevplays.state.modes import DIALOG_ROWS, Mode, detect, find_cursor, is_blank
from jevplays.state.names import map_name


class EmulatorLike(Protocol):
    @property
    def mem(self) -> ram.Memory: ...

    def tilemap(self) -> bytes: ...


@dataclass(frozen=True)
class GameState:
    mode: Mode
    map_id: int
    map: str
    tile: tuple[int, int]
    """(x, y) on the current map. For the executor only; never sent to Jev."""
    player_name: str
    party_count: int
    badges: int
    money: int
    bag_count: int
    in_battle: bool
    text: str
    """The dialog box's text, joined into one line, without the ▼ arrow."""
    menu_items: tuple[str, ...]
    cursor: int | None
    """Index of the highlighted item while a menu or prompt is open."""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["mode"] = str(self.mode)
        d["tile"] = list(self.tile)
        d["menu_items"] = list(self.menu_items)
        return d


def rows_of(raw: bytes) -> list[list[str]]:
    return [
        decode_cells(raw[r * ram.TILEMAP_WIDTH : (r + 1) * ram.TILEMAP_WIDTH]) for r in range(ram.TILEMAP_HEIGHT)
    ]


def dialog_text(rows: list[list[str]]) -> str:
    lines = []
    for r in DIALOG_ROWS:
        cells = [c for c in rows[r] if c != ARROW]
        line = row_text(cells).strip(" " + NON_TEXT)
        if line:
            lines.append(line)
    return " ".join(lines)


def menu_items(rows: list[list[str]], mode: Mode) -> tuple[str, ...]:
    """The labels of an open menu, top to bottom, read from the cursor's column."""
    if mode is Mode.PROMPT:
        return ("YES", "NO")
    if mode is not Mode.MENU:
        return ()
    pos = find_cursor(rows)
    if pos is None:
        return ()
    _, col = pos
    items = []
    for cells in rows:
        if col < len(cells) and cells[col] in (CURSOR, " ") and has_text(cells[col + 1 :]):
            items.append(row_text(cells[col + 1 :]).strip(" " + NON_TEXT))
    return tuple(items)


def snapshot(emu: EmulatorLike) -> GameState:
    mem = emu.mem
    raw = emu.tilemap()
    rows = rows_of(raw)
    in_battle = mem[ram.wIsInBattle] != 0
    mode = detect(rows, in_battle=in_battle, blank=is_blank(raw))
    map_id = mem[ram.wCurMap]
    return GameState(
        mode=mode,
        map_id=map_id,
        map=map_name(map_id),
        tile=(mem[ram.wXCoord], mem[ram.wYCoord]),
        player_name=ram.read_name(mem, ram.wPlayerName),
        party_count=mem[ram.wPartyCount],
        badges=mem[ram.wObtainedBadges].bit_count(),
        money=ram.bcd_to_int(ram.read_bytes(mem, ram.wPlayerMoney, 3)),
        bag_count=mem[ram.wNumBagItems],
        in_battle=in_battle,
        text=dialog_text(rows),
        menu_items=menu_items(rows, mode),
        cursor=mem[ram.wCurrentMenuItem] if mode in (Mode.MENU, Mode.PROMPT) else None,
    )
```

- [ ] **Step 4: Run all tests, unit and ROM**

Run: `uv run pytest -q`
Expected: every test passes; with the ROM and states present that is `39 passed` or more, none failed. If `test_prompt_state_offers_yes_no` fails on `text`, the prompt state was saved before the question finished printing: rerun `mise run states` (its `wait_for` waits for the YES cursor, which appears after the text).

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/state tests/support.py tests/test_names.py tests/test_snapshot.py tests/rom/test_snapshot.py tests/rom/test_ram.py
git commit -m "feat(state): GameState snapshot with map names, menu items, and dialog text"
```

---

### Task 8: Dashboard events, server, and page

**Files:**
- Create: `src/jevplays/dashboard/__init__.py` (empty), `src/jevplays/dashboard/events.py`, `src/jevplays/dashboard/server.py`, `src/jevplays/dashboard/static/index.html`, `src/jevplays/dashboard/static/app.js`, `src/jevplays/dashboard/static/styles.css`
- Test: `tests/test_events.py`, `tests/test_server.py`

**Interfaces:**
- Consumes: `GameState.to_dict()`.
- Produces: `frame_event(jpeg: bytes) -> dict`, `state_event(state: GameState) -> dict`, `status_event(status: str, message: str = "") -> dict`, `encode(event: dict) -> str`; `class Broadcaster` with `async publish(event: dict)`, `async connect(ws)`, `disconnect(ws)`, `latest: dict[str, dict]` (last event per type, replayed to new clients); `create_app(broadcaster) -> Starlette`; `async serve(app, host="127.0.0.1", port=8765) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_events.py
import base64
import json

from jevplays.dashboard.events import encode, frame_event, state_event, status_event
from jevplays.state.snapshot import snapshot
from tests.support import FakeEmulator


def test_frame_event_carries_base64_jpeg():
    ev = frame_event(b"\xff\xd8abc")
    assert ev["type"] == "frame"
    assert base64.b64decode(ev["jpeg"]) == b"\xff\xd8abc"


def test_state_event_wraps_the_state_dict():
    ev = state_event(snapshot(FakeEmulator()))
    assert ev["type"] == "state"
    assert ev["state"]["mode"] == "overworld"


def test_status_event_and_encode_round_trip():
    ev = status_event("running", "walking the intro")
    assert json.loads(encode(ev)) == {"type": "status", "status": "running", "message": "walking the intro"}
```

```python
# tests/test_server.py
import asyncio
import json

from starlette.testclient import TestClient

from jevplays.dashboard.events import status_event
from jevplays.dashboard.server import Broadcaster, create_app


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(text)


def test_broadcaster_sends_to_every_client_and_remembers_the_latest_per_type():
    async def scenario():
        bc = Broadcaster()
        a, b = FakeSocket(), FakeSocket()
        await bc.connect(a)
        await bc.publish(status_event("running"))
        await bc.publish(status_event("paused"))
        await bc.connect(b)  # late joiner gets the latest status on connect
        return bc, a, b

    bc, a, b = asyncio.run(scenario())
    assert [json.loads(m)["status"] for m in a.sent] == ["running", "paused"]
    assert [json.loads(m)["status"] for m in b.sent] == ["paused"]
    assert bc.latest["status"]["status"] == "paused"


def test_broadcaster_drops_a_client_whose_send_fails():
    class Broken(FakeSocket):
        async def send_text(self, text: str) -> None:
            raise RuntimeError("gone")

    async def scenario():
        bc = Broadcaster()
        await bc.connect(Broken())
        await bc.publish(status_event("running"))
        return bc

    bc = asyncio.run(scenario())
    assert bc.clients == set()


def test_page_and_static_files_are_served():
    client = TestClient(create_app(Broadcaster()))
    page = client.get("/")
    assert page.status_code == 200
    assert "Jev plays" in page.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200


def test_websocket_receives_the_latest_events_on_connect():
    bc = Broadcaster()
    bc.latest["status"] = status_event("running", "hello")
    client = TestClient(create_app(bc))
    with client.websocket_connect("/ws") as ws:
        first = json.loads(ws.receive_text())
    assert first == {"type": "status", "status": "running", "message": "hello"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_events.py tests/test_server.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'jevplays.dashboard'`

- [ ] **Step 3: Write the implementation**

```python
# src/jevplays/dashboard/events.py
"""The messages the loop pushes to the page. Each is a JSON object with a `type`."""

import base64
import json

from jevplays.state.snapshot import GameState


def frame_event(jpeg: bytes) -> dict:
    return {"type": "frame", "jpeg": base64.b64encode(jpeg).decode("ascii")}


def state_event(state: GameState) -> dict:
    return {"type": "state", "state": state.to_dict()}


def status_event(status: str, message: str = "") -> dict:
    """status is one of running, waiting_for_api, paused, stopped."""
    return {"type": "status", "status": status, "message": message}


def encode(event: dict) -> str:
    return json.dumps(event, separators=(",", ":"))
```

```python
# src/jevplays/dashboard/server.py
"""A Starlette app: the static page, and a websocket that fans events out to every open tab."""

from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.responses import FileResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from jevplays.dashboard.events import encode

STATIC = Path(__file__).parent / "static"


class Broadcaster:
    """Holds the open sockets and the last event of each type, so a new tab is current at once."""

    def __init__(self) -> None:
        self.clients: set = set()
        self.latest: dict[str, dict] = {}

    async def connect(self, ws) -> None:
        self.clients.add(ws)
        for event in self.latest.values():
            await self._send(ws, event)

    def disconnect(self, ws) -> None:
        self.clients.discard(ws)

    async def publish(self, event: dict) -> None:
        self.latest[event["type"]] = event
        for ws in list(self.clients):
            await self._send(ws, event)

    async def _send(self, ws, event: dict) -> None:
        try:
            await ws.send_text(encode(event))
        except Exception:
            self.disconnect(ws)


def create_app(broadcaster: Broadcaster) -> Starlette:
    async def index(request):
        return FileResponse(STATIC / "index.html")

    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        await broadcaster.connect(ws)
        try:
            while True:
                await ws.receive_text()  # the page never sends; this only notices the close
        except WebSocketDisconnect:
            broadcaster.disconnect(ws)

    return Starlette(
        routes=[
            Route("/", index),
            WebSocketRoute("/ws", ws_endpoint),
            Mount("/static", StaticFiles(directory=STATIC), name="static"),
        ]
    )


async def serve(app: Starlette, host: str = "127.0.0.1", port: int = 8765) -> None:
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    await uvicorn.Server(config).serve()
```

`src/jevplays/dashboard/static/index.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Jev plays Pokémon</title>
  <link rel="stylesheet" href="/static/styles.css">
</head>
<body>
  <header>
    <h1>Jev plays Pokémon</h1>
    <span id="status" class="status" data-status="stopped">stopped</span>
  </header>
  <main>
    <section class="screen">
      <img id="screen" width="640" height="576" alt="Game screen">
    </section>
    <section class="panel">
      <h2>State</h2>
      <dl id="summary">
        <dt>Mode</dt><dd id="mode">–</dd>
        <dt>Map</dt><dd id="map">–</dd>
        <dt>Text</dt><dd id="text">–</dd>
        <dt>Menu</dt><dd id="menu">–</dd>
      </dl>
      <h2>Raw</h2>
      <pre id="state">waiting for the first snapshot…</pre>
    </section>
  </main>
  <script type="module" src="/static/app.js"></script>
</body>
</html>
```

`src/jevplays/dashboard/static/app.js`:

```js
// Milestone 1: show the screen and the raw state. The decision panel arrives with milestone 2.
const screen = document.getElementById("screen");
const status = document.getElementById("status");
const raw = document.getElementById("state");
const fields = {
  mode: document.getElementById("mode"),
  map: document.getElementById("map"),
  text: document.getElementById("text"),
  menu: document.getElementById("menu"),
};

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (msg) => {
    const event = JSON.parse(msg.data);
    if (event.type === "frame") {
      screen.src = `data:image/jpeg;base64,${event.jpeg}`;
    } else if (event.type === "state") {
      const s = event.state;
      fields.mode.textContent = s.mode;
      fields.map.textContent = `${s.map} (${s.tile[0]}, ${s.tile[1]})`;
      fields.text.textContent = s.text || "–";
      fields.menu.textContent = s.menu_items.length
        ? s.menu_items.map((item, i) => (i === s.cursor ? `▶${item}` : item)).join("  ")
        : "–";
      raw.textContent = JSON.stringify(s, null, 2);
    } else if (event.type === "status") {
      status.textContent = event.message ? `${event.status}: ${event.message}` : event.status;
      status.dataset.status = event.status;
    }
  };
  ws.onclose = () => {
    status.textContent = "disconnected, retrying…";
    status.dataset.status = "stopped";
    setTimeout(connect, 1000);
  };
}

connect();
```

`src/jevplays/dashboard/static/styles.css`:

```css
:root {
  --bg: #0f1115;
  --panel: #181b22;
  --text: #e6e6e6;
  --muted: #8b93a1;
  --accent: #7bd88f;
  --warn: #f2c94c;
  --stop: #eb5757;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 15px/1.4 ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-bottom: 1px solid #262a33;
}
h1 { font-size: 18px; margin: 0; }
h2 { font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; margin: 16px 0 8px; }
.status { padding: 4px 10px; border-radius: 999px; background: #262a33; font-size: 13px; }
.status[data-status="running"] { background: var(--accent); color: #0f1115; }
.status[data-status="waiting_for_api"], .status[data-status="paused"] { background: var(--warn); color: #0f1115; }
.status[data-status="stopped"] { background: var(--stop); color: #0f1115; }
main { display: grid; grid-template-columns: 640px 1fr; gap: 20px; padding: 20px; }
.screen img { image-rendering: pixelated; background: #000; display: block; }
.panel { background: var(--panel); border-radius: 8px; padding: 4px 16px 16px; min-width: 0; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: 6px 14px; margin: 0; }
dt { color: var(--muted); }
dd { margin: 0; overflow-wrap: anywhere; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; color: var(--muted); font-size: 13px; }
@media (max-width: 1000px) {
  main { grid-template-columns: 1fr; }
  .screen img { width: 100%; height: auto; }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_events.py tests/test_server.py -q`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/dashboard tests/test_events.py tests/test_server.py
git commit -m "feat(dashboard): websocket broadcaster and a page that shows the screen and state"
```

---

### Task 9: The loop and the CLI

**Files:**
- Create: `src/jevplays/loop.py`, `src/jevplays/cli.py`
- Test: `tests/test_loop.py`, `tests/rom/test_cli.py`

**Interfaces:**
- Consumes: `snapshot`, `Mode`, `frame_event`, `state_event`, `status_event`, `Broadcaster`, `create_app`, `serve`, `Emulator`, `walk_intro`.
- Produces: `@dataclass class LoopConfig(fps: float = 15.0, idle_frames: int = 30, paced: bool = True)`; `class Loop(emu, broadcaster, config=LoopConfig())` with `async run(max_iterations: int | None = None)` and `advance(state: GameState) -> int`; `main(argv: list[str] | None = None) -> int` in `cli.py` with subcommands `run` and `state`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_loop.py
import asyncio

from jevplays.loop import Loop, LoopConfig
from jevplays.state.modes import Mode
from jevplays.state.snapshot import snapshot
from tests.support import FakeEmulator

DIALOG = [""] * 12 + ["····················", "·                  ·", "·Hello there!      ·", "·                  ·", "·Welcome to the   ▼·"]


class RecordingBroadcaster:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish(self, event: dict) -> None:
        self.events.append(event)


def run(loop: Loop, iterations: int) -> None:
    asyncio.run(loop.run(max_iterations=iterations))


def test_publishes_state_then_frame_on_the_first_iteration():
    emu, bc = FakeEmulator(), RecordingBroadcaster()
    run(Loop(emu, bc, LoopConfig(paced=False)), 1)
    assert [e["type"] for e in bc.events][:2] == ["state", "frame"]


def test_state_is_published_only_when_it_changes():
    emu, bc = FakeEmulator(), RecordingBroadcaster()
    run(Loop(emu, bc, LoopConfig(paced=False, fps=1000)), 3)
    assert sum(e["type"] == "state" for e in bc.events) == 1


def test_frames_are_rate_limited():
    emu, bc = FakeEmulator(), RecordingBroadcaster()
    run(Loop(emu, bc, LoopConfig(paced=False, fps=0.001)), 5)  # one frame per 1000 s
    assert sum(e["type"] == "frame" for e in bc.events) == 1


def test_dialog_gets_an_a_press_and_overworld_idles():
    emu = FakeEmulator()
    loop = Loop(emu, RecordingBroadcaster(), LoopConfig(paced=False, idle_frames=7))
    emu.set_rows(DIALOG)
    assert snapshot(emu).mode is Mode.DIALOG
    loop.advance(snapshot(emu))
    assert emu.presses == ["a"]
    emu.set_rows([])
    before = emu.frames
    assert loop.advance(snapshot(emu)) == 7
    assert emu.frames == before + 7
    assert emu.presses == ["a"]
```

```python
# tests/rom/test_cli.py
import json

from jevplays.cli import main


def test_state_command_prints_the_snapshot_as_json(rom, state_path, capsys, monkeypatch):
    monkeypatch.setenv("JEVPLAYS_ROM", str(rom))
    assert main(["state", str(state_path("overworld"))]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "overworld"
    assert out["map"] == "Red's House 2F"


def test_state_command_without_rom_is_an_error(monkeypatch, capsys):
    monkeypatch.delenv("JEVPLAYS_ROM", raising=False)
    assert main(["state", "whatever.state"]) == 2
    assert "JEVPLAYS_ROM" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_loop.py tests/rom/test_cli.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'jevplays.loop'`

- [ ] **Step 3: Write the implementation**

```python
# src/jevplays/loop.py
"""The orchestrator: snapshot, publish, advance, repeat.

Milestone 1 advances the game without deciding anything: dialog and battle text get an A,
transitions get a wait, and every decision point (overworld, menu, prompt, battle menu) idles.
Milestone 2 replaces the idle branches with a request to Jev; the publish side stays as is.

Pacing: the emulator runs as fast as it can, so the loop sleeps to keep emulated frames in step
with wall-clock time at 60 frames per second. That is what makes the dashboard watchable.
"""

import asyncio
from dataclasses import dataclass
from itertools import count
from time import monotonic

from jevplays.dashboard.events import frame_event, state_event
from jevplays.state.modes import Mode
from jevplays.state.snapshot import GameState, snapshot

FRAMES_PER_SECOND = 60


@dataclass
class LoopConfig:
    fps: float = 15.0
    """Dashboard frames per second, not emulator frames."""
    idle_frames: int = 30
    """How long to let the game run when nothing needs pressing."""
    paced: bool = True
    """Sleep so emulated time matches wall time. Off in tests."""


class Loop:
    def __init__(self, emu, broadcaster, config: LoopConfig | None = None) -> None:
        self.emu = emu
        self.broadcaster = broadcaster
        self.config = config or LoopConfig()

    def advance(self, state: GameState) -> int:
        """Move the game forward one step for the current mode. Returns emulated frames spent."""
        if state.mode in (Mode.DIALOG, Mode.BATTLE_WAIT):
            return self.emu.press("a", settle=30)
        if state.mode is Mode.TRANSITION:
            return self.emu.tick(30)
        return self.emu.tick(self.config.idle_frames)

    async def run(self, max_iterations: int | None = None) -> None:
        started = monotonic()
        emulated = 0
        last_frame_at = float("-inf")
        last_state: GameState | None = None
        for i in count():
            if max_iterations is not None and i >= max_iterations:
                return
            state = snapshot(self.emu)
            if state != last_state:
                await self.broadcaster.publish(state_event(state))
                last_state = state
            now = monotonic()
            if now - last_frame_at >= 1 / self.config.fps:
                await self.broadcaster.publish(frame_event(self.emu.frame_jpeg()))
                last_frame_at = now
            emulated += self.advance(state)
            if self.config.paced:
                due = started + emulated / FRAMES_PER_SECOND
                await asyncio.sleep(max(0.0, due - monotonic()))
            else:
                await asyncio.sleep(0)
```

```python
# src/jevplays/cli.py
"""`jevplays run` boots the game and serves the dashboard; `jevplays state` inspects a save."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def _rom_from_env() -> Path | None:
    path = os.environ.get("JEVPLAYS_ROM")
    return Path(path) if path else None


def cmd_state(args: argparse.Namespace) -> int:
    rom = args.rom or _rom_from_env()
    if rom is None:
        print("no ROM: pass --rom or set JEVPLAYS_ROM", file=sys.stderr)
        return 2
    # Imported after the ROM check so a run without a ROM (CI) never loads PyBoy and SDL.
    from jevplays.emulator.pyboy import Emulator
    from jevplays.state.snapshot import snapshot

    with Emulator(rom) as emu:
        emu.load(args.state)
        print(json.dumps(snapshot(emu).to_dict(), indent=2, ensure_ascii=False))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    rom = args.rom or _rom_from_env()
    if rom is None:
        print("no ROM: pass --rom or set JEVPLAYS_ROM", file=sys.stderr)
        return 2
    from jevplays.dashboard.events import status_event
    from jevplays.dashboard.server import Broadcaster, create_app, serve
    from jevplays.emulator.intro import walk_intro
    from jevplays.emulator.pyboy import Emulator
    from jevplays.loop import Loop, LoopConfig

    async def main_async() -> None:
        broadcaster = Broadcaster()
        server = asyncio.create_task(serve(create_app(broadcaster), port=args.port))
        print(f"dashboard: http://127.0.0.1:{args.port}", flush=True)
        with Emulator(rom) as emu:
            if args.state:
                await broadcaster.publish(status_event("running", f"loading {args.state}"))
                emu.load(args.state)
            else:
                await broadcaster.publish(status_event("running", "walking the intro"))
                walk_intro(emu)
            await broadcaster.publish(status_event("running", "idle at the first decision point"))
            loop = Loop(emu, broadcaster, LoopConfig(paced=not args.unpaced))
            try:
                await loop.run()
            finally:
                await broadcaster.publish(status_event("stopped"))
                server.cancel()

    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jevplays", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="boot the game, walk the intro, serve the dashboard")
    run.add_argument("--rom", type=Path, help="Pokémon Red/Blue ROM (default: $JEVPLAYS_ROM)")
    run.add_argument("--state", type=Path, help="start from this save state instead of the intro")
    run.add_argument("--port", type=int, default=8765)
    run.add_argument("--unpaced", action="store_true", help="run the emulator as fast as it can")
    run.set_defaults(func=cmd_run)

    state = sub.add_parser("state", help="print the GameState parsed from a save state")
    state.add_argument("state", type=Path)
    state.add_argument("--rom", type=Path, help="Pokémon Red/Blue ROM (default: $JEVPLAYS_ROM)")
    state.set_defaults(func=cmd_state)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_loop.py tests/rom/test_cli.py -q`
Expected: `6 passed`

- [ ] **Step 5: Run it for real and look at the page**

Run in the background: `uv run jevplays run --port 8765`
Expected on stdout: `dashboard: http://127.0.0.1:8765`. Open the URL: the status pill reads "running: idle at the first decision point", the screen shows Red's bedroom, Mode reads `overworld`, Map reads `Red's House 2F (3, 7)`. Then run `uv run jevplays run --state states/dialog.state`: the screen shows Oak, Mode reads `dialog` briefly, then the loop presses through the speech (Mode flips between `dialog` and `menu` at the name screens, where it idles: the name menu is a decision point). Stop both with Ctrl-C.

Capture one screenshot of the bedroom page for the PR description and note where it is saved.

- [ ] **Step 6: Commit**

```bash
git add src/jevplays/loop.py src/jevplays/cli.py tests/test_loop.py tests/rom/test_cli.py
git commit -m "feat(loop): pace the emulator, publish state and frames, and expose run/state commands"
```

---

### Task 10: Full check, docs, and the pull request

**Files:**
- Modify: `README.md` (only if a command changed during implementation), `CLAUDE.md` (same)

- [ ] **Step 1: Run the whole thing the way CI will**

```bash
mise run check
JEVPLAYS_ROM= uv run pytest -q     # the CI shape: every ROM test skips, everything else passes
uv run pytest -q                   # the developer shape: everything passes
```

Expected: `hk check --all` clean; the first pytest shows the `tests/rom/` count as skipped and zero failures; the second shows zero skipped (or only the ones whose state is missing) and zero failures.

- [ ] **Step 2: Confirm nothing game-derived is tracked**

```bash
git ls-files | grep -E '\.(gb|gbc|state|ram)$|^roms/|^states/|^runs/|mise\.local' ; echo "exit=$?"
```

Expected: no output and `exit=1`.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin tylervick/milestone-1-harness
gh pr create --title "Milestone 1: emulator harness, GameState, and dashboard" --body "$(cat <<'EOF'
Implements milestone 1 of docs/superpowers/specs/2026-09-20-jevplays-design.md.

- Headless PyBoy wrapper with ticks, presses, JPEG frames, save/load.
- Intro walker driven by the game's screen buffer (92 iterations, 0.2 s).
- `GameState` snapshot: mode detection (overworld, dialog, prompt, menu, battle, transition), map name, tile, money, badges, menu items, dialog text.
- Dashboard: websocket broadcaster and a page showing the screen and raw state.
- `jevplays run` and `jevplays state`.
- Tooling copied from graphghan: mise, hk, Renovate, SHA-pinned CI. ROM tests skip without a ROM.

No TypeSafe calls yet; that is milestone 2.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

If the GitHub repository does not exist yet, create it first with `gh repo create tylervick/jevplays --public --source . --push` (that pushes `main`), then push the design branch and this branch, and open the PR against `main` with the design branch merged first or included in this PR.

---

## Self-review

**Spec coverage (sections named in the header):** section 4 repository and tooling: Task 1. Section 5 emulator layer: Tasks 2, 3, 4 (the intro walker in Task 5 replaces the unreleased PyBoy `start_game`). Section 6 state and modes: Tasks 6 and 7, with the party, moves, bag summary, and event flags explicitly deferred to milestone 2 in the header. Section 7 loop: Task 9, with the decision branches idling as milestone 1 requires. Section 10 dashboard: Task 8 covers `frame`, `state`, `status`; the `decision` event and the bars arrive with milestone 2 alongside the first Decision. Section 13 testing: unit and ROM split in every task, `tests/rom/conftest.py` skips, `Scripts/make-states.py` produces the per-mode states. Section 14 milestone 1 deliverables: all present, including `jevplays state` and a `run` that walks the intro.

**Placeholder scan:** every code step carries its code; every test step names its command and expected result. The one conditional instruction (create the GitHub repo if missing) names the exact command.

**Type consistency:** `Emulator.press/tick` return `int` and `FakeEmulator` matches; `snapshot()` needs only `mem` and `tilemap()`, and both `Emulator` and `FakeEmulator` provide them; `Loop.advance` uses `press(..., settle=30)` which both implement; `menu_items(rows, mode)` and `dialog_text(rows)` are imported by name in the tests from `jevplays.state.snapshot`; `rows_from`, `tilemap_bytes`, `write_tilemap`, `FakeMemory`, `FakeEmulator` all live in `tests/support.py` and are imported as `from tests.support import ...`, which works because `tests/__init__.py` and `tests/rom/__init__.py` exist.
