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
    best: str
    regret_s: float | None
    tied: bool | None
    baselines: dict[str, float | None]


def score_decision(info: DecisionInfo, rows, seeds: int, rng: random.Random) -> DecisionScore:
    """The best alternative is picked on the first half of the seeds and scored on the second, so
    choosing the best of several noisy medians does not flatter it (spec: "Scoring")."""
    frames = seed_frames(rows)
    select, scoring = range(0, seeds // 2), range(seeds // 2, seeds)
    alts = [a for a in info.alternatives if a in frames]
    best = min(alts, key=lambda a: _median(frames[a], select))
    best_score = _median(frames[best], scoring)

    def regret(alt: str | None) -> float | None:
        if alt is None or alt not in frames:
            return None
        r = _median(frames[alt], scoring) - best_score
        return r / FRAMES_PER_SECOND if math.isfinite(r) else None

    chosen_regret = regret(info.chosen)
    tied = None
    if info.chosen in frames:
        pairs = [
            frames[info.chosen][s] - frames[best][s]
            for s in scoring
            if s in frames[info.chosen] and s in frames[best]
        ]
        pairs = [d for d in pairs if not math.isnan(d)]
        if info.chosen == best:
            tied = True
        elif pairs and all(math.isfinite(d) for d in pairs):
            lo, hi = bootstrap_ci(pairs, rng, stat=statistics.median)
            tied = lo <= 0 <= hi
        elif pairs:
            tied = False
    every = [r for r in (regret(a) for a in alts) if r is not None]
    baselines = {
        "random": statistics.fmean(every) if every else None,
        "strongest": regret(info.strongest),
        "offline": regret(info.offline),
    }
    return DecisionScore(info.decision, info.kind, info.chosen, best, chosen_regret, tied, baselines)


def headline(scores: list[DecisionScore], rng: random.Random) -> dict[str, dict]:
    """Per kind: how many decisions, how many had a finite regret, the mean regret with its 95%
    interval, the share where Jev's choice was the best or tied with it, and each baseline's mean."""
    out: dict[str, dict] = {}
    for kind in sorted({s.kind for s in scores}):
        mine = [s for s in scores if s.kind == kind]
        finite = [s.regret_s for s in mine if s.regret_s is not None]
        judged = [s.tied for s in mine if s.tied is not None]
        row: dict = {"decisions": len(mine), "scored": len(finite)}
        row["mean_regret_s"] = statistics.fmean(finite) if finite else None
        row["ci"] = bootstrap_ci(finite, rng) if len(finite) > 1 else None
        row["best_or_tied"] = sum(judged) / len(judged) if judged else None
        for name in ("random", "strongest", "offline"):
            values = [s.baselines[name] for s in mine if s.baselines.get(name) is not None]
            row[f"{name}_regret_s"] = statistics.fmean(values) if values else None
        out[kind] = row
    return out
