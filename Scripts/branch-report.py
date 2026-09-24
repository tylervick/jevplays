#!/usr/bin/env -S uv run
"""Score a branch measurement (#82).

    uv run Scripts/branch-report.py RUN_DIR [RUN_DIR ...]
    uv run Scripts/branch-report.py RUN_DIR --decision N
    uv run Scripts/branch-report.py RUN_DIR --export N ALTERNATIVE SEED OUT_DIR

Reads RUN_DIR/branches/branches.sqlite. With several RUN_DIRs the measurements are pooled: each
run's counts print first, then one headline over all their decisions; runs measured with a
different model or K are refused. The default prints the counts (a decision is incomplete
until every alternative has a finished branch for every seed, and is left out of the headline),
then per decision kind the mean regret (seconds of game time Jev's choice cost against the best
alternative) with its 95% interval, the share of decisions where Jev's choice was as good as the
best (the rule is printed under the headline), and three first-action rules -- a random
alternative, the strongest move, and the offline milestone-first pick -- each paired with Jev on
the decisions both have a regret for: n, both means, and (rule − Jev) with its 95% interval over
decisions. `--by-choice` prints, after the headline, one line per kind of alternative Jev chose
within each decision kind (move, switch, heal, run, catch for battle; exit, door, npc, grass,
milestone, heal for explore) -- n decisions, mean regret with its 95% interval, and the as-good-
as-best share -- sorted by n descending. `--decision` prints one decision's alternatives;
`--export` writes one branch as a run directory for `jevplays replay`.
"""

import argparse
import math
import random
import statistics
import sys
from collections import Counter
from pathlib import Path

from jevplays.branch.score import (
    FRAMES_PER_SECOND,
    TIE_RULE,
    choice_kind_of,
    complete,
    headline,
    score_decision,
    seed_frames,
)
from jevplays.branch.store import BranchKey, BranchStore, export_branch


def _s(value) -> str:
    return "-" if value is None else f"{value:.1f}s"


def _measured(store: BranchStore) -> tuple[dict, list]:
    """Print one measurement's counts and return its meta and the scores of its complete
    decisions. An incomplete decision still shows with --decision, but no headline counts it."""
    meta = store.meta()
    seeds = int(meta.get("seeds", "8"))
    infos = store.decision_infos()
    rows = store.branches()
    outcomes = Counter(r.outcome for _, r in rows)
    skipped = Counter(reason.split(":")[0] for reason in store.skipped().values())
    calls = sum(r.jev_calls for _, r in rows)
    hits = sum(r.cache_hits for _, r in rows)
    print(f"run {meta.get('run')}  model {meta.get('model')}  K={seeds}")
    by_decision = {i.decision: store.branches(i.decision) for i in infos}
    whole = [i for i in infos if complete(i, by_decision[i.decision], seeds)]
    print(f"decisions {len(infos)}  incomplete {len(infos) - len(whole)}  skipped {dict(skipped)}")
    print(f"branches {len(rows)}  {dict(outcomes)}  jev calls {calls}  cache hits {hits}")
    if "spread" in meta:
        print(f"determinism check: largest answer spread {meta['spread']}")
    return meta, [score_decision(i, by_decision[i.decision], seeds) for i in whole]


def _unpoolable(stores: list[BranchStore]) -> str | None:
    """Why these measurements cannot be pooled, or None. A different model is a different Jev,
    and a different K splits the seeds differently, so either would mix two measurements."""
    metas = [s.meta() for s in stores]
    models = {m.get("model") for m in metas}
    if len(models) > 1:
        return f"the runs were measured with different models: {', '.join(sorted(map(str, models)))}"
    ks = {m.get("seeds") for m in metas}
    if len(ks) > 1:
        return f"the runs were branched with different K: {', '.join(sorted(map(str, ks)))}"
    return None


def _print_by_choice(scores: list, rng: random.Random) -> None:
    """Per decision kind, one line per choice kind Jev's chosen alternative fell into
    (`choice_kind_of`): n decisions, mean regret with its 95% interval, and the as-good-as-best
    share -- reusing `headline` on the subset rather than duplicating its math. Sorted by n
    decisions descending."""
    for kind in sorted({s.kind for s in scores}):
        mine = [s for s in scores if s.kind == kind]
        groups: dict[str, list] = {}
        for s in mine:
            groups.setdefault(choice_kind_of(s.chosen), []).append(s)
        rows = [(ck, headline(group, rng)[kind]) for ck, group in groups.items()]
        rows.sort(key=lambda kv: kv[1]["decisions"], reverse=True)
        print(f"{kind} by choice:")
        for choice_kind, row in rows:
            ci = row["ci"]
            interval = f" [{ci[0]:.1f}, {ci[1]:.1f}]" if ci else ""
            tied = "-" if row["best_or_tied"] is None else f"{row['best_or_tied']:.0%}"
            print(
                f"  {choice_kind:<10} n {row['decisions']:>4}  regret {_s(row['mean_regret_s'])}{interval}  "
                f"as good as best {tied}"
            )


def summary(stores: list[BranchStore], by_choice: bool = False) -> int:
    why = _unpoolable(stores)
    if why is not None:
        print(f"branch-report: cannot pool: {why}", file=sys.stderr)
        return 2
    scores = []
    for store in stores:
        _meta, run_scores = _measured(store)
        scores += run_scores
    if len(stores) > 1:
        print(
            f"pooled {len(stores)} runs, {len(scores)} complete decisions. The intervals resample "
            "decisions as if independent; decisions in one run share a trajectory, so the true "
            "uncertainty is somewhat wider."
        )
    rng = random.Random(0)
    rules = {"random": "random", "strongest": "strongest move", "offline": "offline pick"}
    for kind, row in headline(scores, rng).items():
        ci = row["ci"]
        interval = f" [{ci[0]:.1f}, {ci[1]:.1f}]" if ci else ""
        tied = "-" if row["best_or_tied"] is None else f"{row['best_or_tied']:.0%}"
        print(
            f"{kind:<8} decisions {row['decisions']} scored {row['scored']} "
            f"censored_chosen {row['censored_chosen']}  "
            f"regret {_s(row['mean_regret_s'])}{interval}  as good as best {tied}"
        )
        for name, label in rules.items():
            diff, dci = row[f"{name}_diff_s"], row[f"{name}_diff_ci"]
            diff_str = "-" if diff is None else f"{diff:+.1f}s"
            diff_ci = f" [{dci[0]:.1f}, {dci[1]:.1f}]" if dci else ""
            extra = (
                f", dropped {row['random_censored_alternatives']} censored alternatives"
                if name == "random"
                else ""
            )
            print(
                f"  vs {label}: n {row[f'{name}_paired']}, Jev {_s(row[f'{name}_jev_s'])}, "
                f"rule {_s(row[f'{name}_regret_s'])}, rule − Jev {diff_str}{diff_ci}"
                f"  ({row[f'{name}_missing']} missing{extra})"
            )
    print(TIE_RULE)
    if by_choice:
        _print_by_choice(scores, rng)
    return 0


def one_decision(store: BranchStore, n: int) -> int:
    info = next((i for i in store.decision_infos() if i.decision == n), None)
    if info is None:
        print(f"decision {n} was not measured: {store.skipped().get(n, 'not a candidate')}", file=sys.stderr)
        return 2
    rows = store.branches(n)
    frames = seed_frames(rows)
    print(f"decision {n} ({info.kind}), Jev chose {info.chosen}")
    for alt in info.alternatives:
        values = sorted(frames.get(alt, {}).values())
        done = [v for v in values if v != float("inf")]
        median = statistics.median(values) / FRAMES_PER_SECOND if values else None
        median_str = "censored" if median is not None and math.isinf(median) else _s(median)
        spread = (max(done) - min(done)) / FRAMES_PER_SECOND if len(done) > 1 else None
        blackouts = sum(r.blackouts for k, r in rows if k.alternative == alt)
        mark = "*" if alt == info.chosen else " "
        print(
            f"{mark} {alt:<32} median {median_str}  spread {_s(spread)}  "
            f"censored {len(values) - len(done)}/{len(values)}  blackouts {blackouts}"
        )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", type=Path, nargs="+", metavar="RUN_DIR")
    ap.add_argument("--decision", type=int)
    ap.add_argument("--export", nargs=4, metavar=("N", "ALTERNATIVE", "SEED", "OUT_DIR"))
    ap.add_argument(
        "--by-choice",
        action="store_true",
        help="after the headline, break each decision kind's regret down by what Jev chose",
    )
    args = ap.parse_args()
    if (args.export or args.decision is not None) and len(args.runs) != 1:
        ap.error("--decision and --export take exactly one RUN_DIR")
    stores = []
    for run in args.runs:
        db = run / "branches" / "branches.sqlite"
        if not db.is_file():
            print(f"{db} does not exist; run `jevplays branch {run}` first", file=sys.stderr)
            return 2
        stores.append(BranchStore(db))
    if args.export:
        n, alt, seed, out = args.export
        print(export_branch(stores[0], BranchKey(int(n), alt, int(seed)), Path(out)))
        return 0
    if args.decision is not None:
        return one_decision(stores[0], args.decision)
    return summary(stores, by_choice=args.by_choice)


if __name__ == "__main__":
    sys.exit(main())
