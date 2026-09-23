"""The starter, asked once at Oak's table (#80): which of the three Jev takes.

Jev is told each starter's type, in the game's own words for it, and where the run is going --
never which type beats which: that lives in `state/types.py` for measurement only.
"""

import time
import uuid

from jevplays.brain.decision import Decision, StarterAction
from jevplays.brain.record import answer_record, question_record

STARTERS = {
    "BULBASAUR": "Grass-type, the plant POKéMON",
    "CHARMANDER": "Fire-type, the fire POKéMON",
    "SQUIRTLE": "Water-type, the water POKéMON",
}
"""species -> what Jev is told about it. The game calls them the plant, fire, and water POKéMON
when it asks to confirm."""

DEFAULT_STARTER = "CHARMANDER"
"""What code takes with no usable answer, and what a run without a brain takes: the one every run
took before Jev chose."""


def starter_state(goal_description: str) -> dict:
    return {"goal": goal_description}


def starter_questions(sj: dict) -> dict[str, dict]:
    return {
        "starter": {
            "type": "choice",
            "instructions": (
                "Which starter POKéMON should we take from Professor Oak? It will be our only "
                'POKéMON at first, and it has to carry us to "goal".'
            ),
            "criteria": dict(STARTERS),
        }
    }


def decide_starter(
    sj: dict,
    questions: dict,
    response: dict,
    *,
    model: str,
    input_tokens: int,
    latency_ms: int,
) -> Decision:
    answers = {qid: answer_record(a) for qid, a in response["answers"].items() if qid in questions}
    raw = response["answers"].get("starter", {})
    choice = raw.get("choice") if raw.get("type") == "choice" else None
    fallback, reason = False, ""
    if choice in STARTERS:
        answers["starter"]["applied"] = True
        species = choice
    else:
        fallback, reason = True, f"starter: {choice!r} is not one of the three; taking {DEFAULT_STARTER}"
        species = DEFAULT_STARTER
    action = StarterAction(species=species)
    return Decision(
        id=uuid.uuid4().hex[:12],
        ts=time.time(),
        kind="starter",
        state_summary=sj,
        questions={qid: question_record(q) for qid, q in questions.items()},
        answers=answers,
        action=action.describe(),
        fallback=fallback,
        fallback_reason=reason,
        model=model,
        input_tokens=input_tokens,
        latency_ms=latency_ms,
        action_value=action,
    )
