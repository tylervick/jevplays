"""What else Jev could have done at a decision, and whether a snapshot rebuilds that decision.

The alternatives are game rules -- which actions the battle menu accepts, which options the map
generates -- so code lists them (spec: "Alternatives"). Nothing here is shown to Jev."""

import json
from dataclasses import dataclass

from jevplays.brain.battle import battle_state, bench_slots
from jevplays.brain.buckets import pp_bucket
from jevplays.brain.decision import BattleAction, ExploreAction
from jevplays.brain.explore import explore_state
from jevplays.executor.goals import MILESTONES, Goal, battle_goal
from jevplays.executor.options import Memory, Option, generate
from jevplays.state.modes import Mode
from jevplays.state.snapshot import GameState, snapshot


@dataclass(frozen=True)
class Alternative:
    key: str
    action: BattleAction | ExploreAction
    power: int | None = None
    """A move's power, for the strongest-move baseline. Code only; Jev never sees it."""


class NotReproducible(Exception):
    """The snapshot does not rebuild the decision Jev saw, so nothing is branched from it."""


@dataclass(frozen=True)
class Prepared:
    kind: str
    chosen: str
    alternatives: list[Alternative]
    strongest: str | None
    offline: str | None


def _has(state: GameState, item: str) -> bool:
    return any(i.name == item and i.quantity > 0 for i in state.bag)


def battle_alternatives(state: GameState) -> list[Alternative]:
    """Every action the battle menu would accept, in the order moves, switches, heal, run, catch."""
    assert state.active is not None and state.battle is not None
    moves = [m for m in state.active.moves if pp_bucket(m.pp) != "out"] or list(state.active.moves)
    alts = [
        Alternative(f"move:{m.name}", BattleAction(kind="move", move=m.name), power=m.power) for m in moves
    ]
    alts += [
        Alternative(f"switch:{label}", BattleAction(kind="switch", target=label))
        for label, _slot in bench_slots(state)
    ]
    if _has(state, "POTION") and state.active.hp < state.active.max_hp:
        alts.append(Alternative("heal", BattleAction(kind="heal")))
    if state.battle.kind == "wild":
        alts.append(Alternative("run", BattleAction(kind="run")))
        if _has(state, "POKE BALL"):
            alts.append(Alternative("catch", BattleAction(kind="catch")))
    return alts


def explore_alternatives(options: list[Option]) -> list[Alternative]:
    return [
        Alternative(f"explore:{o.id}", ExploreAction(option_id=o.id, kind=o.kind, text=o.text))
        for o in options
    ]


def chosen_key(alternatives: list[Alternative], logged_action: str) -> str | None:
    """The alternative whose action text is what the log recorded, or None."""
    return next((a.key for a in alternatives if a.action.describe() == logged_action), None)


def strongest_move(alternatives: list[Alternative]) -> str | None:
    attacks = [a for a in alternatives if a.key.startswith("move:") and (a.power or 0) > 0]
    return max(attacks, key=lambda a: a.power).key if attacks else None


def goal_by_id(milestone: str | None) -> Goal | None:
    return next((g for g in MILESTONES if g.id == milestone), None)


def _as_logged(sj: dict) -> dict:
    """The summary as it reads back from decisions.jsonl: tuples become lists."""
    return json.loads(json.dumps(sj, ensure_ascii=False))


def prepare(emu, logged: dict, sidecar: dict, *, fallback_goal: str) -> Prepared:
    """Rebuild decision `logged` from the loaded snapshot and list its alternatives. Raises
    NotReproducible when the rebuilt state summary differs from the logged one or Jev's logged
    action is not among the alternatives."""
    from jevplays.loop import Loop

    state = snapshot(emu)
    milestone = goal_by_id(sidecar.get("milestone"))
    offline = strongest = None
    if logged["kind"] == "battle":
        if state.mode is not Mode.BATTLE_MENU:
            raise NotReproducible(
                f"not reproducible: the snapshot is at {state.mode.name}, not the battle menu"
            )
        sj = battle_state(state, goal=battle_goal(milestone, fallback=fallback_goal))
        alternatives = battle_alternatives(state)
        strongest = strongest_move(alternatives)
    elif logged["kind"] == "explore":
        options = generate(emu, state, Memory.from_dict(sidecar.get("memory", {})), milestone)
        sj = explore_state(state, options, milestone)
        alternatives = explore_alternatives(options)
        if options:
            offline = f"explore:{Loop._offline_option(options).id}"
    else:
        raise NotReproducible(f"not branched: {logged['kind']} decisions are out of scope")
    if _as_logged(sj) != logged["state_summary"]:
        raise NotReproducible("not reproducible: the rebuilt state summary differs from the logged one")
    chosen = chosen_key(alternatives, logged["action"])
    if chosen is None:
        raise NotReproducible(f"not reproducible: {logged['action']!r} is not among the alternatives")
    return Prepared(logged["kind"], chosen, alternatives, strongest, offline)
