from dataclasses import replace
from types import SimpleNamespace

from jevplays.branch.stop import MIN_CAP_FRAMES, STALL_FRAMES, Stopper, cap_for
from jevplays.executor.goals import MILESTONES
from tests.support import OVERWORLD_LEAD, overworld_state

POKEDEX, BROCK = MILESTONES[1], MILESTONES[2]
ALIVE = overworld_state()
DOWN = overworld_state(party=(replace(OVERWORLD_LEAD, hp=0),))


def loop(frames=0, milestone=POKEDEX, decisions=0, finished=False):
    return SimpleNamespace(
        game_frames=frames, milestone=milestone, decisions=[None] * decisions, finished=finished
    )


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
