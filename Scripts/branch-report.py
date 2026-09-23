#!/usr/bin/env -S uv run
"""Score a branch measurement (#82).

    uv run Scripts/branch-report.py RUN_DIR
    uv run Scripts/branch-report.py RUN_DIR --decision N
    uv run Scripts/branch-report.py RUN_DIR --export N ALTERNATIVE SEED OUT_DIR

Reads RUN_DIR/branches/branches.sqlite. The default prints the counts, then per decision kind the
mean regret (seconds of game time Jev's choice cost against the best alternative) with its 95%
interval, the share of decisions where Jev's choice was the best or tied with it, and the same
regret for three first-action rules: a random alternative, the strongest move, and the offline
milestone-first pick. `--decision` prints one decision's alternatives; `--export` writes one
branch as a run directory for `jevplays replay`.
"""

import argparse
import math
import random
import statistics
import sys
from collections import Counter
from pathlib import Path

from jevplays.branch.score import FRAMES_PER_SECOND, headline, score_decision, seed_frames
from jevplays.branch.store import BranchKey, BranchStore, export_branch


def _s(value) -> str:
    return "-" if value is None else f"{value:.1f}s"


def summary(store: BranchStore) -> int:
    meta = store.meta()
    seeds = int(meta.get("seeds", "8"))
    infos = store.decision_infos()
    rows = store.branches()
    outcomes = Counter(r.outcome for _, r in rows)
    skipped = Counter(reason.split(":")[0] for reason in store.skipped().values())
    calls = sum(r.jev_calls for _, r in rows)
    hits = sum(r.cache_hits for _, r in rows)
    print(f"run {meta.get('run')}  model {meta.get('model')}  K={seeds}")
    print(f"decisions {len(infos)}  skipped {dict(skipped)}")
    print(f"branches {len(rows)}  {dict(outcomes)}  jev calls {calls}  cache hits {hits}")
    if "spread" in meta:
        print(f"determinism check: largest answer spread {meta['spread']}")
    rng = random.Random(0)
    scores = [score_decision(i, store.branches(i.decision), seeds, rng) for i in infos]
    for kind, row in headline(scores, rng).items():
        ci = row["ci"]
        interval = f" [{ci[0]:.1f}, {ci[1]:.1f}]" if ci else ""
        tied = "-" if row["best_or_tied"] is None else f"{row['best_or_tied']:.0%}"
        print(
            f"{kind:<8} decisions {row['decisions']} scored {row['scored']} "
            f"censored_chosen {row['censored_chosen']}  "
            f"regret {_s(row['mean_regret_s'])}{interval}  best or tied {tied}  "
            f"random {_s(row['random_regret_s'])} ({row['random_missing']} missing)  "
            f"strongest {_s(row['strongest_regret_s'])} ({row['strongest_missing']} missing)  "
            f"offline {_s(row['offline_regret_s'])} ({row['offline_missing']} missing)"
        )
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
    ap.add_argument("run", type=Path)
    ap.add_argument("--decision", type=int)
    ap.add_argument("--export", nargs=4, metavar=("N", "ALTERNATIVE", "SEED", "OUT_DIR"))
    args = ap.parse_args()
    db = args.run / "branches" / "branches.sqlite"
    if not db.is_file():
        print(f"{db} does not exist; run `jevplays branch {args.run}` first", file=sys.stderr)
        return 2
    store = BranchStore(db)
    if args.export:
        n, alt, seed, out = args.export
        print(export_branch(store, BranchKey(int(n), alt, int(seed)), Path(out)))
        return 0
    if args.decision is not None:
        return one_decision(store, args.decision)
    return summary(store)


if __name__ == "__main__":
    sys.exit(main())
