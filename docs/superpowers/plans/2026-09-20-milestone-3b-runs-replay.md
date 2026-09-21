# Milestone 3b: Run Logging, Resume, Replay, and the Stream Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every `jevplays run` leaves a `runs/<dir>/` behind that can be resumed from its last checkpoint and replayed on the dashboard without an emulator or an API key, and the dashboard gets its fixed 1920x1080 stream arrangement.

**Architecture:** A small `runlog.RunDir` owns the on-disk shape (`run.json`, `decisions.jsonl`, `checkpoint-<n>.state`). The loop gets an optional `run_dir` and writes through it from the one place every decision already passes (`Loop._record`); checkpoints fall out of the decision count. `jevplays run --resume` opens an existing dir, loads the newest checkpoint, and keeps appending. `dashboard/replay.py` reads the log back and pushes the same `decision` events through the existing `Broadcaster`, so the page code does not know whether a run is live or replayed. The stream layout is a `body[data-layout="stream"]` stylesheet branch selected from the query string; no new events.

**Tech Stack:** Python 3.12, Starlette/uvicorn (already), PyBoy save states (already), plain ES modules + CSS.

**Spec:** `docs/superpowers/specs/2026-09-20-jevplays-design.md`, sections 10 (replay, `?layout=stream`), 11 (runs, logs, resume), 12 (fatal errors resume from a checkpoint), 13 (the `replay` end-to-end test), 14 (milestone 3b).

**Branch:** `tylervick/milestone-3b-runs-replay`, created from the milestone 3a head (`tylervick/milestone-3-goals`, 92de07c) because the loop it instruments lives there. The PR targets `main` once PR #9 merges (rebase first); until then it may be opened against `tylervick/milestone-3-goals`.

## Global Constraints

- ruff: line length 110, `select = ["E", "F", "I", "B"]`, `ignore = ["E501"]`, target py312; `uv run ruff check src tests Scripts && uv run ruff format src tests Scripts` clean before every commit.
- `import pyboy` only inside `src/jevplays/emulator/pyboy.py`; `import typesafe_sdk` only in `src/jevplays/brain/client.py` (and `Scripts/record-fixtures.py`). `tests/test_imports.py` pins that `import jevplays.loop` and `import jevplays.cli` never import pyboy; the new modules must keep that true (no emulator imports at module scope).
- Never commit a ROM, `*.state`, `*.ram`, `runs/`, or `mise.local.toml` (all gitignored). Tests write runs under `tmp_path` only.
- Never edit an existing test to make it pass. Add tests; leave existing assertions alone.
- Jev never receives coordinates, raw numbers (levels excepted), or screenshots. Nothing in this milestone changes what Jev sees; `run.json` and the log are for people.
- The dashboard binds `127.0.0.1`; the page renders event data via `textContent` only.
- Spec 11 values, verbatim: run dir `runs/<YYYYMMDD-HHMMSS>/`; `run.json` holds the ROM hash, the model id from the first response, the start time, and the CLI flags; `decisions.jsonl` is one Decision per line; `checkpoint-<n>.state` every `CHECKPOINT_EVERY` (25) decisions plus one at exit; `jevplays run --resume runs/<dir>` loads the last checkpoint and appends to the same log.
- Spec 10: `jevplays replay runs/<dir>` reads `decisions.jsonl` and pushes the same events with a delay; `?layout=stream` is a fixed 1920x1080 arrangement for OBS.
- Conventional commits; every commit body ends with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Unit tests: `env -u JEVPLAYS_ROM .venv/bin/python -m pytest -q`. ROM tests: `mise exec -- uv run pytest tests/rom -q` (states from `mise run states`). Full check: `mise run check`.

## File Structure

| File | Responsibility |
| --- | --- |
| `src/jevplays/runlog.py` (new) | `RunDir`: create/open a run directory, write `run.json`, append decisions, write and find checkpoints. No emulator import; takes any object with `.save(path)`. |
| `src/jevplays/loop.py` (modify) | `Loop(..., run_dir=None)`; `_record` appends to the log; `_maybe_checkpoint`; `checkpoint()` for the exit checkpoint; `decision_count` (log length + this session). |
| `src/jevplays/cli.py` (modify) | `run` creates or resumes a `RunDir` (`--runs-dir`, `--resume`, `--no-log`), prints the run path, checkpoints at exit; new `replay` subcommand. |
| `src/jevplays/dashboard/replay.py` (new) | `replay(run_dir, broadcaster, *, delay, limit)`: pushes `status` + `decision` events from the log. |
| `src/jevplays/dashboard/static/{index.html,app.js,styles.css}` (modify) | `?layout=stream` → `body[data-layout="stream"]`, a fixed 1920x1080 grid. |
| `tests/support.py` (modify) | `FakeEmulator.save(path)` writes deterministic bytes so checkpoints can be asserted without PyBoy. |
| `tests/test_runlog.py` (new), `tests/test_loop.py` (add), `tests/test_cli.py` (add), `tests/test_replay.py` (new), `tests/test_server.py` (add), `tests/rom/test_resume.py` (new) | Tests per task. |
| `README.md`, `CLAUDE.md` (modify) | Runs, resume, replay, stream layout. |

---

### Task 1: `RunDir` — the on-disk shape of a run

**Files:**
- Create: `src/jevplays/runlog.py`
- Modify: `tests/support.py` (add `FakeEmulator.save`)
- Test: `tests/test_runlog.py`

**Interfaces:**
- Consumes: `jevplays.brain.decision.Decision` (`to_dict()`), nothing else from the package.
- Produces: `CHECKPOINT_EVERY = 25`; `RUN_DIR_FORMAT = "%Y%m%d-%H%M%S"`; `class RunDir` with `path: Path`, `RunDir.create(root: Path, *, rom: Path | None, flags: dict, now: datetime | None = None) -> RunDir` (makes `root/<stamp>/`, writes `run.json`), `RunDir.open(path: Path) -> RunDir` (raises `FileNotFoundError` if `run.json` is missing), `info() -> dict` (the parsed `run.json`), `set_model(model: str) -> None` (writes `model` into `run.json` once; a second call with a different model appends to `models`), `mark_resumed(now=None) -> None` (appends an ISO timestamp to `resumed_at`), `append(decision: Decision) -> int` (writes one JSON line, returns the new line count), `count() -> int` (lines in `decisions.jsonl`, 0 when absent), `decisions() -> Iterator[dict]` (parsed lines), `checkpoint(emu, n: int) -> Path` (calls `emu.save(path)` on `checkpoint-<n>.state`, returns the path), `last_checkpoint() -> Path | None` (the highest `<n>`), `rom_sha256(path: Path) -> str` (module function).
- `tests/support.FakeEmulator.save(path)` writes `b"FAKE-STATE:" + str(self.saves).encode()` and increments `self.saves` (an int starting at 0), so a test can tell checkpoints apart.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_runlog.py
import json
from datetime import datetime

from jevplays.brain.decision import Decision, PromptAction
from jevplays.runlog import CHECKPOINT_EVERY, RunDir, rom_sha256
from tests.support import FakeEmulator


def decision(i: int) -> Decision:
    return Decision(
        id=f"d{i}", ts=1000.0 + i, kind="prompt", state_summary={"prompt": "Yes?"},
        questions={}, answers={}, action="answer YES", action_value=PromptAction(yes=True),
    )


def test_create_writes_run_json_with_the_rom_hash_flags_and_start_time(tmp_path):
    rom = tmp_path / "game.gb"
    rom.write_bytes(b"not a real rom")
    run = RunDir.create(tmp_path / "runs", rom=rom, flags={"state": "route1.state", "unpaced": True},
                        now=datetime(2026, 9, 20, 13, 45, 7))
    assert run.path == tmp_path / "runs" / "20260920-134507"
    info = json.loads((run.path / "run.json").read_text())
    assert info["rom_sha256"] == rom_sha256(rom)
    assert info["flags"] == {"state": "route1.state", "unpaced": True}
    assert info["started_at"] == "2026-09-20T13:45:07"
    assert info["model"] == "" and info["checkpoint_every"] == CHECKPOINT_EVERY
    assert run.count() == 0 and run.last_checkpoint() is None


def test_append_writes_one_decision_per_line_and_reads_them_back(tmp_path):
    run = RunDir.create(tmp_path, rom=None, flags={})
    assert run.append(decision(1)) == 1
    assert run.append(decision(2)) == 2
    lines = (run.path / "decisions.jsonl").read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["id"] == "d1"
    assert [d["action"] for d in run.decisions()] == ["answer YES", "answer YES"]
    assert "action_value" not in json.loads(lines[0])


def test_open_resumes_the_same_directory_and_counts_existing_lines(tmp_path):
    run = RunDir.create(tmp_path, rom=None, flags={})
    run.append(decision(1))
    again = RunDir.open(run.path)
    assert again.count() == 1
    again.append(decision(2))
    assert RunDir.open(run.path).count() == 2


def test_open_a_directory_without_run_json_fails_loudly(tmp_path):
    try:
        RunDir.open(tmp_path)
    except FileNotFoundError as error:
        assert "run.json" in str(error)
    else:
        raise AssertionError("expected FileNotFoundError")


def test_checkpoints_are_numbered_and_the_newest_wins(tmp_path):
    run = RunDir.create(tmp_path, rom=None, flags={})
    emu = FakeEmulator()
    assert run.checkpoint(emu, 25).name == "checkpoint-25.state"
    run.checkpoint(emu, 100)
    run.checkpoint(emu, 50)
    assert run.last_checkpoint().name == "checkpoint-100.state"
    assert (run.path / "checkpoint-25.state").read_bytes() == b"FAKE-STATE:0"
    assert (run.path / "checkpoint-50.state").read_bytes() == b"FAKE-STATE:2"


def test_model_is_recorded_once_and_a_change_is_kept_as_history(tmp_path):
    run = RunDir.create(tmp_path, rom=None, flags={})
    run.set_model("jev-1.13.0")
    run.set_model("jev-1.13.0")
    run.set_model("jev-1.14.0")
    info = run.info()
    assert info["model"] == "jev-1.13.0" and info["models"] == ["jev-1.13.0", "jev-1.14.0"]


def test_mark_resumed_appends_a_timestamp(tmp_path):
    run = RunDir.create(tmp_path, rom=None, flags={})
    run.mark_resumed(now=datetime(2026, 9, 21, 8, 0, 0))
    assert run.info()["resumed_at"] == ["2026-09-21T08:00:00"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `env -u JEVPLAYS_ROM .venv/bin/python -m pytest -q tests/test_runlog.py`
Expected: FAIL with `ModuleNotFoundError: jevplays.runlog`.

- [ ] **Step 3: Implement `runlog.py` and the fake's `save`**

```python
# src/jevplays/runlog.py
"""One run on disk: `runs/<stamp>/` with run.json, decisions.jsonl, and numbered checkpoints.

The loop writes through a RunDir; `jevplays run --resume` opens one and continues it; `jevplays
replay` reads the log back. Nothing here imports the emulator: `checkpoint` takes any object with
a `save(path)` method, which is what the real Emulator and the test fake both offer.
"""

import hashlib
import json
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from jevplays.brain.decision import Decision

CHECKPOINT_EVERY = 25
"""Decisions between checkpoints. Spec 11."""
RUN_DIR_FORMAT = "%Y%m%d-%H%M%S"
_CHECKPOINT = re.compile(r"^checkpoint-(\d+)\.state$")


def rom_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RunDir:
    def __init__(self, path: Path) -> None:
        self.path = path

    # -- creation and opening -----------------------------------------------------------

    @classmethod
    def create(cls, root: Path, *, rom: Path | None, flags: dict, now: datetime | None = None) -> "RunDir":
        now = now or datetime.now()
        path = root / now.strftime(RUN_DIR_FORMAT)
        path.mkdir(parents=True, exist_ok=False)
        run = cls(path)
        run._write_info(
            {
                "rom_sha256": rom_sha256(rom) if rom is not None else "",
                "started_at": now.isoformat(timespec="seconds"),
                "flags": flags,
                "model": "",
                "models": [],
                "resumed_at": [],
                "checkpoint_every": CHECKPOINT_EVERY,
            }
        )
        return run

    @classmethod
    def open(cls, path: Path) -> "RunDir":
        if not (path / "run.json").is_file():
            raise FileNotFoundError(f"{path / 'run.json'} is missing; not a run directory")
        return cls(path)

    # -- run.json -----------------------------------------------------------------------

    def info(self) -> dict:
        return json.loads((self.path / "run.json").read_text())

    def _write_info(self, info: dict) -> None:
        (self.path / "run.json").write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n")

    def set_model(self, model: str) -> None:
        info = self.info()
        if not info["model"]:
            info["model"] = model
        if model not in info["models"]:
            info["models"].append(model)
        self._write_info(info)

    def mark_resumed(self, now: datetime | None = None) -> None:
        info = self.info()
        info["resumed_at"].append((now or datetime.now()).isoformat(timespec="seconds"))
        self._write_info(info)

    # -- decisions.jsonl ----------------------------------------------------------------

    @property
    def log_path(self) -> Path:
        return self.path / "decisions.jsonl"

    def append(self, decision: Decision) -> int:
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(decision.to_dict(), ensure_ascii=False) + "\n")
        return self.count()

    def count(self) -> int:
        if not self.log_path.is_file():
            return 0
        with open(self.log_path, "rb") as f:
            return sum(1 for line in f if line.strip())

    def decisions(self) -> Iterator[dict]:
        if not self.log_path.is_file():
            return
        with open(self.log_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)

    # -- checkpoints --------------------------------------------------------------------

    def checkpoint(self, emu, n: int) -> Path:
        path = self.path / f"checkpoint-{n}.state"
        emu.save(path)
        return path

    def last_checkpoint(self) -> Path | None:
        best: tuple[int, Path] | None = None
        for candidate in self.path.iterdir():
            m = _CHECKPOINT.match(candidate.name)
            if m and (best is None or int(m.group(1)) > best[0]):
                best = (int(m.group(1)), candidate)
        return best[1] if best else None
```

In `tests/support.py`, inside `FakeEmulator.__init__` add `self.saves = 0`, and add:

```python
    def save(self, path) -> None:
        """Stand-in for Emulator.save: distinct bytes per call so checkpoints can be told apart."""
        Path(path).write_bytes(b"FAKE-STATE:" + str(self.saves).encode())
        self.saves += 1
```

(`from pathlib import Path` at the top of `support.py` if it is not there.)

- [ ] **Step 4: Run the tests**

Run: `env -u JEVPLAYS_ROM .venv/bin/python -m pytest -q tests/test_runlog.py tests/test_imports.py`
Expected: all pass (the import guard proves `runlog` pulls in no emulator).

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/runlog.py tests/test_runlog.py tests/support.py
git commit -m "feat(runs): RunDir writes run.json, the decision log, and numbered checkpoints"
```

---

### Task 2: The loop writes through the run dir

**Files:**
- Modify: `src/jevplays/loop.py` (`Loop.__init__`, `_record`, new `_maybe_checkpoint`, `checkpoint`, `decision_count`)
- Test: `tests/test_loop.py` (add)

**Interfaces:**
- Consumes: `runlog.RunDir` (`append`, `count`, `checkpoint`, `set_model`), `runlog.CHECKPOINT_EVERY`.
- Produces: `Loop(emu, broadcaster, config=None, brain=None, run_dir: RunDir | None = None)`; `Loop.decision_count -> int` (decisions in the log before this session plus those made in it; with no run dir, `len(self.decisions)`); `Loop.checkpoint() -> Path | None` (writes `checkpoint-<decision_count>.state` through the run dir, publishes `status_event("running", "checkpoint <n>")`, returns the path; None without a run dir). Every recorded decision (Jev's and `local_decision`s alike) is appended to the log in `_record`; after the append, when `decision_count % CHECKPOINT_EVERY == 0`, a checkpoint is written. The first decision with a non-empty `model` calls `run_dir.set_model`.

- [ ] **Step 1: Failing tests** (append to `tests/test_loop.py`; reuse its `FakeBrain`, `RecordingBroadcaster`, `run`, and the prompt-state helper the existing PROMPT tests use)

```python
def test_every_decision_is_appended_to_the_run_log(tmp_path):
    from jevplays.runlog import RunDir

    run_dir = RunDir.create(tmp_path, rom=None, flags={})
    emu = prompt_emulator("Take CHARMANDER?")  # the helper the PROMPT tests use; keep its name
    loop = Loop(emu, RecordingBroadcaster(), LoopConfig(paced=False), brain=None, run_dir=run_dir)
    run(loop, 1)
    assert run_dir.count() == 1
    assert next(run_dir.decisions())["kind"] == "prompt"
    assert loop.decision_count == 1


def test_a_checkpoint_is_written_every_checkpoint_every_decisions(tmp_path):
    from jevplays.runlog import CHECKPOINT_EVERY, RunDir

    run_dir = RunDir.create(tmp_path, rom=None, flags={})
    emu = prompt_emulator("Take CHARMANDER?")
    emu.step_effects = {}  # the fake never leaves the prompt, so every iteration decides again
    loop = Loop(emu, RecordingBroadcaster(), LoopConfig(paced=False), brain=None, run_dir=run_dir)
    run(loop, CHECKPOINT_EVERY * 2 + 1)
    assert sorted(p.name for p in run_dir.path.glob("checkpoint-*.state")) == [
        f"checkpoint-{CHECKPOINT_EVERY * 2}.state",
        f"checkpoint-{CHECKPOINT_EVERY}.state",
    ]


def test_numbering_continues_from_the_log_when_resumed(tmp_path):
    from jevplays.runlog import CHECKPOINT_EVERY, RunDir

    run_dir = RunDir.create(tmp_path, rom=None, flags={})
    for i in range(CHECKPOINT_EVERY - 1):
        run_dir.append(local_decision("prompt", {}, PromptAction(yes=True), "seed"))
    emu = prompt_emulator("Take CHARMANDER?")
    loop = Loop(emu, RecordingBroadcaster(), LoopConfig(paced=False), brain=None, run_dir=run_dir)
    run(loop, 1)
    assert loop.decision_count == CHECKPOINT_EVERY
    assert (run_dir.path / f"checkpoint-{CHECKPOINT_EVERY}.state").is_file()


def test_the_first_model_id_lands_in_run_json(tmp_path):
    from jevplays.runlog import RunDir

    run_dir = RunDir.create(tmp_path, rom=None, flags={})
    emu = prompt_emulator("Take CHARMANDER?")
    brain = FakeBrain(response={"model": "jev-1.13.0", "usage": {"input_tokens": 3},
                                "choices": {}, "nouls": {"prompt": {"noul": 0.9}}})
    loop = Loop(emu, RecordingBroadcaster(), LoopConfig(paced=False), brain=brain, run_dir=run_dir)
    run(loop, 1)
    assert run_dir.info()["model"] == "jev-1.13.0"


def test_checkpoint_on_demand_names_the_current_count_and_says_so(tmp_path):
    from jevplays.runlog import RunDir

    run_dir = RunDir.create(tmp_path, rom=None, flags={})
    bc = RecordingBroadcaster()
    loop = Loop(FakeEmulator(), bc, LoopConfig(paced=False), run_dir=run_dir)
    path = asyncio.run(loop.checkpoint())
    assert path.name == "checkpoint-0.state"
    assert any(e["type"] == "status" and e["message"] == "checkpoint 0" for e in bc.events)


def test_without_a_run_dir_nothing_is_written_and_checkpoint_is_a_no_op():
    loop = Loop(FakeEmulator(), RecordingBroadcaster(), LoopConfig(paced=False))
    assert asyncio.run(loop.checkpoint()) is None
```

If `tests/test_loop.py` has no `prompt_emulator` helper, add one next to the existing PROMPT test that builds a `FakeEmulator` in `Mode.PROMPT` with the given text (copy how that test sets rows and the YES/NO box), and import `local_decision` and `PromptAction` at the top.

- [ ] **Step 2: Run to verify they fail**

Run: `env -u JEVPLAYS_ROM .venv/bin/python -m pytest -q tests/test_loop.py -k "run_log or checkpoint or model_id or resumed"`
Expected: FAIL (`unexpected keyword argument 'run_dir'`).

- [ ] **Step 3: Implement**

In `loop.py`: `from jevplays.runlog import CHECKPOINT_EVERY, RunDir` (a module import; `runlog` has no emulator import). Constructor gains `run_dir: RunDir | None = None`, stored as `self.run_dir`, plus `self._logged_before = run_dir.count() if run_dir is not None else 0`.

```python
    @property
    def decision_count(self) -> int:
        """Decisions on record for this run: what the log already held plus this session's."""
        return self._logged_before + len(self.decisions)

    async def _record(self, decision: Decision) -> None:
        self.decisions.append(decision)
        if self.run_dir is not None:
            self.run_dir.append(decision)
            if decision.model:
                self.run_dir.set_model(decision.model)
        await self.broadcaster.publish(decision_event(decision))
        await self._maybe_checkpoint()

    async def _maybe_checkpoint(self) -> None:
        if self.run_dir is not None and self.decision_count % CHECKPOINT_EVERY == 0:
            await self.checkpoint()

    async def checkpoint(self):
        """Save the game where it stands, named by the decision count, so `--resume` can pick
        it up. None without a run dir."""
        if self.run_dir is None:
            return None
        path = self.run_dir.checkpoint(self.emu, self.decision_count)
        await self.broadcaster.publish(status_event("running", f"checkpoint {self.decision_count}"))
        return path
```

`set_model` re-reads and rewrites `run.json` on every decision that carries a model; that is one small file per decision and Jev decisions come a few per second at most. Keep it simple; do not cache.

- [ ] **Step 4: Run the whole unit suite**

Run: `env -u JEVPLAYS_ROM .venv/bin/python -m pytest -q`
Expected: all pass (existing loop tests are unaffected: `run_dir` defaults to None).

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/loop.py tests/test_loop.py
git commit -m "feat(loop): log every decision to the run dir and checkpoint every 25"
```

---

### Task 3: `jevplays run` creates or resumes a run; a ROM test resumes from a checkpoint

**Files:**
- Modify: `src/jevplays/cli.py` (`cmd_run`, `build_parser`)
- Test: `tests/test_cli.py` (add), `tests/rom/test_resume.py` (new)

**Interfaces:**
- Consumes: `RunDir.create/open/last_checkpoint/mark_resumed`, `Loop(run_dir=...)`, `Loop.checkpoint()`.
- Produces: `run` flags `--runs-dir PATH` (default `runs`), `--resume RUN_DIR` (mutually exclusive with `--state`; opens the run, loads `last_checkpoint()`, errors with exit 2 and a message when there is none), `--no-log` (no run dir at all; for quick looks). `cmd_run` prints `run: <path>` right after the dashboard line, records `flags` as `{"state": str|None, "resume": str|None, "port": int, "unpaced": bool, "no_brain": bool, "battle_goal": str}`, and in the `finally` after `loop.run()` calls `await loop.checkpoint()` (the "one at exit") before publishing `stopped`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_cli.py (append)
def test_run_help_lists_the_run_dir_flags(capsys):
    import pytest

    with pytest.raises(SystemExit):
        main(["run", "--help"])
    out = capsys.readouterr().out
    assert "--runs-dir" in out and "--resume" in out and "--no-log" in out


def test_resume_without_a_checkpoint_is_an_error(monkeypatch, tmp_path, capsys):
    from jevplays.runlog import RunDir

    rom = tmp_path / "game.gb"
    rom.write_bytes(b"rom")
    monkeypatch.setenv("JEVPLAYS_ROM", str(rom))
    run = RunDir.create(tmp_path / "runs", rom=rom, flags={})
    assert main(["run", "--resume", str(run.path)]) == 2
    assert "checkpoint" in capsys.readouterr().err


def test_state_and_resume_together_are_rejected(capsys):
    import pytest

    with pytest.raises(SystemExit) as exc:
        main(["run", "--state", "a.state", "--resume", "runs/x"])
    assert exc.value.code == 2
```

```python
# tests/rom/test_resume.py
"""A run leaves checkpoints behind and a resumed run continues from the newest one."""

from jevplays.emulator import ram
from jevplays.emulator.pyboy import Emulator
from jevplays.loop import Loop, LoopConfig
from jevplays.runlog import CHECKPOINT_EVERY, RunDir
from tests.rom.test_loop_overworld import FirstChoiceBrain, Quiet  # the stand-in brain and the silent broadcaster


def test_a_run_checkpoints_and_resumes_from_the_newest_one(rom, state_path, tmp_path):
    import asyncio

    run_dir = RunDir.create(tmp_path, rom=rom, flags={"state": "route1"})
    with Emulator(rom) as emu:
        emu.load(state_path("route1"))
        loop = Loop(emu, Quiet(), LoopConfig(paced=False, fps=0.001), brain=FirstChoiceBrain(), run_dir=run_dir)
        asyncio.run(loop.run(max_iterations=400))
        asyncio.run(loop.checkpoint())
        made = loop.decision_count
        map_at_exit = emu.mem[ram.wCurMap]
    assert made >= CHECKPOINT_EVERY, "400 iterations from Route 1 decide at least 25 times"
    newest = run_dir.last_checkpoint()
    assert newest is not None and newest.name == f"checkpoint-{made}.state"
    assert run_dir.count() == made

    resumed = RunDir.open(run_dir.path)
    resumed.mark_resumed()
    with Emulator(rom) as emu:
        emu.load(resumed.last_checkpoint())
        assert emu.mem[ram.wCurMap] == map_at_exit
        loop = Loop(emu, Quiet(), LoopConfig(paced=False, fps=0.001), brain=FirstChoiceBrain(), run_dir=resumed)
        assert loop.decision_count == made
        asyncio.run(loop.run(max_iterations=50))
    assert resumed.count() > made
    assert len(resumed.info()["resumed_at"]) == 1
```

If `Quiet` is not importable from `tests/rom/test_loop_overworld.py` (check its name; the milestone 3a ROM test defines a silent broadcaster), define a two-line one in the new file instead.

- [ ] **Step 2: Run to verify they fail**

Run: `env -u JEVPLAYS_ROM .venv/bin/python -m pytest -q tests/test_cli.py`
Expected: the three new tests FAIL (unknown flags).

- [ ] **Step 3: Implement in `cli.py`**

In `build_parser`, on the `run` subparser:

```python
    source = run.add_mutually_exclusive_group()
    source.add_argument("--state", type=Path, help="start from this save state instead of the intro")
    source.add_argument("--resume", type=Path, metavar="RUN_DIR", help="continue a run from its newest checkpoint")
    run.add_argument("--runs-dir", type=Path, default=Path("runs"), help="where new run directories go")
    run.add_argument("--no-log", action="store_true", help="keep no run directory (no log, no checkpoints)")
```

(remove the old standalone `--state` line). In `cmd_run`, before `main_async`:

```python
    from jevplays.runlog import RunDir

    run_dir = None
    start_state = args.state
    if args.resume is not None:
        try:
            run_dir = RunDir.open(args.resume)
        except FileNotFoundError as error:
            print(f"jevplays run: {error}", file=sys.stderr)
            return 2
        start_state = run_dir.last_checkpoint()
        if start_state is None:
            print(f"jevplays run: {args.resume} has no checkpoint to resume from", file=sys.stderr)
            return 2
        run_dir.mark_resumed()
    elif not args.no_log:
        run_dir = RunDir.create(
            args.runs_dir,
            rom=rom,
            flags={
                "state": str(args.state) if args.state else None,
                "resume": None,
                "port": args.port,
                "unpaced": args.unpaced,
                "no_brain": args.no_brain,
                "battle_goal": args.battle_goal,
            },
        )
```

Inside `main_async`: use `start_state` where `args.state` was used for loading; after the dashboard line print `print(f"run: {run_dir.path}" if run_dir else "run: not logged (--no-log)", flush=True)`; construct `Loop(emu, broadcaster, config, brain=brain, run_dir=run_dir)`; in the `finally` after `loop.run()`, before `status_event("stopped")`, add `await loop.checkpoint()`.

Keep `from jevplays.runlog import RunDir` local to `cmd_run` (the parser test only needs the flags; `runlog` is emulator-free anyway).

- [ ] **Step 4: Run the tests**

Run: `env -u JEVPLAYS_ROM .venv/bin/python -m pytest -q tests/test_cli.py tests/test_imports.py` then `mise exec -- uv run pytest tests/rom/test_resume.py -q`
Expected: pass. Then a manual run to watch it end to end: `mise exec -- uv run jevplays run --state states/route1.state --no-brain --unpaced` for ~20 s, Ctrl-C (or kill), and check `runs/<stamp>/` holds `run.json`, `decisions.jsonl`, and a `checkpoint-<n>.state`; then `mise exec -- uv run jevplays run --resume runs/<stamp>` prints the same run path and `run.json` gains `resumed_at`.

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/cli.py tests/test_cli.py tests/rom/test_resume.py
git commit -m "feat(cli): every run gets a runs/ directory; --resume continues from the newest checkpoint"
```

---

### Task 4: `jevplays replay` pushes a logged run through the dashboard

**Files:**
- Create: `src/jevplays/dashboard/replay.py`
- Modify: `src/jevplays/cli.py` (new `replay` subcommand)
- Test: `tests/test_replay.py`

**Interfaces:**
- Consumes: `RunDir.open/decisions/info`, `dashboard.server.Broadcaster/create_app/serve`, `dashboard.events.status_event`.
- Produces: `async def replay(run_dir: RunDir, broadcaster, *, delay: float = 1.0, limit: int | None = None, sleep=asyncio.sleep) -> int` — publishes `status_event("running", f"replaying {run_dir.path.name}: {i}/{n}")` then `{"type": "decision", "decision": <the logged dict>}` for each line (in order), sleeping `delay` between decisions (not before the first), and `status_event("stopped", f"replayed {n} decisions")` at the end; returns the number replayed. The decision event is built by `decision_event_from_dict(d: dict) -> dict` (a new function in `dashboard/events.py`: `{"type": "decision", "decision": d}`) so the replayed event is byte-for-byte the shape the live loop sends. CLI: `jevplays replay RUN_DIR [--port 8765] [--delay 1.0] [--limit N]` serves the dashboard on `127.0.0.1`, waits 0.2 s for the bind like `run` does, prints `dashboard: http://127.0.0.1:<port>` and `replaying <path> (<n> decisions)`, runs `replay`, and keeps serving until Ctrl-C (so the page can be looked at after the last decision), then exits 0. Missing `run.json` → message on stderr, exit 2.

- [ ] **Step 1: Failing tests**

```python
# tests/test_replay.py
"""Spec 13: `replay` feeds a fixture log end to end through the websocket."""

import asyncio
import json

from starlette.testclient import TestClient

from jevplays.brain.decision import Decision, PromptAction
from jevplays.cli import main
from jevplays.dashboard.replay import replay
from jevplays.dashboard.server import Broadcaster, create_app
from jevplays.runlog import RunDir
from tests.test_server import FakeSocket


def logged_run(tmp_path, n: int) -> RunDir:
    run = RunDir.create(tmp_path, rom=None, flags={})
    for i in range(n):
        run.append(Decision(id=f"d{i}", ts=float(i), kind="prompt", state_summary={"prompt": f"q{i}"},
                            questions={}, answers={}, action="answer YES", model="jev-1.13.0",
                            action_value=PromptAction(yes=True)))
    return run


def test_replay_publishes_each_logged_decision_in_order_with_status_around_it(tmp_path):
    run = logged_run(tmp_path, 3)
    slept: list[float] = []

    async def fake_sleep(s):
        slept.append(s)

    async def scenario():
        bc = Broadcaster()
        sock = FakeSocket()
        await bc.connect(sock)
        n = await replay(run, bc, delay=0.5, sleep=fake_sleep)
        return n, [json.loads(m) for m in sock.sent]

    n, events = asyncio.run(scenario())
    assert n == 3
    decisions = [e for e in events if e["type"] == "decision"]
    assert [d["decision"]["id"] for d in decisions] == ["d0", "d1", "d2"]
    assert decisions[0]["decision"]["state_summary"] == {"prompt": "q0"}
    assert events[0]["type"] == "status" and events[0]["message"].startswith("replaying")
    assert events[-1] == {"type": "status", "status": "stopped", "message": "replayed 3 decisions"}
    assert slept == [0.5, 0.5]


def test_replay_honours_the_limit(tmp_path):
    run = logged_run(tmp_path, 5)

    async def scenario():
        bc = Broadcaster()
        return await replay(run, bc, delay=0, limit=2)

    assert asyncio.run(scenario()) == 2


def test_replayed_events_reach_a_real_websocket_client(tmp_path):
    run = logged_run(tmp_path, 2)
    bc = Broadcaster()
    app = create_app(bc)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        client.portal.call(lambda: replay(run, bc, delay=0))  # run the coroutine on the app's loop
        seen = [json.loads(ws.receive_text()) for _ in range(4)]
    assert [e["type"] for e in seen] == ["status", "decision", "decision", "status"]


def test_replay_command_rejects_a_directory_that_is_not_a_run(tmp_path, capsys):
    assert main(["replay", str(tmp_path)]) == 2
    assert "run.json" in capsys.readouterr().err
```

If `client.portal.call` does not accept a coroutine function in the installed Starlette (check `TestClient.portal`), replace that line with `asyncio.run(replay(run, bc, delay=0))` executed **before** opening the socket and assert the late-joiner gets the latest `status`/`decision` from `Broadcaster.latest` (two events) instead of four; say which variant you used in the report.

- [ ] **Step 2: Run to verify they fail**

Run: `env -u JEVPLAYS_ROM .venv/bin/python -m pytest -q tests/test_replay.py`
Expected: FAIL (`No module named jevplays.dashboard.replay`).

- [ ] **Step 3: Implement**

```python
# src/jevplays/dashboard/replay.py
"""Play a logged run back through the dashboard: the same decision events the loop sent, from
decisions.jsonl, with a delay between them. No emulator, no API key; the page cannot tell."""

import asyncio

from jevplays.dashboard.events import decision_event_from_dict, status_event
from jevplays.runlog import RunDir


async def replay(run_dir: RunDir, broadcaster, *, delay: float = 1.0, limit: int | None = None, sleep=asyncio.sleep) -> int:
    decisions = list(run_dir.decisions())
    if limit is not None:
        decisions = decisions[:limit]
    total = len(decisions)
    for i, d in enumerate(decisions, start=1):
        if i > 1 and delay > 0:
            await sleep(delay)
        await broadcaster.publish(status_event("running", f"replaying {run_dir.path.name}: {i}/{total}"))
        await broadcaster.publish(decision_event_from_dict(d))
    await broadcaster.publish(status_event("stopped", f"replayed {total} decisions"))
    return total
```

In `events.py` add `def decision_event_from_dict(d: dict) -> dict: return {"type": "decision", "decision": d}` and have `decision_event` call it with `decision.to_dict()`.

In `cli.py` add:

```python
def cmd_replay(args: argparse.Namespace) -> int:
    from jevplays.dashboard.replay import replay
    from jevplays.dashboard.server import Broadcaster, create_app, serve
    from jevplays.runlog import RunDir

    try:
        run_dir = RunDir.open(args.run_dir)
    except FileNotFoundError as error:
        print(f"jevplays replay: {error}", file=sys.stderr)
        return 2

    async def main_async() -> None:
        broadcaster = Broadcaster()
        server = asyncio.create_task(serve(create_app(broadcaster), port=args.port))
        try:
            await asyncio.sleep(0.2)
            if server.done():
                server.result()
            print(f"dashboard: http://127.0.0.1:{args.port}", flush=True)
            print(f"replaying {run_dir.path} ({run_dir.count()} decisions)", flush=True)
            await replay(run_dir, broadcaster, delay=args.delay, limit=args.limit)
            print("replay finished; the dashboard stays up until Ctrl-C", flush=True)
            await server  # keep serving
        finally:
            server.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await server

    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass
    return 0
```

and in `build_parser`:

```python
    replay = sub.add_parser("replay", help="play a logged run back on the dashboard, no emulator or API key needed")
    replay.add_argument("run_dir", type=Path)
    replay.add_argument("--port", type=int, default=8765)
    replay.add_argument("--delay", type=float, default=1.0, help="seconds between decisions")
    replay.add_argument("--limit", type=int, default=None, help="stop after this many decisions")
    replay.set_defaults(func=cmd_replay)
```

- [ ] **Step 4: Run the tests and a manual replay**

Run: `env -u JEVPLAYS_ROM .venv/bin/python -m pytest -q tests/test_replay.py tests/test_server.py tests/test_imports.py`
Expected: pass. Manual: `mise exec -- uv run jevplays replay runs/<stamp from Task 3> --delay 0.3` and open the page: the decision panel and log fill up; the screen stays on its placeholder (no frames are logged; that is by design).

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/dashboard/replay.py src/jevplays/dashboard/events.py src/jevplays/cli.py tests/test_replay.py
git commit -m "feat(dashboard): jevplays replay plays a logged run back through the page"
```

---

### Task 5: The `?layout=stream` arrangement

**Files:**
- Modify: `src/jevplays/dashboard/static/index.html`, `app.js`, `styles.css`
- Test: `tests/test_server.py` (add one)

**Interfaces:**
- `app.js`: at start, `const layout = new URLSearchParams(location.search).get("layout"); if (layout === "stream") document.body.dataset.layout = "stream";`. Nothing else in the script changes; the page keeps rendering the same elements.
- `styles.css`: a `body[data-layout="stream"]` block that lays the page out for a 1920x1080 canvas: `html, body { width: 1920px; height: 1080px; overflow: hidden; }`; `header` stays as a 60px bar with the title and status pill; `main` becomes a two-column grid `960px 1fr` with 0 padding and 24px gap; the screen image is 960x864 (6x, `image-rendering: pixelated`); the party strip sits under it in the remaining 156px; the right panel shows, top to bottom, the goal line (larger, 22px), the leg line, the decision headline (26px) and bars (bar label column 200px, fill height 22px, 18px labels), then the log limited to the last 8 entries by `max-height` with `overflow: hidden` (no scrollbars on stream); the collapsed State `<details>` is hidden (`display: none`). Fonts scale up (base 18px) so the bars are legible at stream resolution.
- `index.html`: unchanged apart from nothing; the layout switch is purely CSS/JS. (If a wrapper element is needed to hide the State block, add a class to the existing `<details>`: `class="state-block"`.)

- [ ] **Step 1: Failing test** (append to `tests/test_server.py`)

```python
def test_the_page_serves_the_same_html_for_the_stream_layout_and_the_css_knows_it():
    client = TestClient(create_app(Broadcaster()))
    assert client.get("/?layout=stream").status_code == 200
    css = client.get("/static/styles.css").text
    js = client.get("/static/app.js").text
    assert 'body[data-layout="stream"]' in css
    assert 'dataset.layout' in js and "1920px" in css
```

- [ ] **Step 2: Run to verify it fails**, then **Step 3: implement** per the interface above, then **Step 4: check in a browser** (the controller does this): `mise exec -- uv run jevplays replay runs/<stamp> --delay 0.5` and open `http://127.0.0.1:8765/?layout=stream` in a window sized 1920x1080 (or the device toolbar at that size): no scrollbars, screen left, bars right, the log's last entries at the bottom; and `http://127.0.0.1:8765/` still looks as before.

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/dashboard/static tests/test_server.py
git commit -m "feat(dashboard): a fixed 1920x1080 stream layout behind ?layout=stream"
```

---

### Task 6: Docs, full check, PR

- README: a "Runs" section (what `runs/<stamp>/` holds, `--resume`, `--no-log`, `jevplays replay`, the stream layout URL for OBS's browser source at 1920x1080); status line "milestone 3b". CLAUDE.md: one line under Build & test: "`runs/` is per-run output (logs and checkpoints), gitignored; tests write runs under `tmp_path`". Spec: no amendment needed unless a task deviated; if one did, amend the section it touched the way 3a's amendments are marked.
- Checks: `mise run check`; `env -u JEVPLAYS_ROM .venv/bin/python -m pytest -q`; `mise exec -- uv run pytest -q`; `git ls-files | grep -E '\.state$|\.ram$|mise\.local|^runs/'` prints nothing.
- Commit `docs: runs, resume, replay, and the stream layout`; the controller pushes and opens the PR "Milestone 3b: run logging, resume, replay, stream layout" (base `main` after #9 merges, else `tylervick/milestone-3-goals`).

---

## Self-review

**Spec coverage:** 11 (run dir, run.json fields, JSONL, checkpoints every 25 plus exit, `--resume`) → Tasks 1–3; 10 replay → Task 4; 10 `?layout=stream` → Task 5; 12 "a run can be resumed from its checkpoint" → Task 3; 13 "replay feeds a fixture log end to end through the websocket" → Task 4's websocket test; 14 → Task 6. Not in spec, added: `--no-log` and `--runs-dir` (operational conveniences; documented in README).

**Placeholder scan:** none; every code step has its code. Task 2's `prompt_emulator` helper and Task 3's `Quiet` are named as "reuse if present, else add" with the shape given.

**Type consistency:** `RunDir.append/count/decisions/checkpoint/last_checkpoint/set_model/mark_resumed/info` (Task 1) are the names Tasks 2–4 call; `Loop(run_dir=)`, `decision_count`, `checkpoint()` (Task 2) are what Task 3 uses; `decision_event_from_dict` (Task 4) lives in `events.py`; `replay(run_dir, broadcaster, *, delay, limit, sleep)` matches the tests and the CLI call.
