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
        emu,
        RecordingBroadcaster(),
        LoopConfig(paced=False),
        brain=brain,
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
        emu,
        RecordingBroadcaster(),
        LoopConfig(paced=False),
        brain=FakeBrain(response=RESPONSE),
        forced=BattleAction(kind="move", move="SCRATCH"),
        forced_delay=5,
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
        emu,
        RecordingBroadcaster(),
        LoopConfig(paced=False),
        brain=brain,
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
        emu,
        RecordingBroadcaster(),
        LoopConfig(paced=False),
        brain=brain,
        forced=ExploreAction(option_id="exit_north", kind="exit", text="go north to Route 2"),
    )
    asyncio.run(loop.run(max_iterations=1))
    assert brain.calls == 0
    assert loop.option is not None and loop.option.id == "exit_north"
    assert loop.decisions[0].forced


def test_a_forced_option_that_is_not_offered_raises():
    emu = explore_emu()
    loop = Loop(
        emu,
        RecordingBroadcaster(),
        LoopConfig(paced=False),
        brain=QuestionBrain(explore="exit_north"),
        forced=ExploreAction(option_id="door_99", kind="door", text="enter nowhere"),
    )
    with pytest.raises(ForcedActionMissed, match="door_99"):
        asyncio.run(loop.run(max_iterations=1))


def test_another_decision_before_the_forced_one_raises_instead_of_asking_jev():
    """Review focus 3: an explore decision arrives while a battle action is still forced."""
    emu = explore_emu()
    loop = Loop(
        emu,
        RecordingBroadcaster(),
        LoopConfig(paced=False),
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
