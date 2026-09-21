"""Gen 1 type effectiveness, for measuring Jev's move choices after the fact. Nothing on the path
to a decision imports this: the spec keeps effectiveness out of what the model sees."""

import json
from collections.abc import Sequence
from functools import reduce
from pathlib import Path

_ROWS = json.loads((Path(__file__).parent / "data" / "type_chart.json").read_text(encoding="utf-8"))
TYPE_CHART: dict[tuple[str, str], float] = {(a, d): float(m) for a, d, m in _ROWS}

STAB = 1.5


def effectiveness(move_type: str, defender_types: Sequence[str]) -> float:
    return reduce(lambda acc, t: acc * TYPE_CHART.get((move_type, t), 1.0), defender_types, 1.0)


def best_moves(
    moves: list[dict], defender_types: Sequence[str], *, attacker_types: Sequence[str] = ()
) -> set[str]:
    """The damaging moves (`kind == "attack"`) with the highest effectiveness against
    `defender_types`, STAB included. Empty when no move does damage."""
    scored = {
        m["name"]: effectiveness(m["type"], defender_types) * (STAB if m["type"] in attacker_types else 1.0)
        for m in moves
        if m.get("kind") == "attack"
    }
    if not scored:
        return set()
    top = max(scored.values())
    return {name for name, score in scored.items() if score == top}
