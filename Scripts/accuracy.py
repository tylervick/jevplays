#!/usr/bin/env -S uv run
"""How often Jev's move matched the best-typed attack.

    uv run Scripts/accuracy.py RUN_DIR [--verbose]

Reads `decisions.jsonl` through `jevplays.runlog.RunDir.open`. Only battle decisions with a
`move` answer are judged; a decision whose Pokémon has no damaging move counts as neither judged
nor matched. Prints a summary line, and with `--verbose` one line per judged decision.
"""

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path

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
        best = best_moves(ours["moves"], sj["enemy_pokemon"]["types"])
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

    judged, matched, rows = accuracy(run.decisions())

    if args.verbose:
        for row in rows:
            enemy = "/".join(row["enemy_types"])
            best = ", ".join(sorted(row["best"]))
            status = "ok" if row["ok"] else "miss"
            print(f"{row['id']} {row['ours']} vs {enemy} chose {row['choice']} best {{{best}}} {status}")

    pct = (matched / judged * 100) if judged else 0.0
    print(f"moves judged: {judged}, matched the best type: {matched} ({pct:.0f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
