import json
import re

from jevplays.brain.decision import GoalAction
from jevplays.brain.goal import decide_goal, goal_questions, goal_state
from jevplays.brain.policy import choose_goal
from jevplays.executor.goals import Goal
from jevplays.state.snapshot import BagItem, Mon
from tests.support import overworld_state

LEAD = Mon(
    name="CHARMANDER",
    nickname="CHARMANDER",
    level=8,
    types=("Fire",),
    hp=10,
    max_hp=23,
    status="none",
    moves=(),
)

# Descriptions deliberately have no digits in them, so the number-leak test can isolate levels.
GOALS = [
    Goal(
        id="get_starter",
        description="Get a starter Pokémon from the professor",
        available=lambda s: True,
        done=lambda s: False,
        legs=lambda s: [],
    ),
    Goal(
        id="buy_pokeballs",
        description="Buy some Poké Balls at the mart",
        available=lambda s: True,
        done=lambda s: False,
        legs=lambda s: [],
    ),
    Goal(
        id="heal_at_center",
        description="Heal at the nearest Pokémon Center",
        available=lambda s: True,
        done=lambda s: False,
        legs=lambda s: [],
    ),
]


def answers(**kw):
    out = {}
    for k, v in kw.items():
        if isinstance(v, dict):
            out[k] = {"type": "choice", "choice": max(v, key=v.get), "probabilities": v, "confidence": 0.5}
        else:
            out[k] = {"type": "noul", "noul": v}
    return out


def test_goal_state_uses_words_not_numbers_except_levels():
    state = overworld_state(party=(LEAD,), money=750, bag=(BagItem("POKE BALL", 5), BagItem("POTION", 0)))
    sj = goal_state(state, GOALS)
    assert sj["party"] == [{"name": "CHARMANDER", "level": 8, "hp": "hurt"}]
    assert sj["money"] == "some"
    assert sj["badges"] == "none"
    assert sj["bag"] == {"POKE BALL": "plenty", "POTION": "none"}
    assert sj["goals"] == {g.id: g.description for g in GOALS}

    numbers = re.findall(r"\d+", json.dumps(sj, ensure_ascii=False))
    assert set(numbers) == {"8"}  # only CHARMANDER's level


def test_goal_questions_always_ask_needs_heal_and_goal_lists_exactly_the_available_ids():
    state = overworld_state(party=(LEAD,))
    sj = goal_state(state, GOALS)
    qs = goal_questions(sj)
    assert set(qs) == {"goal", "needs_heal"}
    assert qs["needs_heal"]["type"] == "noul"
    assert qs["goal"]["type"] == "choice"
    assert list(qs["goal"]["criteria"]) == ["get_starter", "buy_pokeballs", "heal_at_center"]
    assert qs["goal"]["criteria"]["heal_at_center"] == "Heal at the nearest Pokémon Center"


def test_goal_questions_lists_only_the_ids_it_is_given():
    state = overworld_state(party=(LEAD,))
    sj = goal_state(state, GOALS[:1])
    qs = goal_questions(sj)
    assert list(qs["goal"]["criteria"]) == ["get_starter"]


def test_policy_heals_first_only_when_available_and_above_threshold():
    available = ["get_starter", "buy_pokeballs", "heal_at_center"]
    a = answers(needs_heal=0.9, goal={"buy_pokeballs": 1.0})
    assert choose_goal(a, available) == ("heal_at_center", ["needs_heal"])

    # needs_heal fires, but heal_at_center is not on offer: falls through to the goal choice.
    a = answers(needs_heal=0.9, goal={"buy_pokeballs": 1.0})
    assert choose_goal(a, ["get_starter", "buy_pokeballs"]) == ("buy_pokeballs", ["goal"])

    # needs_heal below the threshold: the goal choice wins even though heal_at_center is on offer.
    a = answers(needs_heal=0.2, goal={"buy_pokeballs": 1.0})
    assert choose_goal(a, available) == ("buy_pokeballs", ["goal"])


def test_policy_falls_back_to_the_first_available_id_with_no_usable_answers():
    assert choose_goal({}, ["get_starter", "buy_pokeballs"]) == ("get_starter", [])
    assert choose_goal({}, []) == ("", [])


def test_decide_goal_marks_applied_and_builds_the_action():
    state = overworld_state(party=(LEAD,))
    sj = goal_state(state, GOALS)
    qs = goal_questions(sj)
    available_ids = list(sj["goals"])
    response = {
        "model": "jev-1.13.0",
        "usage": {"input_tokens": 300, "output_tokens": 20},
        "answers": answers(needs_heal=0.1, goal={"buy_pokeballs": 0.8, "get_starter": 0.2}),
    }
    d = decide_goal(sj, qs, response, available_ids, model="jev-1.13.0", input_tokens=300, latency_ms=250)
    assert d.kind == "goal" and d.model == "jev-1.13.0" and d.input_tokens == 300 and d.latency_ms == 250
    assert d.fallback is False and d.fallback_reason == ""
    assert d.action == "pursue buy_pokeballs"
    assert d.action_value == GoalAction(goal_id="buy_pokeballs")
    assert d.answers["goal"]["applied"] is True and d.answers["needs_heal"]["applied"] is False


def test_decide_goal_falls_back_when_the_model_picks_an_id_outside_available_ids():
    state = overworld_state(party=(LEAD,))
    sj = goal_state(state, GOALS)
    qs = goal_questions(sj)
    available_ids = ["get_starter", "buy_pokeballs"]  # heal_at_center left out on purpose
    response = {
        "model": "m",
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "answers": answers(needs_heal=0.1, goal={"heal_at_center": 0.9}),
    }
    d = decide_goal(sj, qs, response, available_ids, model="m", input_tokens=1, latency_ms=1)
    assert d.fallback is True and "heal_at_center" in d.fallback_reason
    assert d.action == "pursue get_starter"
    assert d.action_value == GoalAction(goal_id="get_starter")
    assert d.answers["goal"]["applied"] is False  # the invalid choice was not the one used
