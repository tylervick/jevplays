import json
from pathlib import Path

import pytest

from jevplays.brain.battle import ALL_ACTIONS, decide_battle
from jevplays.brain.explore import decide_explore
from jevplays.brain.policy import (
    CATCH_THRESHOLD,
    HEAL_THRESHOLD,
    RUN_THRESHOLD,
    SWITCH_THRESHOLD,
)
from jevplays.brain.prompt import decide_menu, decide_prompt
from jevplays.executor.options import Option

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
    # The catch rule is second: heal fires before it and run after it, so what the catch noul
    # decides here is only really the catch noul's if neither of those would have fired.
    answers = f["response"]["answers"]
    assert answers.get("heal", {}).get("noul", 0.0) <= HEAL_THRESHOLD
    assert answers.get("run", {}).get("noul", 0.0) <= RUN_THRESHOLD
    catch = f["response"]["answers"]["catch"]["noul"]
    assert (d.action == "throw a Poké Ball") == (catch > CATCH_THRESHOLD)
    assert d.fallback is False


def test_heal_fixture_agrees_with_the_heal_noul():
    """The recorded answer is heal 0.21, under HEAL_THRESHOLD: a CHARMANDER on `low` hp with
    Potions in the bag, and Jev still preferred to attack. Same pinning as the catch fixture --
    the noul and the action agree, whichever way the noul goes."""
    f, d = battle("battle_heal")
    # Heal is the first rule in the policy, so nothing earlier can pre-empt it: the hp bucket
    # below is the whole precondition -- the rule also requires low or critical hp.
    assert f["state_json"]["our_pokemon"]["hp"] in ("low", "critical")
    assert f["state_json"]["bag"]["potions"] is True and "heal" in f["questions"]
    heal = f["response"]["answers"]["heal"]["noul"]
    assert (d.action == "use a Potion") == (heal > HEAL_THRESHOLD)
    assert d.fallback is False


def _option_from_labelled(option_id: str, labelled: str) -> Option:
    """Rebuild the `Option` stub `decide_explore` needs from a fixture's `state_json["options"]`
    entry: `kind` from the id's prefix before the first "_" (an id with none, like "heal" or
    "milestone", is its own kind), `text` with the trailing " (word)" stripped, and `memory` the
    word itself. No legs or after -- decide_explore only reads id, kind, and text."""
    text, _, tail = labelled.rpartition(" (")
    memory = tail[:-1] if tail.endswith(")") else tail
    kind = option_id.split("_", 1)[0]
    return Option(id=option_id, kind=kind, text=text, memory=memory, legs=(), after=None)


def test_explore_fixture_picks_an_offered_option():
    """Jev chose "heal" at probability 0.51 (confidence 0.47) -- the recorded state has a hurt
    lead standing in Viridian City with a route to the Pokémon Center, so the heal option and the
    move together read as `needs_heal` 0.65 backing up a judgment that the party should mend up
    before whatever the milestone or an old man's chat has to offer."""
    f = load("explore_viridian")
    options = [_option_from_labelled(oid, labelled) for oid, labelled in f["state_json"]["options"].items()]
    d = decide_explore(
        f["state_json"],
        f["questions"],
        f["response"],
        options,
        model=f["response"]["model"],
        input_tokens=f["response"]["usage"]["input_tokens"],
        latency_ms=f["latency_ms"],
    )
    assert d.fallback is False
    assert d.action_value.option_id in f["state_json"]["options"]
    assert d.action_value.option_id == "heal"  # what was recorded: a re-record that changes it says so


def test_switch_fixture_agrees_with_the_switch_noul():
    """The recorded answer is switch 0.15 (with switch_to PIDGEY at 1.00 had it switched), so
    the turn is a move. A switch names a bench label and never an index -- the loop resolves it
    with brain.battle.bench_slots -- so the label is what a fixture can check."""
    f, d = battle("battle_switch")
    labels = [m["label"] for m in f["state_json"]["bench"]]
    assert len(labels) == 1 and labels[0]  # whichever species Route 1 rolled when the state was made
    assert f["state_json"]["party"] == "two" and "switch" in f["questions"]
    # Switch is the last rule before the plain move, so heal, catch, and run all have to have
    # stayed under their thresholds for the switch noul to be what decided this turn.
    answers = f["response"]["answers"]
    assert answers.get("heal", {}).get("noul", 0.0) <= HEAL_THRESHOLD
    assert answers.get("catch", {}).get("noul", 0.0) <= CATCH_THRESHOLD
    assert answers.get("run", {}).get("noul", 0.0) <= RUN_THRESHOLD
    switch = f["response"]["answers"]["switch"]["noul"]
    assert (d.action_value.kind == "switch") == (switch > SWITCH_THRESHOLD)
    assert d.fallback is False
    if d.action_value.kind == "switch":
        assert d.action_value.target == labels[0] and d.action_value.slot is None
    else:
        assert d.action_value.kind == "move"
