"""The overworld goal decision point: which goal to pursue next, given the party's condition and
progress so far. Jev is only asked again once the current goal completes or the navigator gives
up on it.
"""

import time
import uuid

from jevplays.brain.buckets import hp_bucket, money_bucket, quantity_bucket
from jevplays.brain.decision import Decision, GoalAction
from jevplays.brain.policy import choose_goal
from jevplays.brain.record import answer_record, question_record
from jevplays.executor.goals import Goal
from jevplays.state.snapshot import GameState


def goal_state(state: GameState, goals: list[Goal]) -> dict:
    return {
        "map": state.map,
        "party": [{"name": m.name, "level": m.level, "hp": hp_bucket(m.hp, m.max_hp)} for m in state.party],
        "badges": quantity_bucket(state.badges),
        "money": money_bucket(state.money),
        "bag": {item.name: quantity_bucket(item.quantity) for item in state.bag},
        "goals": {g.id: g.description for g in goals},
    }


def goal_questions(sj: dict) -> dict[str, dict]:
    return {
        "goal": {
            "type": "choice",
            "instructions": (
                "Given the party's condition and progress so far, which goal should we pursue next?"
            ),
            "criteria": dict(sj["goals"]),
        },
        "needs_heal": {
            "type": "noul",
            "instructions": "Should the party heal at a Pokémon Center before doing anything else?",
        },
    }


def decide_goal(
    sj: dict,
    questions: dict,
    response: dict,
    available_ids: list[str],
    *,
    model: str,
    input_tokens: int,
    latency_ms: int,
) -> Decision:
    answers = {qid: answer_record(a) for qid, a in response["answers"].items() if qid in questions}
    raw = {qid: a for qid, a in response["answers"].items() if qid in questions}
    chosen_id, used = choose_goal(raw, available_ids)
    fallback, reason = False, ""
    if chosen_id not in available_ids:
        if not available_ids:
            raise ValueError("no available goals to choose from")
        fallback = True
        reason = f"{chosen_id!r} is not an available goal; using the first available goal instead"
        chosen_id, used = available_ids[0], []
    for qid in used:
        if qid in answers:
            answers[qid]["applied"] = True
    action = GoalAction(goal_id=chosen_id)
    return Decision(
        id=uuid.uuid4().hex[:12],
        ts=time.time(),
        kind="goal",
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
