"""The milestones: the three moments every run passes through, and how to get to each.

Each `Goal` is available or not, and done or not, purely from the current `GameState` --
flags, party, bag, money, and the map. `legs` builds the walk/edge/warp plan to get to where
the milestone happens; `after` names a scripted macro (talking, choosing a starter) that the
loop runs once the legs are finished. None of this touches the emulator: it is pure so the
brain and the loop can both reason about it without a live game.

Milestone 4b retired the nine-goal table this file used to hold: everything the loop can do
between milestones is generated from the map now (`executor.options`), and a milestone is only
the spine that guarantees the run keeps moving.
"""

from dataclasses import dataclass
from typing import Callable

from jevplays.executor import maps
from jevplays.executor.navigate import Leg
from jevplays.state.snapshot import GameState


@dataclass(frozen=True)
class Goal:
    id: str
    description: str
    available: Callable[[GameState], bool]
    done: Callable[[GameState], bool]
    legs: Callable[[GameState, dict[str, "maps.Link"]], list[Leg]]
    """Builds the walk/edge/warp plan from here. Takes the run's walked map graph as well as the
    state, because a route may need links that are not in the hand-written table (#35)."""
    after: str | None = None
    expects_level: int | None = None
    """The level of the toughest Pokémon this milestone walks into, or None when it walks into no
    fight. A story fact, so it lives here; `brain.buckets.readiness_bucket` turns it and the
    lead's level into the word Jev judges with (#42)."""


def lead(state: GameState):
    """The party's first Pokémon, or None with an empty party."""
    return state.party[0] if state.party else None


def balls(state: GameState) -> int:
    """How many Poké Balls are in the bag."""
    return sum(item.quantity for item in state.bag if item.name == "POKE BALL")


def node(state: GameState) -> str:
    """The map graph node the player is standing on."""
    return maps.node_of(state.map_id, *state.tile)


def legs_to(state: GameState, dest_node: str, links: dict | None = None) -> list[Leg]:
    """The edge/warp legs `maps.route` says to follow from here to `dest_node`.

    An edge leg carries the map id its destination node names (`maps.MAP_IDS`) as well as the
    direction, so a blackout in the middle of the walk reads as `lost` rather than as the
    crossing the leg was waiting for."""
    hops = maps.route(node(state), dest_node, links=links)
    if not hops:
        return []
    legs: list[Leg] = []
    for link in hops:
        if link.kind == "edge":
            legs.append(
                Leg(
                    kind="edge",
                    direction=link.direction,
                    dest_map=maps.map_id_of(link.dest_node),
                    label=f"to {link.dest_node}",
                )
            )
        else:
            legs.append(Leg(kind="warp", dest_map=link.dest_map, label=f"to {link.dest_node}"))
    return legs


def _get_starter_legs(state: GameState, links: dict) -> list[Leg]:
    here = node(state)
    if here == "pallet_town":
        return [Leg(kind="walk", target=(10, 1), label="the edge of Pallet Town")]
    if here == "oaks_lab":
        return [Leg(kind="walk", target=(6, 4), label="Charmander's ball")]
    return legs_to(state, "pallet_town", links)


def _deliver_parcel_legs(state: GameState, links: dict) -> list[Leg]:
    if "got_oaks_parcel" not in state.flags:
        return legs_to(state, "viridian_mart", links)
    legs = legs_to(state, "oaks_lab", links)
    if node(state) == "oaks_lab":
        legs = legs + [Leg(kind="walk", target=(5, 3), label="in front of Oak")]
    return legs


def _beat_brock_legs(state: GameState, links: dict) -> list[Leg]:
    return legs_to(state, "pewter_gym", links) + [Leg(kind="walk", target=(4, 2))]


GET_STARTER = Goal(
    id="get_starter",
    description="Get a starter Pokémon from Professor Oak",
    available=lambda s: True,
    done=lambda s: "got_starter" in s.flags,
    legs=_get_starter_legs,
    after="choose_charmander",
)
"""The first of `MILESTONES`, kept as its own name because the fixture scripts reach for it."""

STANDING_CLAUSE = "Build a party of three and keep them healthy."
"""Appended to the active milestone when a battle question asks what the fight is for. The
milestone says where we are going; this says what we are keeping true along the way, which is
what makes catching and healing read as part of the plan rather than a distraction from it."""


def battle_goal(goal: "Goal | None", *, fallback: str) -> str:
    """The objective sent with a battle question: the milestone the run is working towards, plus
    the standing clause. `fallback` (the `--battle-goal` flag) covers the gap before there is
    one -- a battle fought before the loop has ever stood in the overworld."""
    if goal is None:
        return fallback
    return f"{goal.description}. {STANDING_CLAUSE}"


MILESTONES: list[Goal] = [
    GET_STARTER,
    Goal(
        id="get_pokedex",
        description="Deliver Oak's parcel and get the Pokédex",
        available=lambda s: "got_starter" in s.flags and "got_pokedex" not in s.flags,
        done=lambda s: "got_pokedex" in s.flags,
        legs=_deliver_parcel_legs,
        after="talk_oak",
    ),
    Goal(
        id="beat_brock",
        description="Challenge Brock at the Pewter Gym and earn the Boulder Badge",
        available=lambda s: "got_pokedex" in s.flags,
        # The `beat_brock` flag is set when the battle ends; the badge bit is set one dialog
        # later, while "RED received the BOULDERBADGE!" is on screen. Finishing on the flag
        # stopped the run mid-dialog with no badge (#40), so the milestone waits for the bit.
        done=lambda s: s.badges >= 1,
        legs=_beat_brock_legs,
        after="talk_brock",
        # Brock's Onix. The Jr. Trainer before him fields level 11s, so the run that can take the
        # Onix can take the gym.
        expects_level=14,
    ),
]
"""Milestone 4b's spine: the three moments the run always passes through, in order. Everything
else Jev may do at a given moment is generated from the map it is standing on
(`executor.options`); this is the handful of destinations that motivate those options, and the
last one being done is what ends a run."""


def active_milestone(state: GameState) -> Goal | None:
    """The first of `MILESTONES` that's available and not yet done, or None once all three are."""
    for goal in MILESTONES:
        if goal.available(state) and not goal.done(state):
            return goal
    return None
