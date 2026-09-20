import json
from pathlib import Path

import pytest

from jevplays.brain.battle import decide_battle

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
