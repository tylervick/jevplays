"""#80: Jev picks the starter. Code asks one question at Oak's table and walks to the ball."""

from jevplays.brain.starter import STARTERS, decide_starter, starter_questions, starter_state
from jevplays.executor.goals import MILESTONES


def response(choice, probabilities=None):
    probabilities = probabilities or {choice: 0.8}
    return {
        "model": "jev-test",
        "usage": {"input_tokens": 9},
        "answers": {
            "starter": {"type": "choice", "choice": choice, "probabilities": probabilities, "confidence": 0.8}
        },
    }


def test_the_question_offers_the_three_starters_by_type_and_never_a_matchup():
    """Jev judges from names, types, and where the run is going. Which type beats which lives
    in state/types.py and is never sent (CLAUDE.md): whether Jev knows Brock fields Rock types is
    its own judgment, and the interesting one to watch."""
    sj = starter_state(MILESTONES[-1].description)
    qs = starter_questions(sj)
    assert set(qs["starter"]["criteria"]) == {"BULBASAUR", "CHARMANDER", "SQUIRTLE"}
    assert qs["starter"]["type"] == "choice"
    assert "Water-type" in qs["starter"]["criteria"]["SQUIRTLE"]
    assert "Brock" in sj["goal"]
    text = str(sj) + str(qs)
    for leak in ("effective", "weak", "resist", "Rock"):
        assert leak not in text


def test_an_answer_naming_a_starter_takes_it():
    sj = starter_state("x")
    qs = starter_questions(sj)
    d = decide_starter(sj, qs, response("SQUIRTLE"), model="jev-test", input_tokens=9, latency_ms=5)
    assert d.kind == "starter" and d.action == "take SQUIRTLE"
    assert d.action_value.species == "SQUIRTLE"
    assert d.fallback is False and d.answers["starter"]["applied"] is True


def test_an_answer_that_is_not_one_of_the_three_falls_back_to_charmander_and_says_so():
    sj = starter_state("x")
    qs = starter_questions(sj)
    d = decide_starter(sj, qs, response("PIKACHU"), model="jev-test", input_tokens=9, latency_ms=5)
    assert d.action_value.species == "CHARMANDER"
    assert d.fallback is True and "PIKACHU" in d.fallback_reason


def test_every_starter_has_a_tile_to_stand_on():
    from jevplays.executor.goals import STARTER_TILES

    assert set(STARTER_TILES) == set(STARTERS)
    assert STARTER_TILES == {"CHARMANDER": (6, 4), "SQUIRTLE": (7, 4), "BULBASAUR": (8, 4)}  # ROM-checked
