"""Scoring a branch measurement. Pure functions over rows, so every number the report prints can
be recomputed from `branches.sqlite` alone."""

import math
import random
import statistics
from dataclasses import dataclass

from jevplays.branch.store import BranchKey, BranchResult, DecisionInfo

FRAMES_PER_SECOND = 60
BOOTSTRAP_SAMPLES = 2000


def _values(response: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for qid, answer in response.get("answers", {}).items():
        if answer.get("type") == "noul":
            out[qid] = float(answer["noul"])
        elif answer.get("type") == "choice":
            for option, p in answer.get("probabilities", {}).items():
                out[f"{qid}:{option}"] = float(p)
    return out


def answer_spread(responses: list[dict]) -> float:
    """The largest absolute difference, across `responses` to one input, of any probability or
    noul. An answer one response has and another lacks counts as a spread of 1.0."""
    values = [_values(r) for r in responses]
    keys = set().union(*values) if values else set()
    spread = 0.0
    for key in keys:
        seen = [v[key] for v in values if key in v]
        if len(seen) < len(values):
            return 1.0
        spread = max(spread, max(seen) - min(seen))
    return spread


def seed_frames(rows: list[tuple[BranchKey, BranchResult]]) -> dict[str, dict[int, float]]:
    """alternative -> seed -> frames to the milestone; a capped or stalled branch is infinity (it
    took at least the cap), and an errored one is left out."""
    out: dict[str, dict[int, float]] = {}
    for key, result in rows:
        if result.outcome == "error":
            continue
        frames = float(result.frames) if result.outcome == "done" else math.inf
        out.setdefault(key.alternative, {})[key.seed] = frames
    return out


def complete(info: DecisionInfo, rows: list[tuple[BranchKey, BranchResult]], seeds: int) -> bool:
    """Whether every alternative of the decision has a finished branch row (any outcome, error
    included) for every seed. An incomplete decision -- a measurement interrupted or still
    running -- stays out of the headline, so partial data does not pose as a result."""
    wanted = set(info.alternatives)
    finished = {(k.alternative, k.seed) for k, _ in rows if k.alternative in wanted and 0 <= k.seed < seeds}
    return len(finished) == len(wanted) * seeds


def _median(frames: dict[int, float], seeds: range) -> float:
    values = [frames[s] for s in seeds if s in frames]
    return statistics.median(values) if values else math.inf


def bootstrap_ci(
    values: list[float], rng: random.Random, stat=statistics.fmean, n: int = BOOTSTRAP_SAMPLES
) -> tuple[float, float]:
    """A 95% percentile bootstrap interval of `stat` over `values`."""
    draws = sorted(stat(rng.choices(values, k=len(values))) for _ in range(n))
    return draws[int(0.025 * n)], draws[int(0.975 * n) - 1]


@dataclass
class DecisionScore:
    decision: int
    kind: str
    chosen: str
    best: str | None
    regret_s: float | None
    tied: bool | None
    """As good as the best, by `as_good_as_best` (TIE_RULE); None when there is no best."""
    baselines: dict[str, float | None]
    censored_chosen: bool
    strongest_set: bool
    offline_set: bool
    random_censored: int = 0
    """Alternatives left out of the `random` baseline's mean because their regret was not finite."""


TIE_RULE = (
    "as good as best: Jev's choice is the held-out best, or reached the milestone no later than it "
    "on at least half of the scoring seeds (paired by seed; a seed where both capped counts as no later)"
)


def as_good_as_best(chosen: dict[int, float], best: dict[int, float], scoring: range) -> bool | None:
    """The tie rule (spec: "Scoring"). Paired by seed over the scoring seeds present for both, with
    a capped or stalled branch as infinity: the chosen alternative is as good as the best when it
    reached the milestone no later than the best (chosen <= best) on at least half of them. A seed
    where both capped counts as no later -- neither got there within the cap, so the choice lost
    nothing measurable on it -- and a finished choice against a capped best counts as no later too.
    None when no scoring seed is present for both.

    A countable rule, not a bootstrap interval: with K=8 there are 4 paired values, and a 95%
    bootstrap of 4 values is degenerate (its lower bound is just the minimum), so one lucky seed
    would call a choice that lost by minutes on the other three a tie."""
    paired = [s for s in scoring if s in chosen and s in best]
    if not paired:
        return None
    no_later = sum(1 for s in paired if chosen[s] <= best[s])
    return 2 * no_later >= len(paired)


def score_decision(info: DecisionInfo, rows, seeds: int) -> DecisionScore:
    """The best alternative is picked on the first half of the seeds and scored on the second, so
    choosing the best of several noisy medians does not flatter it (spec: "Scoring"). When no
    alternative even finished on the selection half (every seed of every alternative capped,
    stalled, or errored), there is nothing to pick a winner from: `best`, `regret_s`, and `tied`
    all stay None rather than falling back to list order."""
    frames = seed_frames(rows)
    select, scoring = range(0, seeds // 2), range(seeds // 2, seeds)
    alts = [a for a in info.alternatives if a in frames]
    strongest_set = info.strongest is not None
    offline_set = info.offline is not None

    selection_medians = {a: _median(frames[a], select) for a in alts}
    if not alts or min(selection_medians.values()) == math.inf:
        empty: dict[str, float | None] = {"random": None, "strongest": None, "offline": None}
        return DecisionScore(
            info.decision, info.kind, info.chosen, None, None, None, empty, False, strongest_set, offline_set
        )

    best = min(alts, key=lambda a: selection_medians[a])
    best_score = _median(frames[best], scoring)

    def regret(alt: str | None) -> float | None:
        if alt is None or alt not in frames:
            return None
        r = _median(frames[alt], scoring) - best_score
        return r / FRAMES_PER_SECOND if math.isfinite(r) else None

    chosen_regret = regret(info.chosen)

    # Disclosed separately from a None regret_s (spec: "Scoring" baselines) -- true only when the
    # chosen alternative specifically never finished on the scoring half while the best one did,
    # not merely whenever regret happens to come out None (e.g. the best itself capping too).
    chosen_scoring_median = _median(frames[info.chosen], scoring) if info.chosen in frames else None
    censored_chosen = (
        chosen_scoring_median is not None and math.isinf(chosen_scoring_median) and math.isfinite(best_score)
    )

    tied = None
    if info.chosen == best:
        tied = True
    elif info.chosen in frames:
        tied = as_good_as_best(frames[info.chosen], frames[best], scoring)

    regrets = [regret(a) for a in alts]
    every = [r for r in regrets if r is not None]
    baselines = {
        "random": statistics.fmean(every) if every else None,
        "strongest": regret(info.strongest),
        "offline": regret(info.offline),
    }
    return DecisionScore(
        info.decision,
        info.kind,
        info.chosen,
        best,
        chosen_regret,
        tied,
        baselines,
        censored_chosen,
        strongest_set,
        offline_set,
        len(regrets) - len(every),
    )


BASELINES = ("random", "strongest", "offline")


def headline(scores: list[DecisionScore], rng: random.Random) -> dict[str, dict]:
    """Per kind: how many decisions, how many had a finite regret, how many of those had a chosen
    alternative that never finished while the best one did (`censored_chosen` -- a hint that the
    mean regret is a floor, not the true cost), the mean regret with its 95% interval, and the
    share where Jev's choice was as good as the best (TIE_RULE).

    Each baseline is paired with Jev (spec: "Scoring"): over the decisions where both Jev's regret
    and the baseline's are finite, `<name>_paired` counts them, `<name>_jev_s` and `<name>_regret_s`
    are the two mean regrets on that same set, and `<name>_diff_s` is the mean of (baseline - Jev)
    with `<name>_diff_ci` its 95% bootstrap interval over decisions (positive: Jev did better).
    `<name>_missing` counts the decisions of that kind the baseline could not be scored for (one
    that was never set, such as no offline milestone-first pick, is not missing).
    `random_censored_alternatives` sums, over random's paired decisions, the alternatives its
    per-decision mean had to drop because their regret was not finite."""
    out: dict[str, dict] = {}
    applicable = {
        "random": lambda _s: True,
        "strongest": lambda s: s.strongest_set,
        "offline": lambda s: s.offline_set,
    }
    for kind in sorted({s.kind for s in scores}):
        mine = [s for s in scores if s.kind == kind]
        finite = [s.regret_s for s in mine if s.regret_s is not None]
        judged = [s.tied for s in mine if s.tied is not None]
        row: dict = {
            "decisions": len(mine),
            "scored": len(finite),
            "censored_chosen": sum(1 for s in mine if s.censored_chosen),
        }
        row["mean_regret_s"] = statistics.fmean(finite) if finite else None
        row["ci"] = bootstrap_ci(finite, rng) if len(finite) > 1 else None
        row["best_or_tied"] = sum(judged) / len(judged) if judged else None
        for name in BASELINES:
            paired = [s for s in mine if s.regret_s is not None and s.baselines.get(name) is not None]
            jev = [s.regret_s for s in paired]
            rule = [s.baselines[name] for s in paired]
            diffs = [b - j for b, j in zip(rule, jev, strict=True)]
            row[f"{name}_paired"] = len(paired)
            row[f"{name}_jev_s"] = statistics.fmean(jev) if jev else None
            row[f"{name}_regret_s"] = statistics.fmean(rule) if rule else None
            row[f"{name}_diff_s"] = statistics.fmean(diffs) if diffs else None
            row[f"{name}_diff_ci"] = bootstrap_ci(diffs, rng) if len(diffs) > 1 else None
            row[f"{name}_missing"] = sum(
                1 for s in mine if applicable[name](s) and s.baselines.get(name) is None
            )
            if name == "random":
                row["random_censored_alternatives"] = sum(s.random_censored for s in paired)
        out[kind] = row
    return out
