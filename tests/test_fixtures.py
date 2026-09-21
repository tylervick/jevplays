import json
from pathlib import Path

import pytest

from jevplays.brain.battle import ALL_ACTIONS, decide_battle
from jevplays.brain.goal import decide_goal
from jevplays.brain.policy import (
    CATCH_THRESHOLD,
    HEAL_FIRST_THRESHOLD,
    HEAL_THRESHOLD,
    SWITCH_THRESHOLD,
)
from jevplays.brain.prompt import decide_menu, decide_prompt

FIXTURES = Path(__file__).parent / "fixtures" / "responses"


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.mark.parametrize("name", ["battle_trainer", "battle_wild"])
def test_recorded_response_decodes_to_a_move(name):
    f = load(name)
    d = decide_battle(
        f["state_json"],
        f["questions"],
        f["response"],
        model=f["response"]["model"],
        input_tokens=f["response"]["usage"]["input_tokens"],
        latency_ms=f["latency_ms"],
    )
    assert d.action.startswith("use ") and d.fallback is False
    assert d.answers["move"]["applied"] is True
    assert set(d.questions) == set(f["questions"])


def test_trainer_fixture_prefers_an_attack_over_growl():
    f = load("battle_trainer")
    probs = f["response"]["answers"]["move"]["probabilities"]
    assert probs["SCRATCH"] > probs["GROWL"]


def replay(name, decoder, **extra):
    """Decode a recorded response exactly as the loop would, with the questions and the state
    Jev was actually shown."""
    f = load(name)
    return f, decoder(
        f["state_json"],
        f["questions"],
        f["response"],
        model=f["response"]["model"],
        input_tokens=f["response"]["usage"]["input_tokens"],
        latency_ms=f["latency_ms"],
        **extra,
    )


@pytest.mark.parametrize("name", ["goal_route1", "goal_hurt"])
def test_recorded_goal_response_decodes_to_an_available_goal(name):
    f = load(name)
    ids = list(f["state_json"]["goals"])
    _, d = replay(name, decide_goal, available_ids=ids)
    assert d.action_value.goal_id in ids and d.fallback is False
    assert d.answers["goal"]["applied"] is True or d.answers["needs_heal"]["applied"] is True


def test_route1_fixture_goes_after_the_parcel():
    f, d = replay("goal_route1", decide_goal, available_ids=list(load("goal_route1")["state_json"]["goals"]))
    assert d.action == "pursue deliver_parcel"
    probs = f["response"]["answers"]["goal"]["probabilities"]
    assert probs["deliver_parcel"] > probs["train_nearby"]


def test_hurt_fixture_heals_before_anything_else():
    f, d = replay("goal_hurt", decide_goal, available_ids=list(load("goal_hurt")["state_json"]["goals"]))
    assert d.action == "pursue heal_at_center"
    # Both routes to that answer agree: the `goal` choice picked it, and `needs_heal` cleared
    # the heal-first threshold on its own.
    assert f["response"]["answers"]["goal"]["choice"] == "heal_at_center"
    assert f["response"]["answers"]["needs_heal"]["noul"] > HEAL_FIRST_THRESHOLD


def test_starter_prompt_fixture_answers_yes():
    f, d = replay("prompt_starter", decide_prompt)
    assert "CHARMANDER?" in f["state_json"]["prompt"]
    assert d.action_value.yes is True and d.action == "answer YES"
    assert d.fallback is False and d.answers["prompt"]["applied"] is True


def test_start_menu_fixture_picks_an_item_that_is_on_the_menu():
    f, d = replay("menu_start", decide_menu)
    assert d.action_value.item in f["state_json"]["menu_items"]
    assert d.fallback is False and d.answers["menu"]["applied"] is True


def battle(name):
    """Replay a battle fixture the way the loop decodes one: every action kind is executable
    now, so `supported` is ALL_ACTIONS and a heal, catch, or switch answer is no longer
    downgraded to the move answer."""
    return replay(name, decide_battle, supported=ALL_ACTIONS)


def test_catch_fixture_agrees_with_the_catch_noul():
    """The recorded answer is catch 0.32, under CATCH_THRESHOLD, so this turn stays a move:
    Jev was shown a PIDGEY at `low` hp with balls in the bag and judged the ball not worth the
    turn. What is pinned is that the noul and the action say the same thing, so a re-recording
    that clears the threshold has to come with a thrown ball."""
    f, d = battle("battle_catch")
    assert f["state_json"]["enemy_pokemon"]["hp"] in ("low", "critical")
    assert f["state_json"]["bag"]["poke_balls"] is True and "catch" in f["questions"]
    catch = f["response"]["answers"]["catch"]["noul"]
    assert (d.action == "throw a Poké Ball") == (catch > CATCH_THRESHOLD)
    assert d.fallback is False


def test_heal_fixture_agrees_with_the_heal_noul():
    """The recorded answer is heal 0.21, under HEAL_THRESHOLD: a CHARMANDER on `low` hp with
    Potions in the bag, and Jev still preferred to attack. Same pinning as the catch fixture --
    the noul and the action agree, whichever way the noul goes."""
    f, d = battle("battle_heal")
    assert f["state_json"]["our_pokemon"]["hp"] in ("low", "critical")
    assert f["state_json"]["bag"]["potions"] is True and "heal" in f["questions"]
    heal = f["response"]["answers"]["heal"]["noul"]
    assert (d.action == "use a Potion") == (heal > HEAL_THRESHOLD)
    assert d.fallback is False


def test_switch_fixture_agrees_with_the_switch_noul():
    """The recorded answer is switch 0.15 (with switch_to PIDGEY at 1.00 had it switched), so
    the turn is a move. A switch names a bench label and never an index -- the loop resolves it
    with brain.battle.bench_slots -- so the label is what a fixture can check."""
    f, d = battle("battle_switch")
    labels = [m["label"] for m in f["state_json"]["bench"]]
    assert len(labels) == 1 and labels[0]  # whichever species Route 1 rolled when the state was made
    assert f["state_json"]["party"] == "two" and "switch" in f["questions"]
    switch = f["response"]["answers"]["switch"]["noul"]
    assert (d.action_value.kind == "switch") == (switch > SWITCH_THRESHOLD)
    assert d.fallback is False
    if d.action_value.kind == "switch":
        assert d.action_value.target == labels[0] and d.action_value.slot is None
    else:
        assert d.action_value.kind == "move"
