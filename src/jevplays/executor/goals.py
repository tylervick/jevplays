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
    destination: str | None = None
    """The map graph node where `after` happens, for a milestone whose way there is only ever the
    run's walked graph. Standing anywhere else with no route there, the milestone is not offered
    (`options._milestone_option`): the run has not walked there yet, and the exits and doors carry
    it. None for the milestones the hand-written table reaches."""
    badge: str | None = None
    """The badge this milestone ends in, or None. A run that stops at this milestone (`--until`)
    finishes naming it."""


def lead(state: GameState):
    """The party's first Pokémon, or None with an empty party."""
    return state.party[0] if state.party else None


def balls(state: GameState) -> int:
    """How many Poké Balls are in the bag."""
    return sum(item.quantity for item in state.bag if item.name == "POKE BALL")


def node(state: GameState) -> str:
    """The place the player is standing in: the snapshot's pocket-aware name, or the map-level
    name for a state built without one (#137)."""
    return state.place or maps.node_of(state.map_id, *state.tile)


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


STARTER_TILES = {"CHARMANDER": (6, 4), "SQUIRTLE": (7, 4), "BULBASAUR": (8, 4)}
"""Where to stand, facing up, to take each ball on Oak's table (checked against the ROM)."""


def _get_starter_legs(state: GameState, links: dict) -> list[Leg]:
    here = node(state)
    if here == "pallet_town":
        return [Leg(kind="walk", target=(10, 1), label="the edge of Pallet Town")]
    if here == "oaks_lab":
        return [Leg(kind="walk", target=STARTER_TILES["SQUIRTLE"], label="Oak's table")]
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


def _beat_misty_legs(state: GameState, links: dict) -> list[Leg]:
    # To the gym door and no further: where Misty stands is read off the map by `talk_leader`,
    # not typed in here.
    return legs_to(state, "cerulean_gym", links)


GET_STARTER = Goal(
    id="get_starter",
    description="Get a starter Pokémon from Professor Oak",
    available=lambda s: True,
    done=lambda s: "got_starter" in s.flags,
    legs=_get_starter_legs,
    after="choose_starter",
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
        badge="Boulder Badge",
    ),
]
"""Milestone 4b's spine: the three moments the run always passes through, in order. Everything
else Jev may do at a given moment is generated from the map it is standing on
(`executor.options`); this is the handful of destinations that motivate those options, and the
last one being done is what ends a run that takes the default `until`."""

BEAT_MISTY = Goal(
    id="beat_misty",
    description="Challenge Misty at the Cerulean Gym and earn the Cascade Badge",
    available=lambda s: s.badges >= 1,
    done=lambda s: s.badges >= 2,
    legs=_beat_misty_legs,
    after="talk_leader",
    destination="cerulean_gym",
    # Misty's Starmie.
    expects_level=21,
    badge="Cascade Badge",
)

ALL_MILESTONES: list[Goal] = [*MILESTONES, BEAT_MISTY]
"""The whole story a run can be pointed at: the default spine, then what lies past it, which a
run opts into with `--until` (`LoopConfig.until`). `MILESTONES` stays the default spine so every
run, measurement series and the demo still end at the Boulder Badge."""

DEFAULT_UNTIL = "beat_brock"
"""The last milestone a run works towards unless told otherwise."""

BADGE_MILESTONES: tuple[str, ...] = tuple(goal.id for goal in ALL_MILESTONES if goal.badge)
"""The milestones a run can be told to stop at: the ones that end in a badge."""


def milestone_by_id(goal_id: str) -> Goal:
    """The milestone called `goal_id`; ValueError for a name that is not one."""
    for goal in ALL_MILESTONES:
        if goal.id == goal_id:
            return goal
    raise ValueError(f"unknown milestone {goal_id!r}")


def check_until(until: str) -> str:
    """`until` itself, when it names a milestone a run can stop at (`BADGE_MILESTONES`); a
    ValueError that says which ones can, when it does not."""
    if until not in BADGE_MILESTONES:
        raise ValueError(
            f"until {until!r} is not a milestone a run can stop at ({', '.join(BADGE_MILESTONES)})"
        )
    return until


def until_from_flags(flags: dict) -> str:
    """The `until` a run was started with, from its run.json flags. A run.json from before the
    flag existed ran the default spine. ValueError for a value that names no badge milestone."""
    return check_until(flags.get("until") or DEFAULT_UNTIL)


def finish_words(until: str) -> str:
    """What a run that stops at `until` says when it gets there: the badge, or the milestone."""
    goal = milestone_by_id(until)
    return goal.badge or goal.description


def active_milestone(state: GameState, until: str = DEFAULT_UNTIL) -> Goal | None:
    """The first milestone, up to and including `until`, that's available and not yet done, or
    None once they all are. Raises ValueError when `until` names no milestone."""
    last = ALL_MILESTONES.index(milestone_by_id(until))
    for goal in ALL_MILESTONES[: last + 1]:
        if goal.available(state) and not goal.done(state):
            return goal
    return None
