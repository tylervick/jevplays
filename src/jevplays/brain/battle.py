"""The battle decision point: what Jev sees, what it is asked, and how its answers become a move.

Every question is one narrow judgment with its options spelled out, and questions that cannot
apply (RUN in a trainer battle, a Poké Ball with none in the bag) are not sent. All of them go in
one request; the policy consumes only the ones that apply.
"""

import time
import uuid

from jevplays.brain.buckets import hp_bucket, power_bucket, pp_bucket
from jevplays.brain.decision import BattleAction, Decision
from jevplays.brain.policy import choose_battle_action
from jevplays.state.snapshot import GameState, Mon


def _mon(mon: Mon, *, with_moves: bool) -> dict:
    d = {"name": mon.name, "level": mon.level, "types": list(mon.types), "hp": hp_bucket(mon.hp, mon.max_hp)}
    if with_moves:
        d["status"] = mon.status
        d["moves"] = [
            {
                "name": m.name,
                "type": m.type,
                "kind": "attack" if m.power > 0 else "status",
                "power": power_bucket(m.power),
                "pp": pp_bucket(m.pp),
            }
            for m in mon.moves
        ]
    return d


def battle_state(state: GameState, goal: str) -> dict:
    assert state.active is not None and state.enemy is not None and state.battle is not None
    bench = [m for i, m in enumerate(state.party) if i != state.active_slot]
    return {
        "our_pokemon": _mon(state.active, with_moves=True),
        "enemy_pokemon": _mon(state.enemy, with_moves=False),
        "battle": {"kind": state.battle.kind},
        "bench": [_mon(m, with_moves=False) for m in bench if m.hp > 0],
        "bag": {
            "poke_balls": any(item.name.endswith("BALL") and item.quantity > 0 for item in state.bag),
            "potions": any("POTION" in item.name and item.quantity > 0 for item in state.bag),
        },
        "goal": goal,
    }


def battle_questions(sj: dict) -> dict[str, dict]:
    usable = [m for m in sj["our_pokemon"]["moves"] if m["pp"] != "out"]
    if not usable:
        usable = sj["our_pokemon"]["moves"]
    qs: dict[str, dict] = {
        "move": {
            "type": "choice",
            "instructions": "Which move should `our_pokemon` use this turn to win the battle as quickly and safely as possible, given the types of both Pokémon?",
            "criteria": {m["name"]: f"{m['type']}-type {m['kind']}, {m['power']} power" for m in usable},
        }
    }
    if sj["bench"]:
        qs["switch"] = {
            "type": "noul",
            "instructions": "Should we switch out `our_pokemon` this turn instead of using a move?",
            "criteria": {
                "true": "A Pokémon in `bench` would clearly do better against `enemy_pokemon`, or `our_pokemon` is about to faint",
                "false": "`our_pokemon` can keep fighting",
            },
        }
        qs["switch_to"] = {
            "type": "choice",
            "instructions": "If we switch, which Pokémon from `bench` should come in against `enemy_pokemon`?",
            "criteria": {
                m["name"]: f"{'/'.join(m['types'])} type, level {m['level']}, hp {m['hp']}"
                for m in sj["bench"]
            },
        }
    if sj["bag"]["potions"]:
        qs["heal"] = {
            "type": "noul",
            "instructions": "Should we use a Potion on `our_pokemon` this turn instead of attacking?",
        }
    if sj["battle"]["kind"] == "wild":
        qs["run"] = {
            "type": "noul",
            "instructions": "Should we run from this wild battle rather than fight it?",
        }
        if sj["bag"]["poke_balls"]:
            qs["catch"] = {
                "type": "noul",
                "instructions": "Should we throw a Poké Ball at `enemy_pokemon` this turn?",
                "criteria": {
                    "true": "We want a party of at least three, `enemy_pokemon` is worth having, and its hp is low enough for a ball to work",
                    "false": "Its hp is still high, or it is not worth a ball",
                },
            }
    return qs


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


def decide_battle(
    sj: dict,
    questions: dict,
    response: dict,
    *,
    model: str,
    input_tokens: int,
    latency_ms: int,
    supported: frozenset[str] = frozenset({"move", "run"}),
) -> Decision:
    answers = {qid: _answer_record(a) for qid, a in response["answers"].items() if qid in questions}
    raw = {qid: a for qid, a in response["answers"].items() if qid in questions}
    fallback, reason = False, ""
    if "move" not in raw:
        first = next(iter(questions["move"]["criteria"]))
        action, used = BattleAction(kind="move", move=first), []
        fallback, reason = True, "the response had no move answer; using the first usable move"
    else:
        action, used = choose_battle_action(raw, sj)
        if action.kind not in supported:
            fallback, reason = True, f"{action.kind} is not executable yet; using the move answer instead"
            action = BattleAction(kind="move", move=raw["move"]["choice"])
            used = used + ["move"]
    for qid in used:
        if qid in answers:
            answers[qid]["applied"] = True
    return Decision(
        id=uuid.uuid4().hex[:12],
        ts=time.time(),
        kind="battle",
        state_summary=sj,
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
