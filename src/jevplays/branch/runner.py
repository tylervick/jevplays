"""`jevplays branch`: rebuild each decision of a recorded run, then play every alternative from it
(spec: "Shape"). The parent process prepares decisions with one emulator; each branch runs in a
worker process with an emulator of its own."""

import asyncio
import contextlib
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
        reference = (
            finished - sidecar["frame"] if finished is not None and finished >= sidecar["frame"] else None
        )
        out.append(Candidate(n, logged, sidecar, state, reference))
    return out


def check_seeds(store: BranchStore, seeds: int) -> None:
    recorded = store.meta().get("seeds")
    if recorded is not None and int(recorded) != seeds:
        raise SeedsMismatch(f"this measurement was started with --seeds {recorded}; rerun with that")
    store.set_meta("seeds", str(seeds))


def run_branch(job: Job, brain_factory=None) -> BranchResult:
    """Play one branch to its end and record it. Runs in a worker process.

    Any failure other than `ModelDrift` is recorded as an "error" branch with the exception's
    repr, so one bad branch does not stop a measurement of hours; `ModelDrift` propagates, since
    every later branch would compare a different Jev. The brain and the store are closed however
    the branch ends, and a failure to close never hides the error that ended it."""
    from jevplays.brain.cache import CachedBrain, ModelDrift
    from jevplays.emulator.pyboy import Emulator
    from jevplays.executor.options import Memory
    from jevplays.loop import Loop, LoopConfig

    if brain_factory is None:
        from jevplays.brain.client import Brain

        brain_factory = Brain
    store = BranchStore(job.db)
    brain = None
    stopper = Stopper(job.milestone, job.cap_frames)
    try:
        try:
            store.clear_partial(job.key)
            brain = CachedBrain(brain_factory(), store, expected_model=job.model)
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
                asyncio.run(loop.run())
                outcome = "done" if loop.finished else (loop.stop_reason or "stalled")
                result = BranchResult(
                    outcome,
                    loop.game_frames if outcome == "done" else None,
                    stopper.blackouts,
                    brain.calls,
                    brain.hits,
                )
        except ModelDrift:
            raise
        except Exception as error:
            calls, hits = (brain.calls, brain.hits) if brain is not None else (0, 0)
            result = BranchResult("error", None, stopper.blackouts, calls, hits, repr(error))
        store.finish_branch(job.key, result)
        return result
    finally:
        if brain is not None:
            with contextlib.suppress(Exception):
                asyncio.run(brain.close())
        with contextlib.suppress(Exception):
            store.close()


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
                    c.n,
                    prepared.kind,
                    prepared.chosen,
                    [a.key for a in prepared.alternatives],
                    prepared.strongest,
                    prepared.offline,
                    c.reference_frames,
                )
            )
            for alt in prepared.alternatives:
                for seed in range(seeds):
                    key = BranchKey(c.n, alt.key, seed)
                    if key in done:
                        continue
                    jobs.append(
                        Job(
                            rom,
                            c.state,
                            c.sidecar["memory"],
                            c.sidecar["milestone"],
                            key,
                            alt.action,
                            cap_for(c.reference_frames),
                            db,
                            model,
                            goal,
                        )
                    )
    print(
        f"branch: {len(found)} decisions, {len(jobs)} branches to run, {len(done)} already done", flush=True
    )
    with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as pool:
        futures = {pool.submit(run_branch, job): job for job in jobs}
        for i, future in enumerate(as_completed(futures), start=1):
            job = futures[future]
            try:
                result = future.result()
            except Exception as error:
                cause = f" (caused by {error.__cause__!r})" if error.__cause__ is not None else ""
                print(f"jevplays branch: {job.key} failed: {error!r}{cause}", file=sys.stderr)
                pool.shutdown(wait=True, cancel_futures=True)
                return 1
            print(
                f"[{i}/{len(jobs)}] {job.key.decision} {job.key.alternative} seed {job.key.seed}: "
                f"{result.outcome} {result.frames or ''}",
                flush=True,
            )
    return 0
