"""The overworld explore decision point: which of the generated options to pursue next, given
the party's condition, story progress so far, and the active milestone. Jev is asked fresh every
time it stands idle in the overworld, because it has no memory between calls -- the option list
itself carries a memory word (`executor.options.Option.labelled`) that says whether this run has
done each one before.
"""

import time
import uuid

from jevplays.brain.buckets import hp_bucket, money_bucket, quantity_bucket
from jevplays.brain.decision import Decision, ExploreAction
from jevplays.brain.policy import choose_explore
from jevplays.brain.record import answer_record, question_record
from jevplays.executor.goals import Goal
from jevplays.executor.options import Option
from jevplays.state.events import TRACKED_FLAGS
from jevplays.state.snapshot import GameState

PROGRESS_WORDS: dict[str, str] = {
    "got_starter": "got a starter",
    "got_oaks_parcel": "picked up Oak's parcel",
    "oak_got_parcel": "delivered Oak's parcel",
    "got_pokedex": "got the Pokédex",
    "beat_brock": "earned the Boulder Badge",
    "battled_rival_in_oaks_lab": "beat the rival in the lab",
}
"""Story flags worth telling Jev about, in words. Keyed by `state.events.TRACKED_FLAGS` name;
flags with no entry here (the ones that only matter to code, like the intro's own bookkeeping)
are left out of `progress` entirely."""


def explore_state(state: GameState, options: list[Option], milestone: Goal | None) -> dict:
    return {
        "map": state.map,
        "progress": [
            PROGRESS_WORDS[name] for name in TRACKED_FLAGS if name in state.flags and name in PROGRESS_WORDS
        ],
        "party": [{"name": m.name, "level": m.level, "hp": hp_bucket(m.hp, m.max_hp)} for m in state.party],
        "money": money_bucket(state.money),
        "bag": {item.name: quantity_bucket(item.quantity) for item in state.bag},
        "milestone": milestone.description if milestone is not None else "none yet",
        "options": {option.id: option.labelled() for option in options},
    }


def explore_questions(sj: dict) -> dict[str, dict]:
    return {
        "explore": {
            "type": "choice",
            "instructions": (
                'Which of "options" should we do next to make progress in the game, given '
                '"progress" and the "milestone"? Each option ends with a word in parentheses: '
                '"new" means we have never done it from here; "visited" or "talked already" means '
                'we have done it before and may not need to again; "tried" means we chose it '
                "before from here and nothing came of it, so repeat it only if nothing else is "
                "worth doing."
            ),
            "criteria": dict(sj["options"]),
        },
        "needs_heal": {
            "type": "noul",
            "instructions": "Should the party heal before doing anything else?",
            "criteria": {
                "true": "the party is hurt enough that the next battle could be lost",
                "false": "the party can keep going",
            },
        },
    }


def decide_explore(
    sj: dict,
    questions: dict,
    response: dict,
    options: list[Option],
    *,
    model: str,
    input_tokens: int,
    latency_ms: int,
) -> Decision:
    answers = {qid: answer_record(a) for qid, a in response["answers"].items() if qid in questions}
    raw = {qid: a for qid, a in response["answers"].items() if qid in questions}
    by_id = {option.id: option for option in options}
    option_ids = list(by_id)
    chosen_id, used = choose_explore(raw, option_ids)
    fallback, reason = False, ""
    if chosen_id not in by_id:
        if not option_ids:
            raise ValueError("no available options to choose from")
        fallback = True
        reason = f"{chosen_id!r} is not offered; using the first option instead"
        chosen_id, used = option_ids[0], []
    elif not used:
        # choose_explore fell through because there was no usable answer to act on: code chose
        # this, not Jev, so spec 12 says to mark it. When the explore choice itself named an
        # option that was not on the list, say so specifically.
        fallback = True
        raw_explore = raw.get("explore")
        if raw_explore and raw_explore.get("type") == "choice" and raw_explore.get("choice") not in by_id:
            reason = f"{raw_explore['choice']!r} is not offered; using {chosen_id} instead"
        else:
            reason = f"no usable explore answer; using {chosen_id} instead"
    for qid in used:
        if qid in answers:
            answers[qid]["applied"] = True
    chosen = by_id[chosen_id]
    action = ExploreAction(option_id=chosen.id, kind=chosen.kind, text=chosen.text)
    return Decision(
        id=uuid.uuid4().hex[:12],
        ts=time.time(),
        kind="explore",
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
