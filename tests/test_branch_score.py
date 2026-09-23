import math
import random

from jevplays.branch.score import answer_spread, bootstrap_ci, headline, score_decision, seed_frames
from jevplays.branch.store import BranchKey, BranchResult, DecisionInfo


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


def rows(frames_by_alt):
    out = []
    for alt, frames in frames_by_alt.items():
        for seed, f in enumerate(frames):
            outcome = "capped" if f is None else "done"
            out.append((BranchKey(1, alt, seed), BranchResult(outcome, f, 0, 0, 0)))
    return out


INFO = DecisionInfo(1, "battle", "move:A", ["move:A", "move:B", "run"], "move:B", None, 1000)


def test_seed_frames_turns_capped_into_infinity_and_drops_errors():
    r = rows({"move:A": [60, None]}) + [(BranchKey(1, "run", 0), BranchResult("error", None, 0, 0, 0, "x"))]
    assert seed_frames(r) == {"move:A": {0: 60.0, 1: math.inf}}


def test_regret_is_chosen_minus_best_in_seconds_on_the_scoring_seeds():
    # seeds 0-3 pick the best (B), seeds 4-7 score it
    r = rows(
        {
            "move:A": [600] * 8,
            "move:B": [300, 300, 300, 300, 360, 360, 360, 360],
            "run": [900] * 8,
        }
    )
    s = score_decision(INFO, r, seeds=8, rng=random.Random(0))
    assert s.best == "move:B"
    assert s.regret_s == (600 - 360) / 60
    assert s.tied is False
    assert s.baselines["strongest"] == 0.0
    assert s.baselines["random"] == ((600 - 360) + 0 + (900 - 360)) / 60 / 3


def test_a_choice_that_is_the_best_has_zero_regret_and_is_tied():
    r = rows({"move:A": [300] * 8, "move:B": [600] * 8, "run": [900] * 8})
    s = score_decision(INFO, r, seeds=8, rng=random.Random(0))
    assert s.regret_s == 0.0 and s.tied is True


def test_a_censored_chosen_alternative_has_no_regret():
    r = rows({"move:A": [None] * 8, "move:B": [300] * 8, "run": [900] * 8})
    assert score_decision(INFO, r, seeds=8, rng=random.Random(0)).regret_s is None


def test_bootstrap_is_reproducible_with_a_fixed_rng():
    values = [1.0, 2.0, 3.0, 10.0]
    assert bootstrap_ci(values, random.Random(0)) == bootstrap_ci(values, random.Random(0))
    lo, hi = bootstrap_ci(values, random.Random(0))
    assert lo <= 4.0 <= hi


def test_headline_splits_by_kind_and_counts_uncensored_decisions():
    good = score_decision(
        INFO, rows({"move:A": [300] * 8, "move:B": [600] * 8, "run": [900] * 8}), 8, random.Random(0)
    )
    bad = score_decision(
        INFO, rows({"move:A": [None] * 8, "move:B": [300] * 8, "run": [900] * 8}), 8, random.Random(0)
    )
    h = headline([good, bad], random.Random(0))
    assert set(h) == {"battle"}
    assert h["battle"]["decisions"] == 2 and h["battle"]["scored"] == 1
    assert h["battle"]["mean_regret_s"] == 0.0
    # `bad` chose an alternative that never finished while the best did: judged, and not tied
    assert h["battle"]["best_or_tied"] == 0.5
