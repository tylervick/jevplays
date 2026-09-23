"""Branching against the real game (#82)."""

import asyncio

from jevplays.brain.decision import BattleAction
from jevplays.branch.alternatives import prepare
from jevplays.branch.runner import Job, run_branch
from jevplays.branch.stop import Stopper
from jevplays.branch.store import BranchKey, BranchStore
from jevplays.emulator.pyboy import Emulator
from jevplays.loop import Loop, LoopConfig
from jevplays.runlog import RunDir
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
            emu,
            Quiet(),
            LoopConfig(paced=False, fps=1e-9, snapshot_every_decision=True),
            brain=FirstChoiceBrain(),
            run_dir=run,
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


def battle_outcome_for_seed(rom, state, seed):
    """Play the whole battle out from the forced move, seeded by `forced_delay`, and return a
    summary of how it went: decisions taken, the party's ending HP, and frames spent."""
    with Emulator(rom) as emu:
        emu.load(state)
        move = snapshot(emu).active.moves[0].name
        loop = Loop(
            emu,
            Quiet(),
            LoopConfig(paced=False, fps=1e-9),
            brain=FirstChoiceBrain(),
            forced=BattleAction(kind="move", move=move),
            forced_delay=seed,
            stop=lambda lp, st: "battle over" if not st.in_battle else None,
        )
        asyncio.run(loop.run(max_iterations=2000))
        assert loop.decisions[0].forced
        return (len(loop.decisions), tuple(m.hp for m in snapshot(emu).party), loop.game_frames)


def test_seeds_change_how_the_same_forced_move_plays_out(rom, state_path):
    """Review focus 1: if this fails, idle frames do not reseed the battle and K seeds are one.

    One turn is too short a horizon at this level: a lv6 Charmander's SCRATCH almost always
    rolls the same 6 damage, and the lv2 Pidgey knows only GUST (always 3), so most seeds land
    on the same one-turn HP pair even though the RNG bytes genuinely differ per seed. Playing the
    whole battle out gives the RNG enough turns to diverge."""
    state = state_path("battle_wild")
    outcomes = {battle_outcome_for_seed(rom, state, seed) for seed in range(8)}
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
