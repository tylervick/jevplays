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

`decisions.jsonl` also gives an exploration summary (spec 8 of the generated-options design):
decisions by kind, explore picks by option kind, how often the milestone was picked, and how
many distinct maps were seen -- that last from the run's `memory.json` when it has one, since
the memory counts every map the run stood on, not only the ones it stopped to explore from.
"""

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path

from jevplays.calibration import QUESTION, brier, buckets
from jevplays.runlog import RunDir
from jevplays.state.types import best_moves

DECISION_KINDS = ("battle", "explore", "prompt", "menu")
EXPLORE_OPTION_KINDS = ("exit", "door", "npc", "grass", "milestone", "heal")


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


def _option_kind(option_id: str) -> str | None:
    """The `Option.kind` an id like `exit_north` or `door_41` was built with (`executor.options`
    prefixes `exit_`/`door_`/`npc_`; `grass`, `milestone`, and `heal` are ids on their own).
    None for anything that does not match, which should not happen for an id `options.py` built."""
    for prefix in ("exit_", "door_", "npc_"):
        if option_id.startswith(prefix):
            return prefix.rstrip("_")
    return option_id if option_id in ("grass", "milestone", "heal") else None


def _executed_option_id(d: dict) -> str | None:
    """The option an explore decision actually ran. `Decision.to_dict` drops `action_value`, and
    `answers["explore"]["choice"]` is what Jev said, not what ran: a heal-first override or an
    off-list fallback executes something else without changing it. The `action` text is built
    from the option that ran in every branch ("explore: <option text>"), and the options on offer
    are logged as id -> "<text> (<memory>)", so matching the two recovers the id exactly."""
    action = d.get("action", "")
    prefix = "explore: "
    if not action.startswith(prefix):
        return None
    text = action[len(prefix) :]
    for option_id, labelled in d.get("state_summary", {}).get("options", {}).items():
        if labelled.rsplit(" (", 1)[0] == text:
            return option_id
    return None


def exploration(decisions: Iterable[dict], maps_seen: int | None = None) -> dict:
    """Summary of the overworld choices in `decisions`: `by_kind` (decision kind -> count over
    all decisions), `explore_by_option_kind` (explore decisions -> the kind of option that was
    actually run, exit/door/npc/grass/milestone/heal -> count), `milestone_share` (milestone
    picks / explore decisions, 0.0 when there were none), `maps_seen`, and `total` (all
    decisions).

    `maps_seen` is passed in when the run dir kept a `memory.json` -- `visited_maps` is every map
    the run stood on, including the ones it walked straight through -- and otherwise falls back
    to the distinct `state_summary["map"]` over the explore decisions, which is only the maps it
    stopped to explore from."""
    by_kind: dict[str, int] = dict.fromkeys(DECISION_KINDS, 0)
    explore_by_option_kind: dict[str, int] = dict.fromkeys(EXPLORE_OPTION_KINDS, 0)
    explored_maps: set[str] = set()
    total = 0
    explore_total = 0
    milestone_picks = 0
    for d in decisions:
        total += 1
        kind = d.get("kind", "")
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if kind != "explore":
            continue
        explore_total += 1
        map_name = d.get("state_summary", {}).get("map")
        if map_name:
            explored_maps.add(map_name)
        option_id = _executed_option_id(d)
        option_kind = _option_kind(option_id) if option_id is not None else None
        if option_kind is not None:
            explore_by_option_kind[option_kind] += 1
            if option_kind == "milestone":
                milestone_picks += 1
    milestone_share = (milestone_picks / explore_total) if explore_total else 0.0
    return {
        "by_kind": by_kind,
        "explore_by_option_kind": explore_by_option_kind,
        "milestone_share": milestone_share,
        "maps_seen": len(explored_maps) if maps_seen is None else maps_seen,
        "total": total,
    }


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
    else:
        print(f"faint predictions resolved: {len(scored)}, Brier {score:.3f} (0 is perfect)")
        for row in buckets(scored):
            print(
                f"  {row['low']:.1f}-{row['high']:.1f}  n={row['n']:<4d}"
                f" predicted {row['predicted']:.2f}  happened {row['observed']:.2f}"
            )

    memory = run.load_memory()
    visited = len(memory["visited_maps"]) if memory and "visited_maps" in memory else None
    exp = exploration(decisions, visited)
    bk = exp["by_kind"]
    print(
        f"decisions: {exp['total']} (battle {bk['battle']}, explore {bk['explore']}, "
        f"prompt {bk['prompt']}, menu {bk['menu']})"
    )
    ok = exp["explore_by_option_kind"]
    print(
        f"explore picks: exit {ok['exit']}, door {ok['door']}, npc {ok['npc']}, "
        f"grass {ok['grass']}, milestone {ok['milestone']}, heal {ok['heal']}"
    )
    print(f"milestone share: {exp['milestone_share'] * 100:.0f}%")
    print(f"maps seen: {exp['maps_seen']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
