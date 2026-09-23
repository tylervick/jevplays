from jevplays.branch.score import answer_spread


def _choice(p):
    return {
        "answers": {
            "move": {
                "type": "choice",
                "choice": "A",
                "probabilities": {"A": p, "B": 1 - p},
                "confidence": 0.5,
            }
        }
    }


def test_identical_responses_have_no_spread():
    assert answer_spread([_choice(0.7), _choice(0.7), _choice(0.7)]) == 0.0


def test_spread_is_the_largest_difference_in_any_probability_or_noul():
    a = {"answers": {"run": {"type": "noul", "noul": 0.10}, **_choice(0.70)["answers"]}}
    b = {"answers": {"run": {"type": "noul", "noul": 0.25}, **_choice(0.72)["answers"]}}
    assert abs(answer_spread([a, b]) - 0.15) < 1e-9


def test_an_answer_missing_from_one_response_counts_as_full_spread():
    a = {"answers": {"run": {"type": "noul", "noul": 0.1}}}
    b = {"answers": {}}
    assert answer_spread([a, b]) == 1.0
