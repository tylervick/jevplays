"""The PROMPT and MENU decision points: a YES/NO box, and a menu of items. Both are asked with
the current goal's description as context, so the answer serves whatever the party is trying to
do rather than the prompt in isolation.
"""

import time
import uuid

from jevplays.brain.decision import Decision, MenuAction, PromptAction
from jevplays.brain.policy import NEVER_NICKNAME, choose_menu, choose_prompt
from jevplays.brain.record import answer_record, question_record
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


def decide_prompt(
    sj: dict,
    questions: dict,
    response: dict,
    *,
    model: str,
    input_tokens: int,
    latency_ms: int,
) -> Decision:
    answers = {qid: answer_record(a) for qid, a in response["answers"].items() if qid in questions}
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
        if not used:
            # No usable `prompt` answer came back, so NO is code's own safe default, not a
            # judgment: spec 12 says to mark it.
            fallback = True
            reason = "no usable prompt answer; answering NO"
    for qid in used:
        if qid in answers:
            answers[qid]["applied"] = True
    action = PromptAction(yes=yes)
    return Decision(
        id=uuid.uuid4().hex[:12],
        ts=time.time(),
        kind="prompt",
        state_summary=state_summary,
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


def decide_menu(
    sj: dict,
    questions: dict,
    response: dict,
    *,
    model: str,
    input_tokens: int,
    latency_ms: int,
) -> Decision:
    answers = {qid: answer_record(a) for qid, a in response["answers"].items() if qid in questions}
    raw = {qid: a for qid, a in response["answers"].items() if qid in questions}
    item, used = choose_menu(raw)
    fallback, reason = False, ""
    # A real close (the `close` noul fired) is never a fallback. Anything else is a fallback
    # unless the chosen item is one of the ones actually on screen.
    if used != ["close"] and (item is None or item not in sj.get("menu_items", [])):
        fallback = True
        reason = "menu: model chose an item not on screen"
        item, used = None, []
    for qid in used:
        if qid in answers:
            answers[qid]["applied"] = True
    action = MenuAction(item=item)
    return Decision(
        id=uuid.uuid4().hex[:12],
        ts=time.time(),
        kind="menu",
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
