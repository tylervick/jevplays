"""The one question Jev is asked that the game itself answers, and the arithmetic over the answers.

Every battle bundle carries a `faint` prediction (brain/battle.py) that no policy reads. This
module says when the game has answered it and turns a run's resolved predictions into a Brier
score and a reliability table. Nothing here is on the path to a decision: `resolve` reads the
party the loop already has, and the score is read back off disk afterwards by
`Scripts/accuracy.py`.
"""

from dataclasses import dataclass

from jevplays.state.modes import Mode
from jevplays.state.snapshot import GameState

QUESTION = "faint"


@dataclass(frozen=True)
class Pending:
    """A faint prediction waiting for the game to answer it."""

    decision_id: str
    slot: int
    """The party index the prediction was about -- the active Pokémon when it was made."""
    predicted: float


def resolve_prediction(pending: Pending, state: GameState, *, ts: float) -> dict | None:
    """The outcome record, or None while the question is still open.

    It is open until our Pokémon would get to choose again: mid-battle that means the battle
    menu is back, and a battle that ended (ran, caught it, blacked out) answers it too, because
    there is no next turn. A slot the party no longer has stays unresolved rather than guessing.
    """
    if state.in_battle and state.mode is not Mode.BATTLE_MENU:
        return None
    if not 0 <= pending.slot < len(state.party):
        return None
    return {
        "decision_id": pending.decision_id,
        "question": QUESTION,
        "predicted": pending.predicted,
        "observed": state.party[pending.slot].hp == 0,
        "ts": ts,
    }


def brier(pairs) -> float | None:
    """Mean squared error of the probabilities against what happened, 0 (perfect) to 1. None
    when nothing was resolved: no samples is not the same as a perfect score."""
    pairs = list(pairs)
    if not pairs:
        return None
    return sum((p - float(o)) ** 2 for p, o in pairs) / len(pairs)


def buckets(pairs, *, width: float = 0.2) -> list[dict]:
    """Reliability by probability band: how often things Jev called `p` actually happened. Only
    bands with samples are returned, low to high."""
    grouped: dict[int, list[tuple[float, bool]]] = {}
    count = max(1, round(1 / width))
    for p, o in pairs:
        index = min(int(p / width), count - 1)
        grouped.setdefault(index, []).append((p, bool(o)))
    rows = []
    for index in sorted(grouped):
        group = grouped[index]
        rows.append(
            {
                "low": round(index * width, 3),
                "high": round(min(1.0, (index + 1) * width), 3),
                "n": len(group),
                "predicted": round(sum(p for p, _ in group) / len(group), 3),
                "observed": round(sum(o for _, o in group) / len(group), 3),
            }
        )
    return rows
