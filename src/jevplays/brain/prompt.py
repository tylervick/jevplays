"""The PROMPT and MENU decision points: a YES/NO box, and a menu of items. Both are asked with
the current goal's description as context, so the answer serves whatever the party is trying to
do rather than the prompt in isolation.
"""

import time
import uuid

from jevplays.brain.decision import Decision, MenuAction, PromptAction
from jevplays.brain.policy import NEVER_NICKNAME, choose_menu, choose_prompt
from jevplays.state.snapshot import GameState


def prompt_state(state: GameState, goal_description: str) -> dict:
    return {"prompt": state.text, "goal": goal_description}


def prompt_questions(sj: dict) -> dict[str, dict]:
    return {
        "prompt": {
            "type": "noul",
            "instructions": (
                'Would answering YES to the on-screen question in "prompt" help make progress on "goal"?'
            ),
        }
    }


def menu_state(state: GameState, goal_description: str) -> dict:
    return {"menu_items": list(state.menu_items), "screen_text": state.text, "goal": goal_description}


def menu_questions(sj: dict) -> dict[str, dict]:
    return {
        "menu": {
            "type": "choice",
            "instructions": 'Which item in "menu_items" best serves "goal"?',
            "criteria": {item: item for item in sj["menu_items"]},
        },
        "close": {
            "type": "noul",
            "instructions": (
                "Should this menu be closed without choosing anything, because none of "
                '"menu_items" serves "goal"?'
            ),
        },
    }


def _question_record(q: dict) -> dict:
    return {
        "primitive": q["type"],
        "instructions": q["instructions"],
        "options": list(q["criteria"]) if q["type"] == "choice" else [],
    }


def _answer_record(a: dict) -> dict:
    if a["type"] == "choice":
        return {
            "primitive": "choice",
            "choice": a["choice"],
            "probabilities": dict(a["probabilities"]),
            "confidence": a["confidence"],
            "applied": False,
        }
    return {"primitive": "noul", "noul": a["noul"], "applied": False}


def decide_prompt(
    sj: dict,
    questions: dict,
    response: dict,
    *,
    model: str,
    input_tokens: int,
    latency_ms: int,
) -> Decision:
    answers = {qid: _answer_record(a) for qid, a in response["answers"].items() if qid in questions}
    raw = {qid: a for qid, a in response["answers"].items() if qid in questions}
    text = sj.get("prompt", "")
    state_summary = sj
    fallback, reason = False, ""
    if NEVER_NICKNAME and "nickname" in text.lower():
        yes, used = False, []
        reason = "policy: never nickname"
        state_summary = dict(sj)
        state_summary["policy_note"] = reason
    else:
        yes, used = choose_prompt(raw, text)
    for qid in used:
        if qid in answers:
            answers[qid]["applied"] = True
    action = PromptAction(yes=yes)
    return Decision(
        id=uuid.uuid4().hex[:12],
        ts=time.time(),
        kind="prompt",
        state_summary=state_summary,
        questions={qid: _question_record(q) for qid, q in questions.items()},
        answers=answers,
        action=action.describe(),
        fallback=fallback,
        fallback_reason=reason,
        model=model,
        input_tokens=input_tokens,
        latency_ms=latency_ms,
        action_value=action,
    )


def decide_menu(
    sj: dict,
    questions: dict,
    response: dict,
    *,
    model: str,
    input_tokens: int,
    latency_ms: int,
) -> Decision:
    answers = {qid: _answer_record(a) for qid, a in response["answers"].items() if qid in questions}
    raw = {qid: a for qid, a in response["answers"].items() if qid in questions}
    item, used = choose_menu(raw)
    for qid in used:
        if qid in answers:
            answers[qid]["applied"] = True
    action = MenuAction(item=item)
    return Decision(
        id=uuid.uuid4().hex[:12],
        ts=time.time(),
        kind="menu",
        state_summary=sj,
        questions={qid: _question_record(q) for qid, q in questions.items()},
        answers=answers,
        action=action.describe(),
        fallback=False,
        fallback_reason="",
        model=model,
        input_tokens=input_tokens,
        latency_ms=latency_ms,
        action_value=action,
    )
