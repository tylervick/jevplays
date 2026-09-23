import math
import random

from jevplays.branch.score import (
    FRAMES_PER_SECOND,
    answer_spread,
    as_good_as_best,
    bootstrap_ci,
    headline,
    score_decision,
    seed_frames,
)
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
    s = score_decision(INFO, r, seeds=8)
    assert s.best == "move:B"
    assert s.regret_s == (600 - 360) / 60
    assert s.tied is False
    assert s.baselines["strongest"] == 0.0
    assert s.baselines["random"] == ((600 - 360) + 0 + (900 - 360)) / 60 / 3


def test_a_choice_that_is_the_best_has_zero_regret_and_is_tied():
    r = rows({"move:A": [300] * 8, "move:B": [600] * 8, "run": [900] * 8})
    s = score_decision(INFO, r, seeds=8)
    assert s.regret_s == 0.0 and s.tied is True


def test_a_censored_chosen_alternative_has_no_regret():
    r = rows({"move:A": [None] * 8, "move:B": [300] * 8, "run": [900] * 8})
    assert score_decision(INFO, r, seeds=8).regret_s is None


def test_bootstrap_is_reproducible_with_a_fixed_rng():
    values = [1.0, 2.0, 3.0, 10.0]
    assert bootstrap_ci(values, random.Random(0)) == bootstrap_ci(values, random.Random(0))
    lo, hi = bootstrap_ci(values, random.Random(0))
    assert lo <= 4.0 <= hi


def test_headline_splits_by_kind_and_counts_uncensored_decisions():
    good = score_decision(INFO, rows({"move:A": [300] * 8, "move:B": [600] * 8, "run": [900] * 8}), 8)
    bad = score_decision(INFO, rows({"move:A": [None] * 8, "move:B": [300] * 8, "run": [900] * 8}), 8)
    h = headline([good, bad], random.Random(0))
    assert set(h) == {"battle"}
    assert h["battle"]["decisions"] == 2 and h["battle"]["scored"] == 1
    assert h["battle"]["mean_regret_s"] == 0.0
    # `bad` chose an alternative that never finished while the best did: judged, and not tied
    assert h["battle"]["best_or_tied"] == 0.5


def test_a_choice_better_than_best_on_the_scoring_seeds_still_counts_as_tied():
    # chosen (A) beats the selection-half winner (B) on the scoring half: [400]*4+[300]*4 vs
    # [350]*4+[360]*4. Best is still picked from the selection half (B, 350 < 400), but A's
    # scoring-half advantage must count as "best or tied", not a miss.
    r = rows({"move:A": [400] * 4 + [300] * 4, "move:B": [350] * 4 + [360] * 4, "run": [900] * 8})
    s = score_decision(INFO, r, seeds=8)
    assert s.best == "move:B"
    assert s.regret_s == -1.0
    assert s.tied is True


def test_a_capped_best_on_one_scoring_seed_does_not_force_a_tie_to_false():
    # move:B is picked as best from the selection half (300 < 600). On the scoring half it caps
    # on seed 4 (frames None) while move:A finishes there instead; the two are equal (360) on
    # seeds 5-7. A finished choice against a capped best is "no later", and so is an equal time,
    # so a lone infinite pair must not, by itself, force `tied` to False.
    r = rows(
        {
            "move:A": [600] * 4 + [500, 360, 360, 360],
            "move:B": [300] * 4 + [None, 360, 360, 360],
            "run": [900] * 8,
        }
    )
    s = score_decision(INFO, r, seeds=8)
    assert s.best == "move:B"
    assert s.tied is True


def test_all_alternatives_censored_reports_no_best_or_regret():
    # The chosen alternative is deliberately not first in `alternatives`, so a fix that just
    # picked the first alternative when every median ties at infinity would still pass a naive
    # check; asserting `best is None` rules that out.
    info = DecisionInfo(1, "battle", "move:B", ["move:A", "move:B", "run"], "move:B", None, 1000)
    r = rows({"move:A": [None] * 8, "move:B": [None] * 8, "run": [None] * 8})
    s = score_decision(info, r, seeds=8)
    assert s.best is None
    assert s.regret_s is None
    assert s.tied is None


def test_a_decision_with_only_error_rows_has_no_best_and_does_not_crash():
    r = [
        (BranchKey(1, alt, seed), BranchResult("error", None, 0, 0, 0, "boom"))
        for alt in ("move:A", "move:B", "run")
        for seed in range(8)
    ]
    s = score_decision(INFO, r, seeds=8)
    assert s.best is None
    assert s.regret_s is None
    assert s.tied is None


def test_headline_counts_a_decision_whose_chosen_alternative_never_finished():
    good = score_decision(INFO, rows({"move:A": [300] * 8, "move:B": [600] * 8, "run": [900] * 8}), 8)
    bad = score_decision(INFO, rows({"move:A": [None] * 8, "move:B": [300] * 8, "run": [900] * 8}), 8)
    h = headline([good, bad], random.Random(0))
    assert h["battle"]["censored_chosen"] == 1


S = FRAMES_PER_SECOND


def test_one_lucky_seed_does_not_make_a_choice_that_lost_by_minutes_as_good_as_best():
    """The final review's counterexample: paired (chosen - best) of -1 s, 600 s, 700 s and 800 s on
    the scoring seeds. A bootstrap of four values has the minimum (-1 s) as its lower bound and so
    called this a tie; chosen was no later on only one seed of four, so it is not as good."""
    best = [300 * S] * 4 + [1000 * S] * 4
    chosen = [900 * S] * 4 + [999 * S, 1600 * S, 1700 * S, 1800 * S]
    r = rows({"move:A": chosen, "move:B": best, "run": [5000 * S] * 8})
    s = score_decision(INFO, r, seeds=8)
    assert s.best == "move:B"
    assert s.tied is False


def test_no_later_on_exactly_half_the_scoring_seeds_is_as_good_as_best():
    r = rows({"move:A": [900] * 4 + [300, 360, 500, 500], "move:B": [300] * 4 + [360] * 4, "run": [2000] * 8})
    s = score_decision(INFO, r, seeds=8)
    assert s.best == "move:B"
    assert s.tied is True


def test_no_later_on_fewer_than_half_the_scoring_seeds_is_not_as_good():
    r = rows({"move:A": [900] * 4 + [300, 500, 500, 500], "move:B": [300] * 4 + [360] * 4, "run": [2000] * 8})
    assert score_decision(INFO, r, seeds=8).tied is False


def test_as_good_as_best_pairs_by_seed_and_counts_both_capped_as_no_later():
    inf = math.inf
    scoring = range(4, 8)
    # seed 4: both capped (no later); seed 5: chosen finished, best capped (no later);
    # seeds 6, 7: chosen later -> 2 of 4, as good
    assert as_good_as_best({4: inf, 5: 100.0, 6: 500.0, 7: 500.0}, {4: inf, 5: inf, 6: 1.0, 7: 1.0}, scoring)
    # chosen capped where the best finished is later
    assert not as_good_as_best({4: inf, 5: inf, 6: inf}, {4: 1.0, 5: 1.0, 6: 1.0}, scoring)
    # only seeds present for both are paired: seed 4 alone, no later
    assert as_good_as_best({4: 1.0, 6: 9.0}, {4: 1.0, 7: 1.0}, scoring)
    assert as_good_as_best({4: 1.0}, {5: 1.0}, scoring) is None
