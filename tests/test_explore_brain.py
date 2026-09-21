import json
import re

from jevplays.brain.decision import ExploreAction
from jevplays.brain.explore import decide_explore, explore_questions, explore_state
from jevplays.brain.policy import choose_explore
from jevplays.executor.options import Option
from jevplays.state.snapshot import BagItem
from tests.support import overworld_state


def answers(**kw):
    out = {}
    for k, v in kw.items():
        if isinstance(v, dict):
            out[k] = {"type": "choice", "choice": max(v, key=v.get), "probabilities": v, "confidence": 0.5}
        else:
            out[k] = {"type": "noul", "noul": v}
    return out


def test_explore_state_uses_words_and_lists_options_with_memory_words():
    state = overworld_state(
        map_id=1, flags=("got_starter", "got_pokedex"), money=3175, bag=(BagItem("POKE BALL", 4),)
    )
    options = [
        Option("exit_north", "exit", "go north to Route 2", "new", (), None, dest_map=13),
        Option("milestone", "milestone", "head for the Pewter Gym", "new", (), "talk_brock"),
    ]
    sj = explore_state(state, options, milestone=None)
    assert sj["progress"] == ["got a starter", "got the Pokédex"] and sj["money"] == "comfortable"
    assert sj["options"] == {
        "exit_north": "go north to Route 2 (new)",
        "milestone": "head for the Pewter Gym (new)",
    }
    # "party" carries levels and "options" carries option text built by executor/options.py
    # (Task 1, tested there), which is allowed a place name's digits, e.g. "Route 2" -- what
    # explore_state itself computes (map, progress, money, bag, milestone) must have none.
    leak_check = {k: v for k, v in sj.items() if k not in ("party", "options")}
    assert not re.search(r"\d", json.dumps(leak_check, ensure_ascii=False))


def test_questions_offer_exactly_the_options_and_always_ask_needs_heal():
    state = overworld_state()
    options = [
        Option("exit_north", "exit", "go north to Route 2", "new", (), None, dest_map=13),
        Option("grass", "grass", "train in the tall grass here", "tried", (), "wander"),
    ]
    sj = explore_state(state, options, milestone=None)
    qs = explore_questions(sj)
    assert set(qs) == {"explore", "needs_heal"}
    assert qs["explore"]["type"] == "choice" and qs["explore"]["criteria"] == sj["options"]
    assert qs["needs_heal"]["type"] == "noul"


def test_policy_heals_first_only_when_a_heal_option_exists_and_the_noul_clears():
    a = answers(needs_heal=0.9, explore={"grass": 1.0})
    assert choose_explore(a, ["heal", "grass"]) == ("heal", ["needs_heal"])
    # No "heal" option on offer: the explore choice wins even though needs_heal fired.
    assert choose_explore(a, ["grass"]) == ("grass", ["explore"])


def test_off_list_choice_falls_back_to_the_milestone_with_fallback_set():
    options = [
        Option("exit_north", "exit", "go north to Route 2", "new", (), None, dest_map=13),
        Option("milestone", "milestone", "head for the Pewter Gym", "new", (), "talk_brock"),
    ]
    sj = explore_state(overworld_state(), options, milestone=None)
    qs = explore_questions(sj)
    response = {
        "model": "m",
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "answers": answers(needs_heal=0.1, explore={"grass": 1.0}),  # "grass" is not on offer
    }
    d = decide_explore(sj, qs, response, options, model="m", input_tokens=1, latency_ms=1)
    assert d.fallback is True and "not offered" in d.fallback_reason
    assert d.action_value == ExploreAction(
        option_id="milestone", kind="milestone", text="head for the Pewter Gym"
    )
    assert d.answers["explore"]["applied"] is False


def test_decide_explore_marks_applied_and_carries_the_option_kind():
    options = [
        Option("exit_north", "exit", "go north to Route 2", "new", (), None, dest_map=13),
        Option("milestone", "milestone", "head for the Pewter Gym", "new", (), "talk_brock"),
    ]
    sj = explore_state(overworld_state(), options, milestone=None)
    qs = explore_questions(sj)
    response = {
        "model": "m",
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "answers": answers(needs_heal=0.1, explore={"exit_north": 0.9, "milestone": 0.1}),
    }
    d = decide_explore(sj, qs, response, options, model="m", input_tokens=1, latency_ms=1)
    assert d.action == "explore: go north to Route 2"
    assert d.action_value.kind == "exit"
    assert d.fallback is False and d.fallback_reason == ""
    assert d.answers["explore"]["applied"] is True
