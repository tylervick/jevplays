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
    baselines: dict[str, float | None]
    censored_chosen: bool
    strongest_set: bool
    offline_set: bool


def score_decision(info: DecisionInfo, rows, seeds: int, rng: random.Random) -> DecisionScore:
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
    if info.chosen in frames:
        pairs = [
            frames[info.chosen][s] - frames[best][s]
            for s in scoring
            if s in frames[info.chosen] and s in frames[best]
        ]
        # Drop only both-censored pairs (inf - inf = nan); keep a lone infinite pair (one side
        # finished, the other capped on that seed) in the bootstrap so it doesn't, by itself,
        # force the decision to "not tied" -- `median_low` never averages, so it never turns an
        # infinite pair into a nan the way `fmean` or `median`'s midpoint would.
        pairs = [d for d in pairs if not math.isnan(d)]
        if info.chosen == best:
            tied = True
        elif pairs:
            lo, _hi = bootstrap_ci(pairs, rng, stat=statistics.median_low)
            # "Best or tied": the interval doesn't show the choice as worse than best. This also
            # covers a choice that's actually *better* than the selection-half winner -- that's
            # not a miss either.
            tied = lo <= 0

    every = [r for r in (regret(a) for a in alts) if r is not None]
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
    )


def headline(scores: list[DecisionScore], rng: random.Random) -> dict[str, dict]:
    """Per kind: how many decisions, how many had a finite regret, how many of those had a chosen
    alternative that never finished while the best one did (`censored_chosen` -- a hint that the
    mean regret is a floor, not the true cost), the mean regret with its 95% interval, the share
    where Jev's choice was the best or tied with it, and each baseline's mean regret plus how many
    decisions of that kind it could not be scored for (a baseline that was never set, such as no
    offline milestone-first pick for that decision, is not counted as missing)."""
    out: dict[str, dict] = {}
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
        applicable = {
            "random": lambda _s: True,
            "strongest": lambda s: s.strongest_set,
            "offline": lambda s: s.offline_set,
        }
        for name, is_applicable in applicable.items():
            values = [s.baselines[name] for s in mine if s.baselines.get(name) is not None]
            row[f"{name}_regret_s"] = statistics.fmean(values) if values else None
            row[f"{name}_missing"] = sum(
                1 for s in mine if is_applicable(s) and s.baselines.get(name) is None
            )
        out[kind] = row
    return out
