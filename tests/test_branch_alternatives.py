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
    extra = dict(
        species=16, level=8, hp=14, max_hp=14, types=(0, 0), moves=(33,), pps=(35,), nickname="PIDGEY"
    )
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
        prepare(
            emu,
            logged_battle(emu, action="throw a Poké Ball"),
            {"milestone": None, "memory": {}},
            fallback_goal=FALLBACK,
        )


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
    prepared = prepare(
        emu, logged, {"milestone": milestone.id, "memory": Memory.empty().to_dict()}, fallback_goal=FALLBACK
    )
    assert keys(prepared.alternatives) == [f"explore:{o.id}" for o in options]
    assert prepared.chosen == f"explore:{options[-1].id}"
    assert prepared.offline is not None and prepared.offline.startswith("explore:")
    assert explore_alternatives(options)[0].action.option_id == options[0].id
