# Counterfactual Branching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure whether the action Jev chose at each battle and explore decision beat the alternatives, by replaying every alternative from a saved state and letting Jev play each branch to the milestone.

**Architecture:** A run records a snapshot (emulator state + a JSON sidecar) at every decision. `jevplays branch` rebuilds each decision from its snapshot, checks the rebuild matches what Jev saw, lists the alternatives, and runs every (alternative, seed) as a headless `Loop` in a worker process with the first action forced. Jev plays the rest of each branch through a response cache. Everything a measurement writes goes into one SQLite file. A report script scores it.

**Tech Stack:** Python 3.12, PyBoy (only in `emulator/pyboy.py`), `sqlite3` and `concurrent.futures` from the standard library, pytest, ruff, mise/uv.

**Spec:** `docs/superpowers/specs/2026-09-23-counterfactual-branching-design.md`

## Global Constraints

- `import pyboy` lives in `src/jevplays/emulator/pyboy.py` and nowhere else. `import typesafe_sdk` lives in `src/jevplays/brain/client.py` and nowhere else. The new `jevplays.branch` package must import cleanly with neither: import `Emulator` and `Brain` only inside the functions that need them.
- `import jevplays.cli` must not pull in pyboy or typesafe_sdk (`tests/test_imports.py`).
- Tests under `tests/rom/` need `JEVPLAYS_ROM` and `states/`. A ROM-dependent assertion never moves out of `tests/rom/`.
- Never commit a ROM, a save state, a `.ram` file, or `mise.local.toml`. `runs/` is gitignored; tests write under `tmp_path`.
- Never edit or delete an existing test to make it pass.
- Jev judges, code executes: nothing in this plan changes a question, a state field Jev sees, or policy, so the fixtures are not re-recorded.
- Conventional commits (`feat(tooling):`, `feat(brain):`, `test(...)`, `docs:`), each ending with
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- `mise run check` (lint + tests) passes before every push.
- Values fixed by the spec: K defaults to 8; the cap is 3× the logged run's frames to the milestone; a stall is 20,000 game frames with no new decision; 60 frames per second; bootstrap intervals are 95% with a fixed RNG; the best alternative is chosen on the first half of the seeds and scored on the second half.

## Review Focus

1. **Seeding may not change the dice at a battle menu.** If ticking idle frames before a forced move does not change the game's random numbers, all K seeds are one sample repeated. Task 10 asserts that 8 seeds of the same forced move produce more than one distinct enemy HP after the turn.
2. **An interrupted measurement resumed.** A branch killed halfway leaves decision rows with no `branch` row. Resuming must clear them and rerun that branch, not skip it and not duplicate rows. `clear_partial` is tested in Task 4; `measure` queues only keys missing from `done()` (Task 8) and `run_branch` clears before it starts.
3. **Another decision point before the forced one.** For example, a YES/NO box appears before the battle menu. The loop must not quietly ask Jev and carry the forced action forward to a later menu. It must raise, and the branch is recorded as `error`. Test in Task 2.
4. **Re-running `jevplays branch` with a different `--seeds` on an existing measurement.** Mixing K=4 and K=8 rows would break the seed split. The command must refuse. Test in Task 8.
5. **Branching a run recorded without `--snapshot-every-decision`,** or one that never reached a milestone. It must fail with a clear message and exit code 2, not an empty report. A decision very close to its milestone must not get a cap of a few hundred frames. Tests in Task 8.

Four refinements the plan makes to the spec are written back into the spec in Task 1: the explore fidelity check compares the whole state summary, not just the option ids; seed frames are ticked after the forced decision is recorded rather than before it (idle frames before an explore decision move NPCs and change the option list); the cap has a floor of one game minute; and a branch whose forced action could not be taken is recorded as `error`.

---

### Task 1: Check that Jev answers the same input the same way, and amend the spec

**Files:**
- Create: `src/jevplays/branch/__init__.py`
- Create: `src/jevplays/branch/score.py` (only `answer_spread` in this task)
- Create: `Scripts/jev-determinism.py`
- Modify: `docs/superpowers/specs/2026-09-23-counterfactual-branching-design.md`
- Test: `tests/test_branch_score.py`

**Interfaces:**
- Produces: `answer_spread(responses: list[dict]) -> float`: the largest absolute difference, across the given raw responses to one input, of any choice probability or noul value. `jevplays.branch` package exists.

- [ ] **Step 1: Write the failing test**

`tests/test_branch_score.py`:

```python
from jevplays.branch.score import answer_spread


def _choice(p):
    return {"answers": {"move": {"type": "choice", "choice": "A", "probabilities": {"A": p, "B": 1 - p}, "confidence": 0.5}}}


def test_identical_responses_have_no_spread():
    assert answer_spread([_choice(0.7), _choice(0.7), _choice(0.7)]) == 0.0


def test_spread_is_the_largest_difference_in_any_probability_or_noul():
    a = {"answers": {"run": {"type": "noul", "noul": 0.10}, **_choice(0.70)["answers"]}}
    b = {"answers": {"run": {"type": "noul", "noul": 0.25}, **_choice(0.72)["answers"]}}
    assert abs(answer_spread([a, b]) - 0.15) < 1e-9


def test_an_answer_missing_from_one_response_counts_as_full_spread():
    a = {"answers": {"run": {"type": "noul", "noul": 0.1}}}
    b = {"answers": {}}
    assert answer_spread([a, b]) == 1.0
```

- [ ] **Step 2: Run it and watch it fail**

Run: `mise exec -- uv run pytest tests/test_branch_score.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jevplays.branch'`

- [ ] **Step 3: Implement**

`src/jevplays/branch/__init__.py`:

```python
"""Counterfactual branching (#82): replay every alternative of a decision Jev made, from the same
saved state, and measure which one reached the milestone soonest.

Nothing in this package imports pyboy or the TypeSafe SDK at module scope; the worker imports both
inside the function that runs a branch."""
```

`src/jevplays/branch/score.py`:

```python
"""Scoring a branch measurement. Pure functions over rows, so every number the report prints can
be recomputed from `branches.sqlite` alone."""


def _values(response: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for qid, answer in response.get("answers", {}).items():
        if answer.get("type") == "noul":
            out[qid] = float(answer["noul"])
        elif answer.get("type") == "choice":
            for option, p in answer.get("probabilities", {}).items():
                out[f"{qid}:{option}"] = float(p)
    return out


def answer_spread(responses: list[dict]) -> float:
    """The largest absolute difference, across `responses` to one input, of any probability or
    noul. An answer one response has and another lacks counts as a spread of 1.0."""
    values = [_values(r) for r in responses]
    keys = set().union(*values) if values else set()
    spread = 0.0
    for key in keys:
        seen = [v[key] for v in values if key in v]
        if len(seen) < len(values):
            return 1.0
        spread = max(spread, max(seen) - min(seen))
    return spread
```

- [ ] **Step 4: Run it and watch it pass**

Run: `mise exec -- uv run pytest tests/test_branch_score.py -v`
Expected: 3 passed.

- [ ] **Step 5: Write the determinism script**

`Scripts/jev-determinism.py`:

```python
#!/usr/bin/env -S uv run
"""Does Jev answer the same input the same way? The response cache in `jevplays branch` assumes
so (spec: "The response cache").

    mise exec -- uv run Scripts/jev-determinism.py RUN_DIR [--inputs 20] [--repeats 5]

Takes `--inputs` battle and explore decisions Jev made in RUN_DIR, spread evenly through the run,
rebuilds each one's questions from its logged state summary, asks each `--repeats` times, and
prints the spread of every input and the largest overall. Needs TYPESAFE_API_KEY.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from jevplays.brain.battle import battle_questions
from jevplays.brain.client import Brain
from jevplays.brain.explore import explore_questions
from jevplays.branch.score import answer_spread
from jevplays.runlog import RunDir

BUILDERS = {"battle": battle_questions, "explore": explore_questions}


async def main_async(run: Path, inputs: int, repeats: int) -> int:
    logged = [
        d
        for d in RunDir.open(run).decisions()
        if d["kind"] in BUILDERS and d["questions"] and not d["fallback"]
    ]
    if not logged:
        print(f"{run}: no battle or explore decisions Jev made", file=sys.stderr)
        return 2
    step = max(1, len(logged) // inputs)
    picked = logged[::step][:inputs]
    brain = Brain()
    worst = 0.0
    try:
        for d in picked:
            sj = d["state_summary"]
            questions = BUILDERS[d["kind"]](sj)
            responses = [(await brain.ask(sj, questions))[0] for _ in range(repeats)]
            spread = answer_spread(responses)
            worst = max(worst, spread)
            print(f"{d['id']}  {d['kind']:<8} spread {spread:.4f}", flush=True)
    finally:
        await brain.close()
    print(f"inputs {len(picked)}, repeats {repeats}, largest spread {worst:.4f}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=Path)
    ap.add_argument("--inputs", type=int, default=20)
    ap.add_argument("--repeats", type=int, default=5)
    args = ap.parse_args()
    return asyncio.run(main_async(args.run, args.inputs, args.repeats))


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Run it against a real run and keep the output**

Run (from the main checkout, which has `runs/shopcheck`):
`mise exec -- uv run .worktrees/branching/Scripts/jev-determinism.py runs/shopcheck/20260921-202922`
Expected: 20 lines and a final `largest spread`. Save the output to the PR description draft. If the largest spread is not 0, the report's header must print it (Task 9 reads it from `meta`).

- [ ] **Step 7: Amend the spec with the plan's four refinements**

In `docs/superpowers/specs/2026-09-23-counterfactual-branching-design.md`:

1. In "Alternatives", replace "For an explore decision, the generated option ids must equal the ids in the logged `state_summary`." with "For an explore decision, the rebuilt state summary, options and memory words included, must equal the logged one."
2. Replace the "Seeds" section's second sentence onward with: "Seed `s` of a branch therefore ticks `s` idle frames right after the forced decision is recorded and before its buttons are pressed or its legs are walked. Ticking before the decision would not do for the overworld: idle frames let NPCs walk, which can change the option list the decision was made from. Every alternative of a decision runs on the same seeds 0 to K−1, including the action Jev actually chose. The logged run is not counted as a branch, because its randomness was not controlled the same way."
3. In "When a branch stops", change the **capped** bullet's first sentence to "the branch has spent 3× the game frames the logged run took from that decision to the same milestone, or one game minute (3,600 frames), whichever is larger."
4. Add a fourth bullet under it: "- **error**: the forced action could not be taken, because another decision point came first or the forced option was not offered. Recorded with its message, never scored, and counted in the report."

- [ ] **Step 8: Lint and commit**

Run: `mise run check`
Expected: all pass.

```bash
git add src/jevplays/branch/__init__.py src/jevplays/branch/score.py tests/test_branch_score.py Scripts/jev-determinism.py docs/superpowers/specs/2026-09-23-counterfactual-branching-design.md
git commit -m "feat(tooling): check whether Jev answers one input the same way twice (#82)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: A Loop that takes one forced action and stops when told

**Files:**
- Modify: `src/jevplays/brain/decision.py` (two fields on `Decision`)
- Modify: `src/jevplays/loop.py` (`Loop.__init__`, `_decide`, `_record`, `_battle_turn`, `_choose_option`, `run`; new `_take_forced`, `ForcedActionMissed`)
- Test: `tests/test_loop_forced.py`

**Interfaces:**
- Produces:
  - `Decision.forced: bool = False`, `Decision.cached: bool = False` (both serialised by `to_dict`).
  - `Loop(..., forced: BattleAction | ExploreAction | None = None, forced_delay: int = 0, stop: Callable[[Loop, GameState], str | None] | None = None)`.
  - `Loop.stop_reason: str | None`: set to whatever `stop` returned when it ended the run.
  - `class ForcedActionMissed(RuntimeError)` in `jevplays.loop`.

- [ ] **Step 1: Write the failing tests**

`tests/test_loop_forced.py`:

```python
import asyncio

import pytest

from jevplays.brain.decision import BattleAction, ExploreAction
from jevplays.loop import ForcedActionMissed, Loop, LoopConfig
from tests.test_loop import (
    BATTLE_MENU,
    MOVES,
    RESPONSE,
    FakeBrain,
    QuestionBrain,
    RecordingBroadcaster,
    battle_emu,
    explore_emu,
)


def pressing_emu():
    """A battle menu whose FIGHT opens the move list, as in test_loop's battle test."""
    emu = battle_emu()
    original = emu.press

    def press(button, **kw):
        r = original(button, **kw)
        if emu.presses == ["a"]:
            emu.set_rows(MOVES)
        return r

    emu.press = press
    return emu


def test_a_forced_battle_action_is_taken_without_asking_and_logged_as_forced():
    emu = pressing_emu()
    brain = FakeBrain(response=RESPONSE)
    loop = Loop(
        emu, RecordingBroadcaster(), LoopConfig(paced=False), brain=brain,
        forced=BattleAction(kind="move", move="SCRATCH"),
    )
    asyncio.run(loop.run(max_iterations=1))
    assert brain.calls == 0
    decision = loop.decisions[0]
    assert decision.forced and not decision.fallback
    assert decision.action == "use SCRATCH"
    assert decision.to_dict()["forced"] is True
    assert loop.forced is None


def test_the_forced_delay_ticks_after_the_decision_is_recorded():
    emu = pressing_emu()
    loop = Loop(
        emu, RecordingBroadcaster(), LoopConfig(paced=False), brain=FakeBrain(response=RESPONSE),
        forced=BattleAction(kind="move", move="SCRATCH"), forced_delay=5,
    )
    ticked = []
    original = emu.tick
    emu.tick = lambda frames=1, **kw: (ticked.append(frames), original(frames, **kw))[1]
    asyncio.run(loop.run(max_iterations=1))
    assert 5 in ticked


def test_the_decision_after_the_forced_one_goes_to_the_brain():
    emu = pressing_emu()
    brain = FakeBrain(response=RESPONSE)
    loop = Loop(
        emu, RecordingBroadcaster(), LoopConfig(paced=False), brain=brain,
        forced=BattleAction(kind="move", move="SCRATCH"),
    )
    asyncio.run(loop.run(max_iterations=1))
    emu.set_rows(BATTLE_MENU)
    emu.presses.clear()
    asyncio.run(loop.run(max_iterations=1))
    assert brain.calls == 1
    assert [d.forced for d in loop.decisions] == [True, False]


def test_a_forced_explore_option_is_started_without_asking():
    emu = explore_emu()
    brain = QuestionBrain(explore="exit_south", needs_heal=0.1)
    loop = Loop(
        emu, RecordingBroadcaster(), LoopConfig(paced=False), brain=brain,
        forced=ExploreAction(option_id="exit_north", kind="exit", text="go north to Route 2"),
    )
    asyncio.run(loop.run(max_iterations=1))
    assert brain.calls == 0
    assert loop.option is not None and loop.option.id == "exit_north"
    assert loop.decisions[0].forced


def test_a_forced_option_that_is_not_offered_raises():
    emu = explore_emu()
    loop = Loop(
        emu, RecordingBroadcaster(), LoopConfig(paced=False), brain=QuestionBrain(explore="exit_north"),
        forced=ExploreAction(option_id="door_99", kind="door", text="enter nowhere"),
    )
    with pytest.raises(ForcedActionMissed, match="door_99"):
        asyncio.run(loop.run(max_iterations=1))


def test_another_decision_before_the_forced_one_raises_instead_of_asking_jev():
    """Review focus 3: an explore decision arrives while a battle action is still forced."""
    emu = explore_emu()
    loop = Loop(
        emu, RecordingBroadcaster(), LoopConfig(paced=False),
        brain=QuestionBrain(explore="exit_north", needs_heal=0.1),
        forced=BattleAction(kind="move", move="SCRATCH"),
    )
    with pytest.raises(ForcedActionMissed, match="before the forced action"):
        asyncio.run(loop.run(max_iterations=1))


def test_stop_ends_the_run_and_records_why():
    emu = explore_emu()
    seen = []

    def stop(loop, state):
        seen.append(loop.game_frames)
        return "capped" if len(seen) == 2 else None

    loop = Loop(emu, RecordingBroadcaster(), LoopConfig(paced=False), stop=stop)
    asyncio.run(loop.run(max_iterations=10))
    assert loop.stop_reason == "capped"
    assert len(seen) == 2


def test_a_cached_response_is_logged_as_cached():
    emu = pressing_emu()
    brain = FakeBrain(response={**RESPONSE, "cached": True})
    loop = Loop(emu, RecordingBroadcaster(), LoopConfig(paced=False), brain=brain)
    asyncio.run(loop.run(max_iterations=1))
    assert loop.decisions[0].cached is True
```

- [ ] **Step 2: Run them and watch them fail**

Run: `mise exec -- uv run pytest tests/test_loop_forced.py -v`
Expected: FAIL with `ImportError: cannot import name 'ForcedActionMissed'`.

- [ ] **Step 3: Add the two Decision fields**

In `src/jevplays/brain/decision.py`, in `class Decision`, add between `latency_ms` and `action_value`:

```python
    forced: bool = False
    """Set on a branch's first action (#82): code pressed it without asking Jev."""
    cached: bool = False
    """The answers came from a branch measurement's response cache, not a live request."""
```

- [ ] **Step 4: Implement the loop changes**

In `src/jevplays/loop.py`:

Add `from collections.abc import Callable` to the imports.

Below `local_decision`, add:

```python
class ForcedActionMissed(RuntimeError):
    """A branch's forced action could not be taken where it was meant to be (#82): another
    decision point came first, or the forced option is not on offer. The branch is recorded as
    an error rather than letting Jev decide in its place."""
```

In `Loop.__init__`, add three keyword parameters after `memory`:

```python
        forced: BattleAction | ExploreAction | None = None,
        forced_delay: int = 0,
        stop: "Callable[[Loop, GameState], str | None] | None" = None,
```

and at the end of `__init__`:

```python
        self.forced = forced
        """A branch's first action (#82), taken at the first battle menu or explore turn instead
        of asking Jev, then cleared."""
        self.forced_delay = forced_delay
        """Idle frames ticked right after the forced decision is recorded: a branch's seed."""
        self.stop = stop
        """Asked after every step whether the run should end, and why; None never stops it."""
        self.stop_reason: str | None = None
```

In `_decide`, after `decision = decoder(...)` (inside the `else:` branch, after the call), add:

```python
            decision.cached = bool(response.get("cached"))
```

At the top of `_record`, add:

```python
        if self.forced is not None and not decision.forced:
            raise ForcedActionMissed(f"a {decision.kind} decision came before the forced action")
```

Add a method after `_record`:

```python
    async def _take_forced(self, kind: str, sj: dict) -> Decision:
        """The branch's forced action, recorded like any decision and never asked (#82)."""
        action, self.forced = self.forced, None
        decision = Decision(
            id=uuid.uuid4().hex[:12],
            ts=time.time(),
            kind=kind,
            state_summary=sj,
            questions={},
            answers={},
            action=action.describe(),
            forced=True,
            action_value=action,
        )
        await self._record(decision)
        if self.forced_delay:
            self.emu.tick(self.forced_delay)
        return decision
```

In `_battle_turn`, replace

```python
        decision = await self._decide("battle", sj, questions, partial(decide_battle, supported=ALL_ACTIONS))
```

with

```python
        if isinstance(self.forced, BattleAction):
            decision = await self._take_forced("battle", sj)
        else:
            decision = await self._decide(
                "battle", sj, questions, partial(decide_battle, supported=ALL_ACTIONS)
            )
```

In `_choose_option`, replace the `decision = await self._decide("explore", ...)` call (through its closing parenthesis) with

```python
        if isinstance(self.forced, ExploreAction):
            decision = await self._take_forced("explore", sj)
            if not any(o.id == decision.action_value.option_id for o in options):
                raise ForcedActionMissed(
                    f"forced option {decision.action_value.option_id} is not offered here"
                )
        else:
            decision = await self._decide(
                "explore",
                sj,
                questions,
                partial(decide_explore, options=options),
                offline=(
                    ExploreAction(option_id=offline.id, kind=offline.kind, text=offline.text),
                    f"no brain: {offline.text}",
                ),
            )
```

In `run`, directly after the `if counted is not None ... else ...` block that updates `self.game_frames` (and before `captured = self._take_frames()`), add:

```python
            if self.stop is not None:
                reason = self.stop(self, state)
                if reason is not None:
                    self.stop_reason = reason
                    return
```

- [ ] **Step 5: Run the new tests and the loop's existing tests**

Run: `mise exec -- uv run pytest tests/test_loop_forced.py tests/test_loop.py tests/test_runlog.py tests/test_replay.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/jevplays/brain/decision.py src/jevplays/loop.py tests/test_loop_forced.py
git commit -m "feat(tooling): a loop can take one forced action and stop when told (#82)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Snapshot every decision, and note when each milestone finished

**Files:**
- Modify: `src/jevplays/runlog.py` (snapshot methods)
- Modify: `src/jevplays/loop.py` (`LoopConfig.snapshot_every_decision`, `_record`, `_refresh_milestone`)
- Modify: `src/jevplays/cli.py` (`--snapshot-every-decision`)
- Test: `tests/test_runlog_snapshots.py`, and one test added to `tests/test_cli.py`

**Interfaces:**
- Produces:
  - `RunDir.snapshots_path -> Path` (`<run>/snapshots`)
  - `RunDir.snapshot(emu, n: int, sidecar: dict) -> Path`: writes `snapshots/<n>.state` and `snapshots/<n>.json`
  - `RunDir.snapshot_state(n: int) -> Path | None`, `RunDir.snapshot_info(n: int) -> dict | None`
  - `RunDir.note_milestone(milestone: str, frame: int) -> None`: appends to `snapshots/milestones.jsonl`
  - `RunDir.milestones_done() -> dict[str, int]`: the first frame each milestone was done at
  - Sidecar keys: `frame` (int, `Loop._game_clock()`), `milestone` (str | None, `Loop.milestone.id`), `memory` (`Memory.to_dict()`)
  - `LoopConfig.snapshot_every_decision: bool = False`

- [ ] **Step 1: Write the failing tests**

`tests/test_runlog_snapshots.py`:

```python
import asyncio

from jevplays.loop import Loop, LoopConfig
from jevplays.runlog import RunDir
from tests.support import FakeEmulator
from tests.test_loop import QuestionBrain, RecordingBroadcaster, explore_emu


def test_a_snapshot_writes_the_state_and_its_sidecar(tmp_path):
    run = RunDir.create(tmp_path, rom=None, flags={})
    path = run.snapshot(FakeEmulator(), 3, {"frame": 120, "milestone": "get_pokedex", "memory": {}})
    assert path == run.snapshots_path / "3.state" and path.is_file()
    assert run.snapshot_state(3) == path
    assert run.snapshot_info(3) == {"frame": 120, "milestone": "get_pokedex", "memory": {}}
    assert run.snapshot_state(4) is None and run.snapshot_info(4) is None


def test_milestones_done_keeps_the_first_frame_of_each(tmp_path):
    run = RunDir.create(tmp_path, rom=None, flags={})
    assert run.milestones_done() == {}
    run.note_milestone("get_starter", 500)
    run.note_milestone("get_pokedex", 9000)
    run.note_milestone("get_starter", 9999)
    assert run.milestones_done() == {"get_starter": 500, "get_pokedex": 9000}


def test_the_loop_snapshots_every_decision_when_asked(tmp_path):
    run = RunDir.create(tmp_path, rom=None, flags={})
    loop = Loop(
        explore_emu(), RecordingBroadcaster(), LoopConfig(paced=False, snapshot_every_decision=True),
        brain=QuestionBrain(explore="exit_north", needs_heal=0.1), run_dir=run,
    )
    asyncio.run(loop.run(max_iterations=1))
    assert run.count() == 1
    info = run.snapshot_info(1)
    assert set(info) == {"frame", "milestone", "memory"}
    assert info["memory"] == loop.memory.to_dict()


def test_the_loop_takes_no_snapshots_by_default(tmp_path):
    run = RunDir.create(tmp_path, rom=None, flags={})
    loop = Loop(
        explore_emu(), RecordingBroadcaster(), LoopConfig(paced=False),
        brain=QuestionBrain(explore="exit_north", needs_heal=0.1), run_dir=run,
    )
    asyncio.run(loop.run(max_iterations=1))
    assert not run.snapshots_path.exists()
```

Append to `tests/test_cli.py`:

```python
def test_snapshots_cannot_be_combined_with_resume_or_no_log(tmp_path, capsys):
    import pytest

    from jevplays.cli import main

    for extra in (["--resume", str(tmp_path)], ["--no-log"]):
        with pytest.raises(SystemExit):
            main(["run", "--snapshot-every-decision", *extra])
        assert "--snapshot-every-decision" in capsys.readouterr().err
```

- [ ] **Step 2: Run them and watch them fail**

Run: `mise exec -- uv run pytest tests/test_runlog_snapshots.py tests/test_cli.py::test_snapshots_cannot_be_combined_with_resume_or_no_log -v`
Expected: FAIL (`AttributeError: 'RunDir' object has no attribute 'snapshot'`, and an unrecognised argument).

- [ ] **Step 3: Implement the RunDir methods**

Append to `class RunDir` in `src/jevplays/runlog.py`:

```python
    # -- snapshots (#82) ----------------------------------------------------------------

    @property
    def snapshots_path(self) -> Path:
        return self.path / "snapshots"

    def snapshot(self, emu, n: int, sidecar: dict) -> Path:
        """The game and what the loop knew at decision `n`, after it was logged and before its
        buttons were pressed: the point a counterfactual branch starts from."""
        self.snapshots_path.mkdir(exist_ok=True)
        path = self.snapshots_path / f"{n}.state"
        emu.save(path)
        (self.snapshots_path / f"{n}.json").write_text(
            json.dumps(sidecar, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return path

    def snapshot_state(self, n: int) -> Path | None:
        path = self.snapshots_path / f"{n}.state"
        return path if path.is_file() else None

    def snapshot_info(self, n: int) -> dict | None:
        path = self.snapshots_path / f"{n}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def note_milestone(self, milestone: str, frame: int) -> None:
        self.snapshots_path.mkdir(exist_ok=True)
        with open(self.snapshots_path / "milestones.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"milestone": milestone, "frame": frame}) + "\n")

    def milestones_done(self) -> dict[str, int]:
        """The game frame each milestone was first seen done at, on the clock the sidecars use."""
        path = self.snapshots_path / "milestones.jsonl"
        done: dict[str, int] = {}
        if not path.is_file():
            return done
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                done.setdefault(row["milestone"], row["frame"])
        return done
```

- [ ] **Step 4: Implement the loop and CLI changes**

In `LoopConfig` (`src/jevplays/loop.py`), add after `max_decisions`:

```python
    snapshot_every_decision: bool = False
    """Save the game and the loop's memory at every decision, for `jevplays branch` (#82)."""
```

In `Loop._record`, after the `if decision.model: ... set_model(...)` lines and still inside `if self.run_dir is not None:`, add:

```python
            if self.config.snapshot_every_decision:
                self.run_dir.snapshot(
                    self.emu,
                    self.decision_count,
                    {
                        "frame": self._game_clock(),
                        "milestone": self.milestone.id if self.milestone is not None else None,
                        "memory": self.memory.to_dict(),
                    },
                )
```

In `Loop._refresh_milestone`, inside `if previous is not None and (...):`, before the `publish` call, add:

```python
            if self.config.snapshot_every_decision and self.run_dir is not None:
                self.run_dir.note_milestone(previous.id, self._game_clock())
```

In `src/jevplays/cli.py`, in `build_parser`, after the `--no-log` argument:

```python
    run.add_argument(
        "--snapshot-every-decision",
        action="store_true",
        help="save the game at every decision so `jevplays branch` can replay it (about 170 KB each)",
    )
```

In `main`, after the existing `--no-log`/`--resume` check:

```python
    if getattr(args, "snapshot_every_decision", False) and (
        getattr(args, "resume", None) is not None or getattr(args, "no_log", False)
    ):
        parser.error("--snapshot-every-decision needs a fresh, logged run (no --resume, no --no-log)")
```

In `cmd_run`, add `"snapshot_every_decision": args.snapshot_every_decision,` to the `flags` dict, and `snapshot_every_decision=args.snapshot_every_decision,` to the `LoopConfig(...)` call.

- [ ] **Step 5: Run the tests**

Run: `mise exec -- uv run pytest tests/test_runlog_snapshots.py tests/test_cli.py tests/test_loop.py tests/test_imports.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/jevplays/runlog.py src/jevplays/loop.py src/jevplays/cli.py tests/test_runlog_snapshots.py tests/test_cli.py
git commit -m "feat(tooling): --snapshot-every-decision saves the game at each decision (#82)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: The measurement's SQLite store

**Files:**
- Create: `src/jevplays/branch/store.py`
- Test: `tests/test_branch_store.py`

**Interfaces:**
- Produces:
  - `BranchKey(NamedTuple)`: `decision: int`, `alternative: str`, `seed: int`
  - `@dataclass(frozen=True) BranchResult`: `outcome: str` (`done` | `capped` | `stalled` | `error`), `frames: int | None`, `blackouts: int`, `jev_calls: int`, `cache_hits: int`, `error: str | None = None`
  - `@dataclass(frozen=True) DecisionInfo`: `decision: int`, `kind: str`, `chosen: str`, `alternatives: list[str]`, `strongest: str | None`, `offline: str | None`, `reference_frames: int`
  - `class BranchStore(path: Path)` with: `set_meta(key, value: str)`, `meta() -> dict[str, str]`, `put_decision_info(info)`, `decision_infos() -> list[DecisionInfo]`, `skip(decision: int, reason: str)`, `skipped() -> dict[int, str]`, `done() -> set[BranchKey]`, `clear_partial(key)`, `add_decision(key, seq: int, body: dict)`, `branch_decisions(key) -> list[dict]`, `finish_branch(key, result)`, `branches(decision: int | None = None) -> list[tuple[BranchKey, BranchResult]]`, `get_response(key: str) -> tuple[dict, int] | None`, `put_response(key: str, response: dict, latency_ms: int, model: str)`
  - `class BranchSink(store, key)`: what a branch's `Loop` takes as `run_dir`

- [ ] **Step 1: Write the failing tests**

`tests/test_branch_store.py`:

```python
from jevplays.brain.decision import Decision
from jevplays.branch.store import BranchKey, BranchResult, BranchSink, BranchStore, DecisionInfo

KEY = BranchKey(12, "move:EMBER", 3)


def store(tmp_path):
    return BranchStore(tmp_path / "branches.sqlite")


def test_a_finished_branch_is_done_and_reads_back(tmp_path):
    s = store(tmp_path)
    result = BranchResult("done", 4200, 1, 17, 30)
    s.finish_branch(KEY, result)
    assert s.done() == {KEY}
    assert s.branches() == [(KEY, result)]
    assert s.branches(decision=13) == []


def test_a_second_process_sees_the_first_ones_writes(tmp_path):
    store(tmp_path).finish_branch(KEY, BranchResult("capped", None, 0, 1, 2))
    assert store(tmp_path).done() == {KEY}


def test_clear_partial_removes_an_unfinished_branchs_decisions(tmp_path):
    """Review focus 2: a branch killed halfway leaves decisions and no branch row."""
    s = store(tmp_path)
    s.add_decision(KEY, 1, {"id": "a"})
    s.add_decision(KEY, 2, {"id": "b"})
    assert KEY not in s.done()
    s.clear_partial(KEY)
    assert s.branch_decisions(KEY) == []
    s.add_decision(KEY, 1, {"id": "c"})
    assert s.branch_decisions(KEY) == [{"id": "c"}]


def test_responses_round_trip_and_the_first_write_wins(tmp_path):
    s = store(tmp_path)
    assert s.get_response("k") is None
    s.put_response("k", {"answers": {}, "model": "jev-1"}, 250, "jev-1")
    s.put_response("k", {"answers": {"x": 1}, "model": "jev-1"}, 999, "jev-1")
    assert s.get_response("k") == ({"answers": {}, "model": "jev-1"}, 250)


def test_meta_skips_and_decision_info(tmp_path):
    s = store(tmp_path)
    s.set_meta("seeds", "8")
    s.skip(4, "not reproducible: the rebuilt state summary differs from the logged one")
    info = DecisionInfo(12, "battle", "move:EMBER", ["move:EMBER", "run"], "move:EMBER", None, 5000)
    s.put_decision_info(info)
    assert s.meta() == {"seeds": "8"}
    assert s.skipped() == {4: "not reproducible: the rebuilt state summary differs from the logged one"}
    assert s.decision_infos() == [info]


def test_the_sink_numbers_and_stores_the_branchs_decisions(tmp_path):
    s = store(tmp_path)
    sink = BranchSink(s, KEY)
    d = Decision(id="x", ts=0.0, kind="battle", state_summary={}, questions={}, answers={}, action="use EMBER")
    assert sink.count() == 0
    assert sink.append(d) == 1
    assert sink.count() == 1
    assert sink.checkpoint(object(), 1) is None
    sink.set_model("jev-1")
    sink.save_memory({})
    sink.append_outcome({})
    assert s.branch_decisions(KEY)[0]["action"] == "use EMBER"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `mise exec -- uv run pytest tests/test_branch_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jevplays.branch.store'`.

- [ ] **Step 3: Implement**

`src/jevplays/branch/store.py`:

```python
"""Everything one branch measurement writes: `runs/<stamp>/branches/branches.sqlite`.

One file, in WAL mode, written by every branch process at once. A branch's decisions go in as it
makes them; its `branch` row goes in when it ends, so a (decision, alternative, seed) with a row
is finished and one without is not -- which is how an interrupted measurement resumes (spec:
"Storage")."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decision_info (
    decision INTEGER PRIMARY KEY, kind TEXT NOT NULL, chosen TEXT NOT NULL,
    alternatives TEXT NOT NULL, strongest TEXT, offline TEXT, reference_frames INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS skipped (decision INTEGER PRIMARY KEY, reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS branch (
    decision INTEGER NOT NULL, alternative TEXT NOT NULL, seed INTEGER NOT NULL,
    outcome TEXT NOT NULL, frames INTEGER, blackouts INTEGER NOT NULL,
    jev_calls INTEGER NOT NULL, cache_hits INTEGER NOT NULL, error TEXT, finished_at TEXT NOT NULL,
    PRIMARY KEY (decision, alternative, seed)
);
CREATE TABLE IF NOT EXISTS decision (
    decision INTEGER NOT NULL, alternative TEXT NOT NULL, seed INTEGER NOT NULL,
    seq INTEGER NOT NULL, body TEXT NOT NULL,
    PRIMARY KEY (decision, alternative, seed, seq)
);
CREATE TABLE IF NOT EXISTS response (
    key TEXT PRIMARY KEY, body TEXT NOT NULL, latency_ms INTEGER NOT NULL, model TEXT NOT NULL
);
"""


class BranchKey(NamedTuple):
    decision: int
    alternative: str
    seed: int


@dataclass(frozen=True)
class BranchResult:
    outcome: str  # done | capped | stalled | error
    frames: int | None
    blackouts: int
    jev_calls: int
    cache_hits: int
    error: str | None = None


@dataclass(frozen=True)
class DecisionInfo:
    decision: int
    kind: str
    chosen: str
    alternatives: list[str]
    strongest: str | None
    offline: str | None
    reference_frames: int


class BranchStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._db = sqlite3.connect(path, timeout=60, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    # -- meta, decisions measured, decisions skipped ------------------------------------

    def set_meta(self, key: str, value: str) -> None:
        self._db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))

    def meta(self) -> dict[str, str]:
        return dict(self._db.execute("SELECT key, value FROM meta"))

    def put_decision_info(self, info: DecisionInfo) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO decision_info VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                info.decision, info.kind, info.chosen, json.dumps(info.alternatives),
                info.strongest, info.offline, info.reference_frames,
            ),
        )

    def decision_infos(self) -> list[DecisionInfo]:
        rows = self._db.execute("SELECT * FROM decision_info ORDER BY decision")
        return [DecisionInfo(d, k, c, json.loads(a), s, o, r) for d, k, c, a, s, o, r in rows]

    def skip(self, decision: int, reason: str) -> None:
        self._db.execute("INSERT OR REPLACE INTO skipped VALUES (?, ?)", (decision, reason))

    def skipped(self) -> dict[int, str]:
        return dict(self._db.execute("SELECT decision, reason FROM skipped ORDER BY decision"))

    # -- branches -----------------------------------------------------------------------

    def done(self) -> set[BranchKey]:
        return {BranchKey(*row) for row in self._db.execute("SELECT decision, alternative, seed FROM branch")}

    def clear_partial(self, key: BranchKey) -> None:
        """Forget the decisions of a branch that never finished, so rerunning it starts clean."""
        self._db.execute(
            "DELETE FROM decision WHERE decision = ? AND alternative = ? AND seed = ?", tuple(key)
        )

    def add_decision(self, key: BranchKey, seq: int, body: dict) -> None:
        self._db.execute(
            "INSERT INTO decision VALUES (?, ?, ?, ?, ?)",
            (*key, seq, json.dumps(body, ensure_ascii=False)),
        )

    def branch_decisions(self, key: BranchKey) -> list[dict]:
        rows = self._db.execute(
            "SELECT body FROM decision WHERE decision = ? AND alternative = ? AND seed = ? ORDER BY seq",
            tuple(key),
        )
        return [json.loads(body) for (body,) in rows]

    def finish_branch(self, key: BranchKey, result: BranchResult) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO branch VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                *key, result.outcome, result.frames, result.blackouts, result.jev_calls,
                result.cache_hits, result.error, datetime.now().isoformat(timespec="seconds"),
            ),
        )

    def branches(self, decision: int | None = None) -> list[tuple[BranchKey, BranchResult]]:
        sql = (
            "SELECT decision, alternative, seed, outcome, frames, blackouts, jev_calls, cache_hits, error "
            "FROM branch"
        )
        args: tuple = ()
        if decision is not None:
            sql += " WHERE decision = ?"
            args = (decision,)
        sql += " ORDER BY decision, alternative, seed"
        return [
            (BranchKey(d, a, s), BranchResult(o, f, b, c, h, e))
            for d, a, s, o, f, b, c, h, e in self._db.execute(sql, args)
        ]

    # -- the response cache (brain/cache.py's store) ------------------------------------

    def get_response(self, key: str) -> tuple[dict, int] | None:
        row = self._db.execute("SELECT body, latency_ms FROM response WHERE key = ?", (key,)).fetchone()
        return (json.loads(row[0]), row[1]) if row else None

    def put_response(self, key: str, response: dict, latency_ms: int, model: str) -> None:
        self._db.execute(
            "INSERT OR IGNORE INTO response VALUES (?, ?, ?, ?)",
            (key, json.dumps(response, ensure_ascii=False), latency_ms, model),
        )


class BranchSink:
    """What a branch's `Loop` writes through in place of a `RunDir`: its decisions go to the store
    under the branch's key; checkpoints, memory and faint outcomes are not kept."""

    def __init__(self, store: BranchStore, key: BranchKey) -> None:
        self.store = store
        self.key = key
        self._n = 0

    def count(self) -> int:
        return self._n

    def append(self, decision) -> int:
        self._n += 1
        self.store.add_decision(self.key, self._n, decision.to_dict())
        return self._n

    def set_model(self, model: str) -> None:
        pass

    def checkpoint(self, emu, n: int) -> None:
        return None

    def save_memory(self, d: dict) -> None:
        pass

    def append_outcome(self, outcome: dict) -> None:
        pass
```

- [ ] **Step 4: Run the tests**

Run: `mise exec -- uv run pytest tests/test_branch_store.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/branch/store.py tests/test_branch_store.py
git commit -m "feat(tooling): one SQLite file holds a branch measurement (#82)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: The response cache

**Files:**
- Create: `src/jevplays/brain/cache.py`
- Test: `tests/test_brain_cache.py`

**Interfaces:**
- Consumes: `BranchStore.get_response` / `put_response` (Task 4), through a structural protocol.
- Produces: `cache_key(model: str, state: dict, questions: dict) -> str`; `class ModelDrift(RuntimeError)`; `class CachedBrain(inner, store, *, expected_model: str | None)` with `model: str`, `calls: int`, `hits: int`, `async ask(state, questions) -> tuple[dict, int]`, `async close()`.

- [ ] **Step 1: Write the failing tests**

`tests/test_brain_cache.py`:

```python
import asyncio

import pytest

from jevplays.brain.cache import CachedBrain, ModelDrift, cache_key


class DictStore:
    def __init__(self):
        self.rows = {}

    def get_response(self, key):
        return self.rows.get(key)

    def put_response(self, key, response, latency_ms, model):
        self.rows.setdefault(key, (response, latency_ms))


class Inner:
    model = "jev-latest"

    def __init__(self, reported="jev-1.13.0"):
        self.calls = 0
        self.reported = reported
        self.closed = False

    async def ask(self, state, questions):
        self.calls += 1
        return {"model": self.reported, "answers": {"n": self.calls}}, 300

    async def close(self):
        self.closed = True


Q = {"run": {"type": "noul", "instructions": "Run?"}}


def test_the_second_identical_ask_is_served_from_the_store_and_marked_cached():
    inner, store = Inner(), DictStore()
    brain = CachedBrain(inner, store, expected_model="jev-1.13.0")
    first, _ = asyncio.run(brain.ask({"hp": "low"}, Q))
    second, latency = asyncio.run(brain.ask({"hp": "low"}, Q))
    assert inner.calls == 1 and brain.calls == 1 and brain.hits == 1
    assert second == {**first, "cached": True} and latency == 300
    assert "cached" not in first


def test_the_key_changes_with_model_state_and_questions():
    base = cache_key("jev-latest", {"hp": "low"}, Q)
    assert base == cache_key("jev-latest", {"hp": "low"}, dict(Q))
    assert base != cache_key("jev-other", {"hp": "low"}, Q)
    assert base != cache_key("jev-latest", {"hp": "high"}, Q)
    assert base != cache_key("jev-latest", {"hp": "low"}, {"catch": Q["run"]})


def test_a_different_model_than_the_run_used_stops_the_measurement():
    brain = CachedBrain(Inner(reported="jev-2.0.0"), DictStore(), expected_model="jev-1.13.0")
    with pytest.raises(ModelDrift, match="jev-2.0.0"):
        asyncio.run(brain.ask({}, Q))


def test_close_closes_the_inner_brain():
    inner = Inner()
    asyncio.run(CachedBrain(inner, DictStore(), expected_model=None).close())
    assert inner.closed


def test_close_tolerates_a_brain_with_nothing_to_close():
    class Bare:
        async def ask(self, state, questions):
            return {}, 0

    asyncio.run(CachedBrain(Bare(), DictStore(), expected_model=None).close())
```

- [ ] **Step 2: Run them and watch them fail**

Run: `mise exec -- uv run pytest tests/test_brain_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jevplays.brain.cache'`.

- [ ] **Step 3: Implement**

`src/jevplays/brain/cache.py`:

```python
"""A brain that remembers its answers, for branch measurements (#82).

Jev sees buckets, not numbers, so branches of one decision keep putting the same question to it.
`CachedBrain` wraps the real brain, has the same `ask`, and answers a repeated input from the
store. The loop cannot tell the difference, and the SDK stays in `brain/client.py`."""

import hashlib
import json
from typing import Protocol


class ResponseStore(Protocol):
    def get_response(self, key: str) -> tuple[dict, int] | None: ...

    def put_response(self, key: str, response: dict, latency_ms: int, model: str) -> None: ...


class ModelDrift(RuntimeError):
    """A live answer came from a different model than the run being measured used, so branches
    would compare two versions of Jev. The measurement stops rather than mix them."""


def cache_key(model: str, state: dict, questions: dict) -> str:
    blob = json.dumps(
        {"model": model, "state": state, "questions": questions},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class CachedBrain:
    def __init__(self, inner, store: ResponseStore, *, expected_model: str | None) -> None:
        self.inner = inner
        self.store = store
        self.expected_model = expected_model or None
        self.model = getattr(inner, "model", "")
        self.calls = 0
        self.hits = 0

    async def ask(self, state: dict, questions: dict) -> tuple[dict, int]:
        key = cache_key(self.model, state, questions)
        hit = self.store.get_response(key)
        if hit is not None:
            self.hits += 1
            response, latency_ms = hit
            return {**response, "cached": True}, latency_ms
        response, latency_ms = await self.inner.ask(state, questions)
        self.calls += 1
        reported = response.get("model", "")
        if self.expected_model and reported and reported != self.expected_model:
            raise ModelDrift(f"the run used {self.expected_model}; this answer came from {reported}")
        self.store.put_response(key, response, latency_ms, reported)
        return response, latency_ms

    async def close(self) -> None:
        close = getattr(self.inner, "close", None)
        if close is not None:
            await close()
```

`close` is optional because the ROM tests' stand-in brain (`FirstChoiceBrain`) has none.

- [ ] **Step 4: Run the tests, and the import boundary test**

Run: `mise exec -- uv run pytest tests/test_brain_cache.py tests/test_imports.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/brain/cache.py tests/test_brain_cache.py
git commit -m "feat(brain): a caching brain for branch measurements (#82)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Alternatives, the fidelity check, and the baseline picks

**Files:**
- Create: `src/jevplays/branch/alternatives.py`
- Test: `tests/test_branch_alternatives.py`

**Interfaces:**
- Consumes: `snapshot`, `battle_state`, `bench_slots`, `explore_state`, `generate`, `Memory`, `MILESTONES`, `battle_goal`, `Loop._offline_option`.
- Produces:
  - `@dataclass(frozen=True) Alternative`: `key: str`, `action: BattleAction | ExploreAction`, `power: int | None = None`
  - `battle_alternatives(state: GameState) -> list[Alternative]`
  - `explore_alternatives(options: list[Option]) -> list[Alternative]`
  - `chosen_key(alternatives, logged_action: str) -> str | None`
  - `strongest_move(alternatives) -> str | None`
  - `goal_by_id(milestone: str | None) -> Goal | None`
  - `class NotReproducible(Exception)`
  - `@dataclass(frozen=True) Prepared`: `kind: str`, `chosen: str`, `alternatives: list[Alternative]`, `strongest: str | None`, `offline: str | None`
  - `prepare(emu, logged: dict, sidecar: dict, *, fallback_goal: str) -> Prepared`: raises `NotReproducible`
  - Keys: `move:<NAME>`, `switch:<label>`, `heal`, `run`, `catch`, `explore:<option id>`

- [ ] **Step 1: Write the failing tests**

`tests/test_branch_alternatives.py`:

```python
import json
from dataclasses import replace

import pytest

from jevplays.brain.battle import battle_state
from jevplays.brain.explore import explore_state
from jevplays.branch.alternatives import (
    NotReproducible,
    battle_alternatives,
    chosen_key,
    explore_alternatives,
    goal_by_id,
    prepare,
    strongest_move,
)
from jevplays.executor.goals import MILESTONES, battle_goal
from jevplays.executor.options import Memory, generate
from jevplays.state.snapshot import BagItem, Battle, Move, snapshot
from tests.test_loop import battle_emu, explore_emu

FALLBACK = "Win every battle and explore"


def battle(**changes):
    return replace(snapshot(battle_emu()), **changes)


def keys(alts):
    return [a.key for a in alts]


def test_a_wild_battle_with_an_empty_bag_offers_the_moves_and_run():
    assert keys(battle_alternatives(battle())) == ["move:SCRATCH", "move:GROWL", "run"]


def test_a_trainer_battle_offers_no_run_and_no_catch():
    state = battle(battle=Battle(kind="trainer", trainer_class="RIVAL1"), bag=(BagItem("POKE BALL", 5),))
    assert "run" not in keys(battle_alternatives(state)) and "catch" not in keys(battle_alternatives(state))


def test_balls_and_potions_add_catch_and_heal_but_heal_needs_missing_hp():
    bag = (BagItem("POKE BALL", 5), BagItem("POTION", 1))
    full = battle(bag=bag)
    assert "catch" in keys(battle_alternatives(full)) and "heal" not in keys(battle_alternatives(full))
    hurt = battle(bag=bag, active=replace(full.active, hp=3))
    assert "heal" in keys(battle_alternatives(hurt))


def test_a_move_with_no_pp_is_left_out_unless_every_move_is_out():
    state = battle()
    no_scratch = replace(state.active, moves=(replace(state.active.moves[0], pp=0), state.active.moves[1]))
    assert keys(battle_alternatives(replace(state, active=no_scratch)))[:1] == ["move:GROWL"]
    all_out = replace(state.active, moves=tuple(replace(m, pp=0) for m in state.active.moves))
    assert keys(battle_alternatives(replace(state, active=all_out)))[:2] == ["move:SCRATCH", "move:GROWL"]


def test_a_living_bench_member_is_a_switch_and_a_fainted_one_is_not():
    extra = dict(species=16, level=8, hp=14, max_hp=14, types=(0, 0), moves=(33,), pps=(35,), nickname="PIDGEY")
    alive = snapshot(battle_emu(party_extra=extra))
    assert "switch:PIDGEY" in keys(battle_alternatives(alive))
    fainted = snapshot(battle_emu(party_extra={**extra, "hp": 0}))
    assert not any(k.startswith("switch:") for k in keys(battle_alternatives(fainted)))


def test_chosen_key_matches_the_logged_action_text():
    alts = battle_alternatives(battle())
    assert chosen_key(alts, "use GROWL") == "move:GROWL"
    assert chosen_key(alts, "throw a Poké Ball") is None


def test_the_strongest_move_is_the_highest_power_attack():
    alts = battle_alternatives(battle())
    assert strongest_move(alts) == "move:SCRATCH"
    status_only = battle(active=replace(battle().active, moves=(Move("GROWL", "Normal", 0, 40, 40),)))
    assert strongest_move(battle_alternatives(status_only)) is None


def logged_battle(emu, action="use SCRATCH", milestone=None):
    state = snapshot(emu)
    sj = battle_state(state, goal=battle_goal(goal_by_id(milestone), fallback=FALLBACK))
    return {"kind": "battle", "state_summary": json.loads(json.dumps(sj)), "action": action}


def test_prepare_accepts_a_battle_that_rebuilds_exactly():
    emu = battle_emu()
    prepared = prepare(emu, logged_battle(emu), {"milestone": None, "memory": {}}, fallback_goal=FALLBACK)
    assert prepared.kind == "battle" and prepared.chosen == "move:SCRATCH"
    assert prepared.strongest == "move:SCRATCH" and prepared.offline is None


def test_prepare_rejects_a_rebuilt_summary_that_differs():
    emu = battle_emu()
    logged = logged_battle(emu)
    logged["state_summary"]["party"] = "two"
    with pytest.raises(NotReproducible, match="differs"):
        prepare(emu, logged, {"milestone": None, "memory": {}}, fallback_goal=FALLBACK)


def test_prepare_rejects_an_action_that_is_not_an_alternative():
    emu = battle_emu()
    with pytest.raises(NotReproducible, match="not among"):
        prepare(emu, logged_battle(emu, action="throw a Poké Ball"), {"milestone": None, "memory": {}}, fallback_goal=FALLBACK)


def test_prepare_uses_the_sidecars_milestone_for_the_battle_goal():
    emu = battle_emu()
    logged = logged_battle(emu, milestone="get_pokedex")
    with pytest.raises(NotReproducible):
        prepare(emu, logged, {"milestone": None, "memory": {}}, fallback_goal=FALLBACK)
    assert prepare(emu, logged, {"milestone": "get_pokedex", "memory": {}}, fallback_goal=FALLBACK).chosen


def test_prepare_an_explore_decision_lists_every_option_and_the_offline_pick():
    emu = explore_emu()
    state = snapshot(emu)
    milestone = MILESTONES[1]
    options = generate(emu, state, Memory.empty(), milestone)
    sj = json.loads(json.dumps(explore_state(state, options, milestone)))
    logged = {"kind": "explore", "state_summary": sj, "action": f"explore: {options[-1].text}"}
    prepared = prepare(emu, logged, {"milestone": milestone.id, "memory": Memory.empty().to_dict()}, fallback_goal=FALLBACK)
    assert keys(prepared.alternatives) == [f"explore:{o.id}" for o in options]
    assert prepared.chosen == f"explore:{options[-1].id}"
    assert prepared.offline is not None and prepared.offline.startswith("explore:")
    assert explore_alternatives(options)[0].action.option_id == options[0].id
```

- [ ] **Step 2: Run them and watch them fail**

Run: `mise exec -- uv run pytest tests/test_branch_alternatives.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jevplays.branch.alternatives'`.

- [ ] **Step 3: Implement**

`src/jevplays/branch/alternatives.py`:

```python
"""What else Jev could have done at a decision, and whether a snapshot rebuilds that decision.

The alternatives are game rules -- which actions the battle menu accepts, which options the map
generates -- so code lists them (spec: "Alternatives"). Nothing here is shown to Jev."""

import json
from dataclasses import dataclass

from jevplays.brain.battle import battle_state, bench_slots
from jevplays.brain.buckets import pp_bucket
from jevplays.brain.decision import BattleAction, ExploreAction
from jevplays.brain.explore import explore_state
from jevplays.executor.goals import MILESTONES, Goal, battle_goal
from jevplays.executor.options import Memory, Option, generate
from jevplays.state.modes import Mode
from jevplays.state.snapshot import GameState, snapshot


@dataclass(frozen=True)
class Alternative:
    key: str
    action: BattleAction | ExploreAction
    power: int | None = None
    """A move's power, for the strongest-move baseline. Code only; Jev never sees it."""


class NotReproducible(Exception):
    """The snapshot does not rebuild the decision Jev saw, so nothing is branched from it."""


@dataclass(frozen=True)
class Prepared:
    kind: str
    chosen: str
    alternatives: list[Alternative]
    strongest: str | None
    offline: str | None


def _has(state: GameState, item: str) -> bool:
    return any(i.name == item and i.quantity > 0 for i in state.bag)


def battle_alternatives(state: GameState) -> list[Alternative]:
    """Every action the battle menu would accept, in the order moves, switches, heal, run, catch."""
    assert state.active is not None and state.battle is not None
    moves = [m for m in state.active.moves if pp_bucket(m.pp) != "out"] or list(state.active.moves)
    alts = [Alternative(f"move:{m.name}", BattleAction(kind="move", move=m.name), power=m.power) for m in moves]
    alts += [
        Alternative(f"switch:{label}", BattleAction(kind="switch", target=label))
        for label, _slot in bench_slots(state)
    ]
    if _has(state, "POTION") and state.active.hp < state.active.max_hp:
        alts.append(Alternative("heal", BattleAction(kind="heal")))
    if state.battle.kind == "wild":
        alts.append(Alternative("run", BattleAction(kind="run")))
        if _has(state, "POKE BALL"):
            alts.append(Alternative("catch", BattleAction(kind="catch")))
    return alts


def explore_alternatives(options: list[Option]) -> list[Alternative]:
    return [
        Alternative(f"explore:{o.id}", ExploreAction(option_id=o.id, kind=o.kind, text=o.text))
        for o in options
    ]


def chosen_key(alternatives: list[Alternative], logged_action: str) -> str | None:
    """The alternative whose action text is what the log recorded, or None."""
    return next((a.key for a in alternatives if a.action.describe() == logged_action), None)


def strongest_move(alternatives: list[Alternative]) -> str | None:
    attacks = [a for a in alternatives if a.key.startswith("move:") and (a.power or 0) > 0]
    return max(attacks, key=lambda a: a.power).key if attacks else None


def goal_by_id(milestone: str | None) -> Goal | None:
    return next((g for g in MILESTONES if g.id == milestone), None)


def _as_logged(sj: dict) -> dict:
    """The summary as it reads back from decisions.jsonl: tuples become lists."""
    return json.loads(json.dumps(sj, ensure_ascii=False))


def prepare(emu, logged: dict, sidecar: dict, *, fallback_goal: str) -> Prepared:
    """Rebuild decision `logged` from the loaded snapshot and list its alternatives. Raises
    NotReproducible when the rebuilt state summary differs from the logged one or Jev's logged
    action is not among the alternatives."""
    from jevplays.loop import Loop

    state = snapshot(emu)
    milestone = goal_by_id(sidecar.get("milestone"))
    offline = strongest = None
    if logged["kind"] == "battle":
        if state.mode is not Mode.BATTLE_MENU:
            raise NotReproducible(f"not reproducible: the snapshot is at {state.mode.name}, not the battle menu")
        sj = battle_state(state, goal=battle_goal(milestone, fallback=fallback_goal))
        alternatives = battle_alternatives(state)
        strongest = strongest_move(alternatives)
    elif logged["kind"] == "explore":
        options = generate(emu, state, Memory.from_dict(sidecar.get("memory", {})), milestone)
        sj = explore_state(state, options, milestone)
        alternatives = explore_alternatives(options)
        if options:
            offline = f"explore:{Loop._offline_option(options).id}"
    else:
        raise NotReproducible(f"not branched: {logged['kind']} decisions are out of scope")
    if _as_logged(sj) != logged["state_summary"]:
        raise NotReproducible("not reproducible: the rebuilt state summary differs from the logged one")
    chosen = chosen_key(alternatives, logged["action"])
    if chosen is None:
        raise NotReproducible(f"not reproducible: {logged['action']!r} is not among the alternatives")
    return Prepared(logged["kind"], chosen, alternatives, strongest, offline)
```

`prepare` imports `Loop` inside the function because `jevplays.loop` is heavy and `branch.alternatives` is imported by the report script.

- [ ] **Step 4: Run the tests**

Run: `mise exec -- uv run pytest tests/test_branch_alternatives.py -v`
Expected: all pass. The bench fixture is the same `party_extra` that `tests/test_loop.py`'s switch test uses.

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/branch/alternatives.py tests/test_branch_alternatives.py
git commit -m "feat(tooling): list a decision's alternatives and check its snapshot rebuilds it (#82)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: When a branch stops

**Files:**
- Create: `src/jevplays/branch/stop.py`
- Test: `tests/test_branch_stop.py`

**Interfaces:**
- Produces: `STALL_FRAMES = 20_000`; `CAP_FACTOR = 3`; `MIN_CAP_FRAMES = 3_600`; `cap_for(reference_frames: int) -> int`; `class Stopper(target: str, cap_frames: int, stall_frames: int = STALL_FRAMES)`, callable as `stopper(loop, state) -> str | None`, with a `blackouts: int` attribute.

- [ ] **Step 1: Write the failing tests**

`tests/test_branch_stop.py`:

```python
from dataclasses import replace
from types import SimpleNamespace

from jevplays.branch.stop import MIN_CAP_FRAMES, STALL_FRAMES, Stopper, cap_for
from jevplays.executor.goals import MILESTONES
from tests.support import OVERWORLD_LEAD, overworld_state

POKEDEX, BROCK = MILESTONES[1], MILESTONES[2]
ALIVE = overworld_state()
DOWN = overworld_state(party=(replace(OVERWORLD_LEAD, hp=0),))


def loop(frames=0, milestone=POKEDEX, decisions=0, finished=False):
    return SimpleNamespace(game_frames=frames, milestone=milestone, decisions=[None] * decisions, finished=finished)


def test_the_cap_is_three_times_the_reference_with_a_one_minute_floor():
    assert cap_for(10_000) == 30_000
    assert cap_for(100) == MIN_CAP_FRAMES


def test_done_when_the_target_milestone_is_no_longer_the_active_one():
    stop = Stopper("get_pokedex", cap_frames=50_000)
    assert stop(loop(milestone=POKEDEX), ALIVE) is None
    assert stop(loop(milestone=BROCK), ALIVE) == "done"
    assert Stopper("beat_brock", 50_000)(loop(milestone=None, finished=True), ALIVE) == "done"


def test_capped_at_the_cap():
    stop = Stopper("get_pokedex", cap_frames=1000)
    assert stop(loop(frames=999, decisions=1), ALIVE) is None
    assert stop(loop(frames=1000, decisions=2), ALIVE) == "capped"


def test_stalled_after_too_long_with_no_new_decision():
    stop = Stopper("get_pokedex", cap_frames=10**9)
    assert stop(loop(frames=0, decisions=1), ALIVE) is None
    assert stop(loop(frames=STALL_FRAMES - 1, decisions=1), ALIVE) is None
    assert stop(loop(frames=STALL_FRAMES, decisions=1), ALIVE) == "stalled"


def test_a_new_decision_resets_the_stall_clock():
    stop = Stopper("get_pokedex", cap_frames=10**9)
    stop(loop(frames=0, decisions=1), ALIVE)
    stop(loop(frames=STALL_FRAMES - 1, decisions=2), ALIVE)
    assert stop(loop(frames=STALL_FRAMES + 10, decisions=2), ALIVE) is None


def test_a_blackout_is_counted_once_per_whole_party_down():
    stop = Stopper("get_pokedex", cap_frames=10**9)
    for state in (ALIVE, DOWN, DOWN, ALIVE, DOWN):
        stop(loop(decisions=1), state)
    assert stop.blackouts == 2
```

- [ ] **Step 2: Run them and watch them fail**

Run: `mise exec -- uv run pytest tests/test_branch_stop.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/jevplays/branch/stop.py`:

```python
"""When a branch ends (spec: "When a branch stops"). Counted in game frames throughout, never
wall-clock time (#61)."""

CAP_FACTOR = 3
"""A branch may spend this many times the frames the logged run took to the same milestone."""
MIN_CAP_FRAMES = 3_600
"""One game minute: the smallest cap, so a decision just before its milestone is not capped
before any alternative could get there."""
STALL_FRAMES = 20_000
"""Game frames with no new decision before a branch is called stalled: the #67 hang."""


def cap_for(reference_frames: int) -> int:
    return max(CAP_FACTOR * reference_frames, MIN_CAP_FRAMES)


class Stopper:
    """The `stop` a branch's Loop is given. Returns "done", "capped" or "stalled" to end the run,
    None to go on, and counts blackouts along the way."""

    def __init__(self, target: str, cap_frames: int, stall_frames: int = STALL_FRAMES) -> None:
        self.target = target
        self.cap_frames = cap_frames
        self.stall_frames = stall_frames
        self.blackouts = 0
        self._down = False
        self._seen = -1
        self._last_decision_at = 0

    def __call__(self, loop, state) -> str | None:
        if loop.finished or (loop.milestone is not None and loop.milestone.id != self.target):
            return "done"
        down = bool(state.party) and all(m.hp == 0 for m in state.party)
        if down and not self._down:
            self.blackouts += 1
        self._down = down
        if len(loop.decisions) != self._seen:
            self._seen = len(loop.decisions)
            self._last_decision_at = loop.game_frames
        if loop.game_frames >= self.cap_frames:
            return "capped"
        if loop.game_frames - self._last_decision_at >= self.stall_frames:
            return "stalled"
        return None
```

- [ ] **Step 4: Run the tests**

Run: `mise exec -- uv run pytest tests/test_branch_stop.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/jevplays/branch/stop.py tests/test_branch_stop.py
git commit -m "feat(tooling): a branch stops at its milestone, its cap, or a stall (#82)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Running branches, and `jevplays branch`

**Files:**
- Create: `src/jevplays/branch/runner.py`
- Modify: `src/jevplays/cli.py` (`branch` subcommand)
- Test: `tests/test_branch_runner.py`

**Interfaces:**
- Consumes: everything from Tasks 2–7.
- Produces:
  - `@dataclass(frozen=True) Candidate`: `n: int`, `logged: dict`, `sidecar: dict`, `state: Path`, `reference_frames: int | None`
  - `candidates(run_dir: RunDir) -> list[Candidate]`: raises `FileNotFoundError` when the run has no snapshots
  - `@dataclass(frozen=True) Job`: `rom: Path`, `state: Path`, `memory: dict`, `milestone: str`, `key: BranchKey`, `action: BattleAction | ExploreAction`, `cap_frames: int`, `db: Path`, `model: str`, `battle_goal: str`
  - `run_branch(job: Job, brain_factory=None) -> BranchResult`
  - `measure(run_path: Path, *, rom: Path, seeds: int, sample: int | None, workers: int) -> int`: an exit code
  - `class SeedsMismatch(ValueError)`
  - CLI: `jevplays branch RUN_DIR [--rom] [--seeds 8] [--sample N] [--workers N]`

- [ ] **Step 1: Write the failing tests**

`tests/test_branch_runner.py`:

```python
import json

import pytest

from jevplays.brain.decision import Decision
from jevplays.branch.runner import SeedsMismatch, candidates, check_seeds
from jevplays.branch.store import BranchStore
from jevplays.runlog import RunDir
from tests.support import FakeEmulator


def decision(kind="battle", fallback=False, questions=True, forced=False):
    return Decision(
        id="x", ts=0.0, kind=kind, state_summary={}, questions={"q": {}} if questions else {},
        answers={}, action="use EMBER", fallback=fallback, forced=forced,
    )


def recorded(tmp_path, decisions, frames, milestone_done=None):
    run = RunDir.create(tmp_path, rom=None, flags={})
    for n, (d, frame) in enumerate(zip(decisions, frames, strict=True), start=1):
        run.append(d)
        run.snapshot(FakeEmulator(), n, {"frame": frame, "milestone": "get_pokedex", "memory": {}})
    if milestone_done is not None:
        run.note_milestone("get_pokedex", milestone_done)
    return run


def test_candidates_are_jevs_battle_and_explore_decisions_with_their_reference(tmp_path):
    ds = [decision(), decision("explore"), decision("prompt"), decision(fallback=True), decision(questions=False)]
    run = recorded(tmp_path, ds, [100, 200, 300, 400, 500], milestone_done=1100)
    got = candidates(run)
    assert [c.n for c in got] == [1, 2]
    assert [c.reference_frames for c in got] == [1000, 900]
    assert got[0].state == run.snapshot_state(1)


def test_a_milestone_the_run_never_finished_leaves_no_reference(tmp_path):
    run = recorded(tmp_path, [decision()], [100])
    assert candidates(run)[0].reference_frames is None


def test_a_run_recorded_without_snapshots_is_refused(tmp_path):
    """Review focus 5."""
    run = RunDir.create(tmp_path, rom=None, flags={})
    run.append(decision())
    with pytest.raises(FileNotFoundError, match="--snapshot-every-decision"):
        candidates(run)


def test_a_measurement_refuses_a_different_seed_count(tmp_path):
    """Review focus 4."""
    store = BranchStore(tmp_path / "b.sqlite")
    check_seeds(store, 8)
    assert store.meta()["seeds"] == "8"
    check_seeds(store, 8)
    with pytest.raises(SeedsMismatch, match="8"):
        check_seeds(store, 4)


def test_the_branch_command_needs_an_api_key(tmp_path, monkeypatch, capsys):
    from jevplays.cli import main

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    rom = tmp_path / "rom.gb"
    rom.write_bytes(b"")
    assert main(["branch", str(tmp_path), "--rom", str(rom)]) == 2
    assert "TYPESAFE_API_KEY" in capsys.readouterr().err
```

- [ ] **Step 2: Run them and watch them fail**

Run: `mise exec -- uv run pytest tests/test_branch_runner.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the runner**

`src/jevplays/branch/runner.py`:

```python
"""`jevplays branch`: rebuild each decision of a recorded run, then play every alternative from it
(spec: "Shape"). The parent process prepares decisions with one emulator; each branch runs in a
worker process with an emulator of its own."""

import asyncio
import random
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from multiprocessing import get_context
from pathlib import Path

from jevplays.brain.decision import BattleAction, ExploreAction
from jevplays.branch.alternatives import NotReproducible, goal_by_id, prepare
from jevplays.branch.stop import Stopper, cap_for
from jevplays.branch.store import BranchKey, BranchResult, BranchSink, BranchStore, DecisionInfo
from jevplays.runlog import RunDir

BRANCHED_KINDS = ("battle", "explore")
DEFAULT_GOAL = "Win every battle and explore"
"""`LoopConfig.goal`'s default, for a run.json from before `battle_goal` was a flag."""


class SeedsMismatch(ValueError):
    pass


@dataclass(frozen=True)
class Candidate:
    n: int
    logged: dict
    sidecar: dict
    state: Path
    reference_frames: int | None


@dataclass(frozen=True)
class Job:
    rom: Path
    state: Path
    memory: dict
    milestone: str
    key: BranchKey
    action: BattleAction | ExploreAction
    cap_frames: int
    db: Path
    model: str
    battle_goal: str


class _Quiet:
    async def publish(self, event: dict) -> None:
        pass


def candidates(run_dir: RunDir) -> list[Candidate]:
    """Every battle and explore decision Jev made (not a fallback, not forced), with its snapshot
    and the frames the logged run took from it to its milestone (None if it never got there)."""
    if not run_dir.snapshots_path.is_dir():
        raise FileNotFoundError(f"{run_dir.path} has no snapshots; record it with --snapshot-every-decision")
    done = run_dir.milestones_done()
    out = []
    for n, logged in enumerate(run_dir.decisions(), start=1):
        if logged["kind"] not in BRANCHED_KINDS or logged.get("fallback") or logged.get("forced"):
            continue
        if not logged.get("questions"):
            continue
        sidecar, state = run_dir.snapshot_info(n), run_dir.snapshot_state(n)
        if sidecar is None or state is None:
            continue
        finished = done.get(sidecar.get("milestone") or "")
        reference = finished - sidecar["frame"] if finished is not None and finished >= sidecar["frame"] else None
        out.append(Candidate(n, logged, sidecar, state, reference))
    return out


def check_seeds(store: BranchStore, seeds: int) -> None:
    recorded = store.meta().get("seeds")
    if recorded is not None and int(recorded) != seeds:
        raise SeedsMismatch(f"this measurement was started with --seeds {recorded}; rerun with that")
    store.set_meta("seeds", str(seeds))


def run_branch(job: Job, brain_factory=None) -> BranchResult:
    """Play one branch to its end and record it. Runs in a worker process."""
    from jevplays.brain.cache import CachedBrain
    from jevplays.emulator.pyboy import Emulator
    from jevplays.executor.options import Memory
    from jevplays.loop import ForcedActionMissed, Loop, LoopConfig

    if brain_factory is None:
        from jevplays.brain.client import Brain

        brain_factory = Brain
    store = BranchStore(job.db)
    store.clear_partial(job.key)
    brain = CachedBrain(brain_factory(), store, expected_model=job.model)
    stopper = Stopper(job.milestone, job.cap_frames)
    try:
        with Emulator(job.rom) as emu:
            emu.load(job.state)
            loop = Loop(
                emu,
                _Quiet(),
                LoopConfig(paced=False, fps=1e-9, goal=job.battle_goal),
                brain=brain,
                run_dir=BranchSink(store, job.key),
                memory=Memory.from_dict(job.memory),
                forced=job.action,
                forced_delay=job.key.seed,
                stop=stopper,
            )
            loop.milestone = goal_by_id(job.milestone)
            try:
                asyncio.run(loop.run())
                outcome = "done" if loop.finished else (loop.stop_reason or "stalled")
                result = BranchResult(
                    outcome,
                    loop.game_frames if outcome == "done" else None,
                    stopper.blackouts,
                    brain.calls,
                    brain.hits,
                )
            except ForcedActionMissed as error:
                result = BranchResult("error", None, stopper.blackouts, brain.calls, brain.hits, str(error))
    finally:
        asyncio.run(brain.close())
    store.finish_branch(job.key, result)
    store.close()
    return result


def measure(run_path: Path, *, rom: Path, seeds: int, sample: int | None, workers: int) -> int:
    from jevplays.emulator.pyboy import Emulator

    run_dir = RunDir.open(run_path)
    try:
        found = candidates(run_dir)
    except FileNotFoundError as error:
        print(f"jevplays branch: {error}", file=sys.stderr)
        return 2
    if sample is not None and sample < len(found):
        found = sorted(random.Random(0).sample(found, sample), key=lambda c: c.n)
    db = run_path / "branches" / "branches.sqlite"
    store = BranchStore(db)
    try:
        check_seeds(store, seeds)
    except SeedsMismatch as error:
        print(f"jevplays branch: {error}", file=sys.stderr)
        return 2
    info = run_dir.info()
    model = info.get("model", "")
    goal = info.get("flags", {}).get("battle_goal") or DEFAULT_GOAL
    store.set_meta("run", str(run_path))
    store.set_meta("model", model)
    done = store.done()
    jobs: list[Job] = []
    with Emulator(rom) as emu:
        for c in found:
            if c.reference_frames is None:
                store.skip(c.n, "no reference: the logged run never finished this milestone")
                continue
            emu.load(c.state)
            try:
                prepared = prepare(emu, c.logged, c.sidecar, fallback_goal=goal)
            except NotReproducible as error:
                store.skip(c.n, str(error))
                continue
            store.put_decision_info(
                DecisionInfo(
                    c.n, prepared.kind, prepared.chosen, [a.key for a in prepared.alternatives],
                    prepared.strongest, prepared.offline, c.reference_frames,
                )
            )
            for alt in prepared.alternatives:
                for seed in range(seeds):
                    key = BranchKey(c.n, alt.key, seed)
                    if key in done:
                        continue
                    jobs.append(
                        Job(rom, c.state, c.sidecar["memory"], c.sidecar["milestone"], key, alt.action,
                            cap_for(c.reference_frames), db, model, goal)
                    )
    print(f"branch: {len(found)} decisions, {len(jobs)} branches to run, {len(done)} already done", flush=True)
    with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as pool:
        futures = {pool.submit(run_branch, job): job for job in jobs}
        for i, future in enumerate(as_completed(futures), start=1):
            job = futures[future]
            try:
                result = future.result()
            except Exception as error:
                print(f"jevplays branch: {job.key} failed: {error}", file=sys.stderr)
                pool.shutdown(wait=True, cancel_futures=True)
                return 1
            print(f"[{i}/{len(jobs)}] {job.key.decision} {job.key.alternative} seed {job.key.seed}: "
                  f"{result.outcome} {result.frames or ''}", flush=True)
    return 0
```

A `ModelDrift` raised in a worker reaches the parent through `future.result()`, and the loop above stops the measurement and returns 1. That is the spec's "the measurement stops and says so".

- [ ] **Step 4: Add the CLI subcommand**

In `src/jevplays/cli.py`, add:

```python
def cmd_branch(args: argparse.Namespace) -> int:
    rom = args.rom or _rom_from_env()
    if rom is None:
        print("no ROM: pass --rom or set JEVPLAYS_ROM", file=sys.stderr)
        return 2
    if not os.environ.get("TYPESAFE_API_KEY"):
        print("jevplays branch: TYPESAFE_API_KEY is not set; every branch asks Jev", file=sys.stderr)
        return 2
    from jevplays.branch.runner import measure

    return measure(args.run_dir, rom=rom, seeds=args.seeds, sample=args.sample, workers=args.workers)
```

and in `build_parser`, before `return parser`:

```python
    branch = sub.add_parser(
        "branch", help="replay every alternative of each decision in a recorded run (#82)"
    )
    branch.add_argument("run_dir", type=Path)
    branch.add_argument("--rom", type=Path, help="Pokémon Red/Blue ROM (default: $JEVPLAYS_ROM)")
    branch.add_argument("--seeds", type=int, default=8, help="random seeds per alternative")
    branch.add_argument("--sample", type=int, default=None, help="branch only N decisions, chosen at random")
    branch.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    branch.set_defaults(func=cmd_branch)
```

- [ ] **Step 5: Run the tests**

Run: `mise exec -- uv run pytest tests/test_branch_runner.py tests/test_cli.py tests/test_imports.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/jevplays/branch/runner.py src/jevplays/cli.py tests/test_branch_runner.py
git commit -m "feat(tooling): jevplays branch plays every alternative of a recorded run's decisions (#82)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Scoring, the report, and exporting a branch

**Files:**
- Modify: `src/jevplays/branch/score.py`
- Modify: `src/jevplays/branch/store.py` (`export_branch`)
- Create: `Scripts/branch-report.py`
- Test: `tests/test_branch_score.py` (extend), `tests/test_branch_store.py` (extend)

**Interfaces:**
- Consumes: `BranchStore`, `DecisionInfo`, `BranchKey`, `BranchResult`.
- Produces:
  - `seed_frames(rows: list[tuple[BranchKey, BranchResult]]) -> dict[str, dict[int, float]]`: capped and stalled become `math.inf`, errors are left out
  - `@dataclass DecisionScore`: `decision`, `kind`, `chosen`, `best`, `regret_s: float | None`, `tied: bool | None`, `baselines: dict[str, float | None]`
  - `score_decision(info: DecisionInfo, rows, seeds: int, rng: random.Random) -> DecisionScore`
  - `bootstrap_ci(values: list[float], rng, stat=statistics.fmean, n: int = 2000) -> tuple[float, float]`
  - `headline(scores: list[DecisionScore], rng) -> dict[str, dict]`, keyed by kind
  - `export_branch(store, key: BranchKey, root: Path) -> Path`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_branch_score.py`:

```python
import math
import random

from jevplays.branch.score import bootstrap_ci, headline, score_decision, seed_frames
from jevplays.branch.store import BranchKey, BranchResult, DecisionInfo


def rows(frames_by_alt):
    out = []
    for alt, frames in frames_by_alt.items():
        for seed, f in enumerate(frames):
            outcome = "capped" if f is None else "done"
            out.append((BranchKey(1, alt, seed), BranchResult(outcome, f, 0, 0, 0)))
    return out


INFO = DecisionInfo(1, "battle", "move:A", ["move:A", "move:B", "run"], "move:B", None, 1000)


def test_seed_frames_turns_capped_into_infinity_and_drops_errors():
    r = rows({"move:A": [60, None]}) + [(BranchKey(1, "run", 0), BranchResult("error", None, 0, 0, 0, "x"))]
    assert seed_frames(r) == {"move:A": {0: 60.0, 1: math.inf}}


def test_regret_is_chosen_minus_best_in_seconds_on_the_scoring_seeds():
    # seeds 0-3 pick the best (B), seeds 4-7 score it
    r = rows({
        "move:A": [600] * 8,
        "move:B": [300, 300, 300, 300, 360, 360, 360, 360],
        "run": [900] * 8,
    })
    s = score_decision(INFO, r, seeds=8, rng=random.Random(0))
    assert s.best == "move:B"
    assert s.regret_s == (600 - 360) / 60
    assert s.tied is False
    assert s.baselines["strongest"] == 0.0
    assert s.baselines["random"] == ((600 - 360) + 0 + (900 - 360)) / 60 / 3


def test_a_choice_that_is_the_best_has_zero_regret_and_is_tied():
    r = rows({"move:A": [300] * 8, "move:B": [600] * 8, "run": [900] * 8})
    s = score_decision(INFO, r, seeds=8, rng=random.Random(0))
    assert s.regret_s == 0.0 and s.tied is True


def test_a_censored_chosen_alternative_has_no_regret():
    r = rows({"move:A": [None] * 8, "move:B": [300] * 8, "run": [900] * 8})
    assert score_decision(INFO, r, seeds=8, rng=random.Random(0)).regret_s is None


def test_bootstrap_is_reproducible_with_a_fixed_rng():
    values = [1.0, 2.0, 3.0, 10.0]
    assert bootstrap_ci(values, random.Random(0)) == bootstrap_ci(values, random.Random(0))
    lo, hi = bootstrap_ci(values, random.Random(0))
    assert lo <= 4.0 <= hi


def test_headline_splits_by_kind_and_counts_uncensored_decisions():
    good = score_decision(INFO, rows({"move:A": [300] * 8, "move:B": [600] * 8, "run": [900] * 8}), 8, random.Random(0))
    bad = score_decision(INFO, rows({"move:A": [None] * 8, "move:B": [300] * 8, "run": [900] * 8}), 8, random.Random(0))
    h = headline([good, bad], random.Random(0))
    assert set(h) == {"battle"}
    assert h["battle"]["decisions"] == 2 and h["battle"]["scored"] == 1
    assert h["battle"]["mean_regret_s"] == 0.0
    # `bad` chose an alternative that never finished while the best did: judged, and not tied
    assert h["battle"]["best_or_tied"] == 0.5
```

Append to `tests/test_branch_store.py`:

```python
def test_export_writes_a_run_directory_replay_can_read(tmp_path):
    from jevplays.branch.store import export_branch
    from jevplays.runlog import RunDir

    s = store(tmp_path)
    s.add_decision(KEY, 1, {"id": "a", "kind": "battle", "action": "use EMBER"})
    s.add_decision(KEY, 2, {"id": "b", "kind": "explore", "action": "explore: x"})
    s.finish_branch(KEY, BranchResult("done", 100, 0, 1, 1))
    path = export_branch(s, KEY, tmp_path / "exported")
    run = RunDir.open(path)
    assert [d["id"] for d in run.decisions()] == ["a", "b"]
    assert run.info()["flags"]["branch"] == [12, "move:EMBER", 3]
```

- [ ] **Step 2: Run them and watch them fail**

Run: `mise exec -- uv run pytest tests/test_branch_score.py tests/test_branch_store.py -v`
Expected: FAIL with `ImportError` for the new names.

- [ ] **Step 3: Implement scoring**

Append to `src/jevplays/branch/score.py` (and move the new imports to the top of the file):

```python
import math
import random
import statistics
from dataclasses import dataclass

from jevplays.branch.store import BranchKey, BranchResult, DecisionInfo

FRAMES_PER_SECOND = 60
BOOTSTRAP_SAMPLES = 2000


def seed_frames(rows: list[tuple[BranchKey, BranchResult]]) -> dict[str, dict[int, float]]:
    """alternative -> seed -> frames to the milestone; a capped or stalled branch is infinity (it
    took at least the cap), and an errored one is left out."""
    out: dict[str, dict[int, float]] = {}
    for key, result in rows:
        if result.outcome == "error":
            continue
        frames = float(result.frames) if result.outcome == "done" else math.inf
        out.setdefault(key.alternative, {})[key.seed] = frames
    return out


def _median(frames: dict[int, float], seeds: range) -> float:
    values = [frames[s] for s in seeds if s in frames]
    return statistics.median(values) if values else math.inf


def bootstrap_ci(values: list[float], rng: random.Random, stat=statistics.fmean, n: int = BOOTSTRAP_SAMPLES) -> tuple[float, float]:
    """A 95% percentile bootstrap interval of `stat` over `values`."""
    draws = sorted(stat(rng.choices(values, k=len(values))) for _ in range(n))
    return draws[int(0.025 * n)], draws[int(0.975 * n) - 1]


@dataclass
class DecisionScore:
    decision: int
    kind: str
    chosen: str
    best: str
    regret_s: float | None
    tied: bool | None
    baselines: dict[str, float | None]


def score_decision(info: DecisionInfo, rows, seeds: int, rng: random.Random) -> DecisionScore:
    """The best alternative is picked on the first half of the seeds and scored on the second, so
    choosing the best of several noisy medians does not flatter it (spec: "Scoring")."""
    frames = seed_frames(rows)
    select, scoring = range(0, seeds // 2), range(seeds // 2, seeds)
    alts = [a for a in info.alternatives if a in frames]
    best = min(alts, key=lambda a: _median(frames[a], select))
    best_score = _median(frames[best], scoring)

    def regret(alt: str | None) -> float | None:
        if alt is None or alt not in frames:
            return None
        r = _median(frames[alt], scoring) - best_score
        return r / FRAMES_PER_SECOND if math.isfinite(r) else None

    chosen_regret = regret(info.chosen)
    tied = None
    if info.chosen in frames:
        pairs = [
            frames[info.chosen][s] - frames[best][s]
            for s in scoring
            if s in frames[info.chosen] and s in frames[best]
        ]
        pairs = [d for d in pairs if not math.isnan(d)]
        if info.chosen == best:
            tied = True
        elif pairs and all(math.isfinite(d) for d in pairs):
            lo, hi = bootstrap_ci(pairs, rng, stat=statistics.median)
            tied = lo <= 0 <= hi
        elif pairs:
            tied = False
    every = [r for r in (regret(a) for a in alts) if r is not None]
    baselines = {
        "random": statistics.fmean(every) if every else None,
        "strongest": regret(info.strongest),
        "offline": regret(info.offline),
    }
    return DecisionScore(info.decision, info.kind, info.chosen, best, chosen_regret, tied, baselines)


def headline(scores: list[DecisionScore], rng: random.Random) -> dict[str, dict]:
    """Per kind: how many decisions, how many had a finite regret, the mean regret with its 95%
    interval, the share where Jev's choice was the best or tied with it, and each baseline's mean."""
    out: dict[str, dict] = {}
    for kind in sorted({s.kind for s in scores}):
        mine = [s for s in scores if s.kind == kind]
        finite = [s.regret_s for s in mine if s.regret_s is not None]
        judged = [s.tied for s in mine if s.tied is not None]
        row: dict = {"decisions": len(mine), "scored": len(finite)}
        row["mean_regret_s"] = statistics.fmean(finite) if finite else None
        row["ci"] = bootstrap_ci(finite, rng) if len(finite) > 1 else None
        row["best_or_tied"] = sum(judged) / len(judged) if judged else None
        for name in ("random", "strongest", "offline"):
            values = [s.baselines[name] for s in mine if s.baselines.get(name) is not None]
            row[f"{name}_regret_s"] = statistics.fmean(values) if values else None
        out[kind] = row
    return out
```

- [ ] **Step 4: Implement export**

Append to `src/jevplays/branch/store.py`:

```python
def export_branch(store: BranchStore, key: BranchKey, root: Path) -> Path:
    """Write one branch out as an ordinary run directory, so `jevplays replay` plays it."""
    from jevplays.runlog import RunDir

    run = RunDir.create(root, rom=None, flags={"branch": list(key), "measurement": str(store.path)})
    with open(run.log_path, "w", encoding="utf-8") as f:
        for body in store.branch_decisions(key):
            f.write(json.dumps(body, ensure_ascii=False) + "\n")
    return run.path
```

- [ ] **Step 5: Write the report script**

`Scripts/branch-report.py`:

```python
#!/usr/bin/env -S uv run
"""Score a branch measurement (#82).

    uv run Scripts/branch-report.py RUN_DIR
    uv run Scripts/branch-report.py RUN_DIR --decision N
    uv run Scripts/branch-report.py RUN_DIR --export N ALTERNATIVE SEED OUT_DIR

Reads RUN_DIR/branches/branches.sqlite. The default prints the counts, then per decision kind the
mean regret (seconds of game time Jev's choice cost against the best alternative) with its 95%
interval, the share of decisions where Jev's choice was the best or tied with it, and the same
regret for three first-action rules: a random alternative, the strongest move, and the offline
milestone-first pick. `--decision` prints one decision's alternatives; `--export` writes one
branch as a run directory for `jevplays replay`.
"""

import argparse
import random
import statistics
import sys
from collections import Counter
from pathlib import Path

from jevplays.branch.score import FRAMES_PER_SECOND, headline, score_decision, seed_frames
from jevplays.branch.store import BranchKey, BranchStore, export_branch


def _s(value) -> str:
    return "-" if value is None else f"{value:.1f}s"


def summary(store: BranchStore) -> int:
    meta = store.meta()
    seeds = int(meta.get("seeds", "8"))
    infos = store.decision_infos()
    rows = store.branches()
    outcomes = Counter(r.outcome for _, r in rows)
    skipped = Counter(reason.split(":")[0] for reason in store.skipped().values())
    calls = sum(r.jev_calls for _, r in rows)
    hits = sum(r.cache_hits for _, r in rows)
    print(f"run {meta.get('run')}  model {meta.get('model')}  K={seeds}")
    print(f"decisions {len(infos)}  skipped {dict(skipped)}")
    print(f"branches {len(rows)}  {dict(outcomes)}  jev calls {calls}  cache hits {hits}")
    if "spread" in meta:
        print(f"determinism check: largest answer spread {meta['spread']}")
    rng = random.Random(0)
    scores = [score_decision(i, store.branches(i.decision), seeds, rng) for i in infos]
    for kind, row in headline(scores, rng).items():
        ci = row["ci"]
        interval = f" [{ci[0]:.1f}, {ci[1]:.1f}]" if ci else ""
        tied = "-" if row["best_or_tied"] is None else f"{row['best_or_tied']:.0%}"
        print(
            f"{kind:<8} decisions {row['decisions']} scored {row['scored']}  "
            f"regret {_s(row['mean_regret_s'])}{interval}  best or tied {tied}  "
            f"random {_s(row['random_regret_s'])}  strongest {_s(row['strongest_regret_s'])}  "
            f"offline {_s(row['offline_regret_s'])}"
        )
    return 0


def one_decision(store: BranchStore, n: int) -> int:
    info = next((i for i in store.decision_infos() if i.decision == n), None)
    if info is None:
        print(f"decision {n} was not measured: {store.skipped().get(n, 'not a candidate')}", file=sys.stderr)
        return 2
    rows = store.branches(n)
    frames = seed_frames(rows)
    print(f"decision {n} ({info.kind}), Jev chose {info.chosen}")
    for alt in info.alternatives:
        values = sorted(frames.get(alt, {}).values())
        done = [v for v in values if v != float("inf")]
        median = statistics.median(values) / FRAMES_PER_SECOND if values else None
        spread = (max(done) - min(done)) / FRAMES_PER_SECOND if len(done) > 1 else None
        blackouts = sum(r.blackouts for k, r in rows if k.alternative == alt)
        mark = "*" if alt == info.chosen else " "
        print(
            f"{mark} {alt:<32} median {_s(median)}  spread {_s(spread)}  "
            f"censored {len(values) - len(done)}/{len(values)}  blackouts {blackouts}"
        )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=Path)
    ap.add_argument("--decision", type=int)
    ap.add_argument("--export", nargs=4, metavar=("N", "ALTERNATIVE", "SEED", "OUT_DIR"))
    args = ap.parse_args()
    db = args.run / "branches" / "branches.sqlite"
    if not db.is_file():
        print(f"{db} does not exist; run `jevplays branch {args.run}` first", file=sys.stderr)
        return 2
    store = BranchStore(db)
    if args.export:
        n, alt, seed, out = args.export
        print(export_branch(store, BranchKey(int(n), alt, int(seed)), Path(out)))
        return 0
    if args.decision is not None:
        return one_decision(store, args.decision)
    return summary(store)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Run the tests**

Run: `mise exec -- uv run pytest tests/test_branch_score.py tests/test_branch_store.py -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/jevplays/branch/score.py src/jevplays/branch/store.py Scripts/branch-report.py tests/test_branch_score.py tests/test_branch_store.py
git commit -m "feat(tooling): score a branch measurement and export a branch for replay (#82)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: ROM tests: snapshots rebuild, seeds differ, a branch reaches the badge

**Files:**
- Create: `tests/rom/test_branch.py`

**Interfaces:**
- Consumes: `FirstChoiceBrain` from `tests/rom/test_loop_overworld.py`; `prepare`, `Stopper`, `run_branch`, `Job`, `BranchKey`, `BranchStore`.

Before starting, make sure the worktree has game data: copy `mise.local.toml`, `roms/` and `states/` from the main checkout, run `mkdir -p runs && mise run setup`, and write the on-request state with `mise exec -- uv run Scripts/make-states.py --only brock`.

- [ ] **Step 1: Write the tests**

`tests/rom/test_branch.py`:

```python
"""Branching against the real game (#82)."""

import asyncio

from jevplays.brain.decision import BattleAction
from jevplays.branch.alternatives import prepare
from jevplays.branch.runner import Job, run_branch
from jevplays.branch.stop import Stopper
from jevplays.branch.store import BranchKey, BranchStore
from jevplays.emulator import ram
from jevplays.emulator.pyboy import Emulator
from jevplays.loop import Loop, LoopConfig
from jevplays.runlog import RunDir
from jevplays.state.modes import Mode
from jevplays.state.snapshot import snapshot
from tests.rom.test_loop_overworld import FirstChoiceBrain

GOAL = LoopConfig().goal


class Quiet:
    async def publish(self, event):
        pass


def record(rom, state, tmp_path, iterations):
    run = RunDir.create(tmp_path, rom=rom, flags={})
    with Emulator(rom) as emu:
        emu.load(state)
        loop = Loop(
            emu, Quiet(), LoopConfig(paced=False, fps=1e-9, snapshot_every_decision=True),
            brain=FirstChoiceBrain(), run_dir=run,
        )
        asyncio.run(loop.run(max_iterations=iterations))
    return run


def rebuilt(rom, run, kind):
    """How many of `run`'s `kind` decisions rebuild from their snapshot. `prepare` raises if one
    does not, which fails the test with its reason."""
    count = 0
    with Emulator(rom) as emu:
        for n, logged in enumerate(run.decisions(), start=1):
            if logged["kind"] != kind or logged["fallback"]:
                continue
            emu.load(run.snapshot_state(n))
            assert prepare(emu, logged, run.snapshot_info(n), fallback_goal=GOAL).chosen
            count += 1
    return count


def test_explore_snapshots_rebuild_their_decisions(rom, state_path, tmp_path):
    run = record(rom, state_path("route1"), tmp_path, 100)
    assert rebuilt(rom, run, "explore") >= 1


def test_battle_snapshots_rebuild_their_decisions(rom, state_path, tmp_path):
    run = record(rom, state_path("battle_wild"), tmp_path, 3)
    assert rebuilt(rom, run, "battle") >= 1


def enemy_hp_after_forced_move(rom, state, seed):
    """Press the forced move, then play the turn out -- A through the battle text -- up to the
    next battle menu or the end of the battle, without asking anyone anything."""
    with Emulator(rom) as emu:
        emu.load(state)
        move = snapshot(emu).active.moves[0].name
        loop = Loop(
            emu, Quiet(), LoopConfig(paced=False, fps=1e-9), brain=FirstChoiceBrain(),
            forced=BattleAction(kind="move", move=move), forced_delay=seed,
        )
        asyncio.run(loop.advance(snapshot(emu)))
        assert loop.decisions[0].forced and loop.decisions[0].action == f"use {move}"
        for _ in range(400):
            state_now = snapshot(emu)
            if state_now.mode is Mode.BATTLE_MENU or not state_now.in_battle:
                break
            if state_now.mode in (Mode.DIALOG, Mode.BATTLE_WAIT):
                emu.press("a", settle=30)
            else:
                emu.tick(30)
        return (
            emu.mem[ram.wEnemyMonHP] * 256 + emu.mem[ram.wEnemyMonHP + 1],
            emu.mem[ram.wBattleMonHP] * 256 + emu.mem[ram.wBattleMonHP + 1],
        )


def test_seeds_change_how_the_same_forced_move_plays_out(rom, state_path):
    """Review focus 1: if this fails, idle frames do not reseed the battle and K seeds are one."""
    state = state_path("battle_wild")
    outcomes = {enemy_hp_after_forced_move(rom, state, seed) for seed in range(8)}
    assert len(outcomes) > 1, outcomes


def test_a_branch_from_the_gym_stops_done_at_the_badge(rom, state_path, tmp_path):
    """`brock_award.state` is mid-dialog after Brock falls; test_badge.py finishes from it in
    under 80 turns. A branch from there must end as done, not capped or stalled."""
    with Emulator(rom) as emu:
        emu.load(state_path("brock_award"))
        stopper = Stopper("beat_brock", cap_frames=200_000)
        loop = Loop(emu, Quiet(), LoopConfig(paced=False, fps=1e-9), brain=FirstChoiceBrain(), stop=stopper)
        asyncio.run(loop.run(max_iterations=200))
        assert loop.finished and loop.stop_reason is None
        assert snapshot(emu).badges >= 1


def test_run_branch_records_a_finished_branch_and_its_decisions(rom, state_path, tmp_path):
    state = state_path("battle_wild")
    with Emulator(rom) as emu:
        emu.load(state)
        move = snapshot(emu).active.moves[0].name
    db = tmp_path / "b.sqlite"
    key = BranchKey(1, f"move:{move}", 0)
    job = Job(rom, state, {}, "get_pokedex", key, BattleAction(kind="move", move=move), 20_000, db, "", GOAL)
    result = run_branch(job, brain_factory=FirstChoiceBrain)
    store = BranchStore(db)
    assert store.done() == {key}
    assert result.outcome in ("done", "capped", "stalled")
    assert store.branch_decisions(key)[0]["forced"] is True
```

`ram.wEnemyMonHP` (0xCFE6) and `ram.wBattleMonHP` (0xD015) are big-endian u16s already in `ram.py`.

- [ ] **Step 2: Run them**

Run: `mise exec -- uv run pytest tests/rom/test_branch.py -v`
Expected: 5 passed. If `test_seeds_change_how_the_same_forced_move_plays_out` fails, stop and report. The seeding design is wrong, and the spec's "Seeds" section needs revisiting with Tyler before anything else is built on it.

- [ ] **Step 3: Run the whole suite**

Run: `mise run check`
Expected: all pass, with the ROM tests collected on this machine.

- [ ] **Step 4: Commit**

```bash
git add tests/rom/test_branch.py
git commit -m "test(tooling): branching against the real game (#82)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: One real measurement, the README, and the PR

**Files:**
- Modify: `README.md` (a short "Did Jev choose well?" section next to the calibration numbers)

- [ ] **Step 1: Record a run with snapshots**

Run: `mise exec -- uv run jevplays run --state states/route1.state --unpaced --snapshot-every-decision --port 8791`
Expected: it finishes at the Boulder Badge and prints the run directory. Check `runs/<stamp>/snapshots/` holds one `.state` per decision and a `milestones.jsonl` with all three milestones.

- [ ] **Step 2: Store the determinism result in the measurement**

Run the Task 1 script against this new run:
`mise exec -- uv run Scripts/jev-determinism.py runs/<stamp>`
Then store its largest spread, so the report prints it:

```bash
mise exec -- uv run python -c "from pathlib import Path; from jevplays.branch.store import BranchStore; BranchStore(Path('runs/<stamp>/branches/branches.sqlite')).set_meta('spread', '<largest spread>')"
```

- [ ] **Step 3: Branch it**

Run: `mise exec -- uv run jevplays branch runs/<stamp>`
Expected: progress lines ending in all branches run, exit 0. Resuming after an interruption reruns only unfinished branches.

- [ ] **Step 4: Report**

Run: `mise exec -- uv run Scripts/branch-report.py runs/<stamp>`, then `--decision N` for the decision with the largest regret.
Expected: the header counts, one line per kind, and a per-decision table.

- [ ] **Step 5: README**

Add a section after the calibration numbers in `README.md`, in the README's own voice. Say what was measured (one run, N decisions, K=8), and give the regret numbers with intervals for battle and explore next to the three baselines. Point to `Scripts/branch-report.py` and the spec. Quote the numbers exactly as the report printed them.

- [ ] **Step 6: Commit, push, open the PR**

```bash
git add README.md
git commit -m "docs: what branching says about Jev's choices (#82)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
mise run check
git push -u origin tylervick/branching
gh pr create --title "feat(tooling): counterfactual branching (#82)" --body "<summary, the determinism check's output, the full branch-report output, and Closes #82, ending with the Claude Code attribution line>"
```
