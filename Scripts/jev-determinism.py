#!/usr/bin/env -S uv run
"""Does Jev answer the same input the same way? The response cache in `jevplays branch` assumes
so (spec: "The response cache").

    mise exec -- uv run Scripts/jev-determinism.py RUN_DIR [--inputs 20] [--repeats 5]
    mise exec -- uv run Scripts/jev-determinism.py RUN_DIR --store RUN_DIR/branches/branches.sqlite

Takes `--inputs` battle and explore decisions Jev made in RUN_DIR, spread evenly through the run,
rebuilds each one's questions from its logged state summary, asks each `--repeats` times, and
prints the spread of every input and the largest overall. `--store` also writes the largest
spread into a branch measurement, where `Scripts/branch-report.py` prints it. Needs
TYPESAFE_API_KEY.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from jevplays.brain.battle import battle_questions
from jevplays.brain.client import Brain
from jevplays.brain.explore import explore_questions
from jevplays.branch.score import answer_spread
from jevplays.branch.store import BranchStore
from jevplays.runlog import RunDir

BUILDERS = {"battle": battle_questions, "explore": explore_questions}


async def main_async(run: Path, inputs: int, repeats: int, store: Path | None = None) -> int:
    logged = [
        d
        for d in RunDir.open(run).decisions()
        if d["kind"] in BUILDERS and d["questions"] and not d["fallback"]
    ]
    if not logged:
        print(f"{run}: no battle or explore decisions Jev made", file=sys.stderr)
        return 2
    step = max(1, len(logged) // inputs)
    picked = logged[::step][:inputs]
    brain = Brain()
    worst = 0.0
    try:
        for d in picked:
            sj = d["state_summary"]
            questions = BUILDERS[d["kind"]](sj)
            responses = [(await brain.ask(sj, questions))[0] for _ in range(repeats)]
            spread = answer_spread(responses)
            worst = max(worst, spread)
            print(f"{d['id']}  {d['kind']:<8} spread {spread:.4f}", flush=True)
    finally:
        await brain.close()
    print(f"inputs {len(picked)}, repeats {repeats}, largest spread {worst:.4f}")
    if store is not None:
        db = BranchStore(store)
        db.set_meta("spread", f"{worst:.4f}")
        db.close()
        print(f"wrote spread {worst:.4f} to {store}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=Path)
    ap.add_argument("--inputs", type=int, default=20)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument(
        "--store",
        type=Path,
        help="a measurement's branches.sqlite: record the largest spread there for branch-report",
    )
    args = ap.parse_args()
    if args.store is not None and not args.store.is_file():
        print(f"{args.store} does not exist; run `jevplays branch` first", file=sys.stderr)
        return 2
    return asyncio.run(main_async(args.run, args.inputs, args.repeats, args.store))


if __name__ == "__main__":
    sys.exit(main())
