import json
from pathlib import Path

import pytest

from jevplays.brain.battle import decide_battle
from jevplays.state.modes import Mode
from jevplays.state.snapshot import GameState

FIXTURES = Path(__file__).parent / "fixtures" / "responses"


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def rebuild(d: dict) -> GameState:
    from jevplays.state.snapshot import BagItem, Battle, Mon, Move

    def mon(m):
        return (
            None
            if m is None
            else Mon(**{**m, "types": tuple(m["types"]), "moves": tuple(Move(**mv) for mv in m["moves"])})
        )

    return GameState(
        **{
            **d,
            "mode": Mode(d["mode"]),
            "tile": tuple(d["tile"]),
            "menu_items": tuple(d["menu_items"]),
            "party": tuple(mon(m) for m in d["party"]),
            "active": mon(d["active"]),
            "enemy": mon(d["enemy"]),
            "battle": None if d["battle"] is None else Battle(**d["battle"]),
            "bag": tuple(BagItem(**b) for b in d["bag"]),
        }
    )


@pytest.mark.parametrize("name", ["battle_trainer", "battle_wild"])
def test_recorded_response_decodes_to_a_move(name):
    f = load(name)
    d = decide_battle(
        rebuild(f["state"]),
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
