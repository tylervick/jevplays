#!/usr/bin/env -S uv run
"""How good Jev's battle judgment was: the moves it picked, and the confidence it picked them with.

    uv run Scripts/accuracy.py RUN_DIR [--verbose]

Two numbers off one run directory, both read back through `jevplays.runlog.RunDir.open`.

`decisions.jsonl` gives accuracy: how often the chosen move matched the best-typed attack. Only
battle decisions with a `move` answer are judged; a decision whose Pokémon has no damaging move
counts as neither judged nor matched.

`outcomes.jsonl` gives calibration: every faint prediction the game went on to answer, as a Brier
score and a reliability table. A model whose 0.8s happen about 80% of the time is calibrated;
accuracy alone cannot say that. With `--verbose`, one line per judged decision.
"""

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path

from jevplays.calibration import QUESTION, brier, buckets
from jevplays.runlog import RunDir
from jevplays.state.types import best_moves


def accuracy(decisions: Iterable[dict]) -> tuple[int, int, list[dict]]:
    """(judged, matched, rows) over `decisions`: battle decisions with a `move` answer and at
    least one damaging move. `rows` holds one dict per judged decision, in order."""
    judged = 0
    matched = 0
    rows: list[dict] = []
    for d in decisions:
        if d.get("kind") != "battle" or "move" not in d.get("answers", {}):
            continue
        sj = d["state_summary"]
        ours = sj["our_pokemon"]
        best = best_moves(ours["moves"], sj["enemy_pokemon"]["types"], attacker_types=ours.get("types", ()))
        if not best:
            continue
        choice = d["answers"]["move"]["choice"]
        ok = choice in best
        judged += 1
        matched += ok
        rows.append(
            {
                "id": d.get("id", ""),
                "ours": ours.get("name", ""),
                "enemy_types": sj["enemy_pokemon"]["types"],
                "choice": choice,
                "best": best,
                "ok": ok,
            }
        )
    return judged, matched, rows


def pairs(decisions: Iterable[dict], outcomes: Iterable[dict]) -> list[tuple[float, bool]]:
    """(predicted, observed) for every resolved faint prediction whose decision is still in the
    log. The join is the guard a resume needs: rolled-back decisions move to
    `decisions.orphaned.jsonl` while `outcomes.jsonl` is left as it is, so an outcome whose
    decision is gone would otherwise score a turn that was never played."""
    ids = {d.get("id") for d in decisions}
    return [
        (float(o["predicted"]), bool(o["observed"]))
        for o in outcomes
        if o.get("question") == QUESTION and o.get("decision_id") in ids
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("run_dir", metavar="RUN_DIR", type=Path)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    try:
        run = RunDir.open(args.run_dir)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 2

    decisions = list(run.decisions())
    judged, matched, rows = accuracy(decisions)

    if args.verbose:
        for row in rows:
            enemy = "/".join(row["enemy_types"])
            best = ", ".join(sorted(row["best"]))
            status = "ok" if row["ok"] else "miss"
            print(f"{row['id']} {row['ours']} vs {enemy} chose {row['choice']} best {{{best}}} {status}")

    pct = (matched / judged * 100) if judged else 0.0
    print(f"moves judged: {judged}, matched the best type: {matched} ({pct:.0f}%)")

    scored = pairs(decisions, run.outcomes())
    score = brier(scored)
    if score is None:
        print("no faint predictions resolved")
        return 0
    print(f"faint predictions resolved: {len(scored)}, Brier {score:.3f} (0 is perfect)")
    for row in buckets(scored):
        print(
            f"  {row['low']:.1f}-{row['high']:.1f}  n={row['n']:<4d}"
            f" predicted {row['predicted']:.2f}  happened {row['observed']:.2f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
