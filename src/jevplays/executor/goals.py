"""The early game's goal table: what Jev can choose to do next, and how to get there.

Each `Goal` is available or not, and done or not, purely from the current `GameState` --
flags, party, bag, money, and the map. `legs` builds the walk/edge/warp plan to get to where
the goal happens; `after` names a scripted macro (talking, choosing a starter, healing,
buying, wandering into a battle) that the loop runs once the legs are finished. None of this
touches the emulator: it is pure so the brain and the loop can both reason about it without a
live game.
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
    legs: Callable[[GameState], list[Leg]]
    after: str | None = None


def lead(state: GameState):
    """The party's first Pokémon, or None with an empty party."""
    return state.party[0] if state.party else None


def balls(state: GameState) -> int:
    """How many Poké Balls are in the bag."""
    return sum(item.quantity for item in state.bag if item.name == "POKE BALL")


def potions(state: GameState) -> int:
    """How many Potions are in the bag. The `heal` battle action needs one, and until #27 nothing
    ever put one there: the Viridian Mart does not stock them."""
    return sum(item.quantity for item in state.bag if item.name == "POTION")


def node(state: GameState) -> str:
    """The map graph node the player is standing on."""
    return maps.node_of(state.map_id, *state.tile)


def legs_to(state: GameState, dest_node: str) -> list[Leg]:
    """The edge/warp legs `maps.route` says to follow from here to `dest_node`."""
    links = maps.route(node(state), dest_node)
    if not links:
        return []
    legs: list[Leg] = []
    for link in links:
        if link.kind == "edge":
            legs.append(Leg(kind="edge", direction=link.direction, label=f"to {link.dest_node}"))
        else:
            legs.append(Leg(kind="warp", dest_map=link.dest_map, label=f"to {link.dest_node}"))
    return legs


POTIONS_WANTED = 2
"""Potions worth having before Brock. Two is one per gym Pokémon and a party of one's whole
margin for error."""

POTION_BUDGET = 600
"""Money to keep back for the trip. Deliberately a budget and not a price: what a Potion costs is
read off the shop screen, never assumed here (#27)."""

OLD_MAN_PICTURE = 72
"""The sprite picture id of the old man asleep across the road north out of Viridian City."""

PEWTER_NODES = {"pewter_city", "pewter_gym", "pewter_mart", "pewter_pokecenter"}
CENTER_NODES = ("viridian_pokecenter", "pewter_pokecenter")
GRASS_MAPS = {maps.ROUTE_1, maps.ROUTE_2, maps.VIRIDIAN_FOREST}


def _get_starter_legs(state: GameState) -> list[Leg]:
    here = node(state)
    if here == "pallet_town":
        return [Leg(kind="walk", target=(10, 1), label="the edge of Pallet Town")]
    if here == "oaks_lab":
        return [Leg(kind="walk", target=(6, 4), label="Charmander's ball")]
    return legs_to(state, "pallet_town")


def _deliver_parcel_legs(state: GameState) -> list[Leg]:
    if "got_oaks_parcel" not in state.flags:
        return legs_to(state, "viridian_mart")
    legs = legs_to(state, "oaks_lab")
    if node(state) == "oaks_lab":
        legs = legs + [Leg(kind="walk", target=(5, 3), label="in front of Oak")]
    return legs


def _wake_old_man_legs(state: GameState) -> list[Leg]:
    return legs_to(state, "viridian_city") + [Leg(kind="walk", target=(18, 10))]


def _buy_pokeballs_legs(state: GameState) -> list[Leg]:
    return legs_to(state, "viridian_mart")


def _buy_potions_legs(state: GameState) -> list[Leg]:
    return legs_to(state, "pewter_mart")


def _train_to_level_12_legs(state: GameState) -> list[Leg]:
    return legs_to(state, "route_2_south")


def _cross_viridian_forest_legs(state: GameState) -> list[Leg]:
    return legs_to(state, "pewter_city")


def _beat_brock_legs(state: GameState) -> list[Leg]:
    return legs_to(state, "pewter_gym") + [Leg(kind="walk", target=(4, 2))]


def _nearest_center(state: GameState) -> str | None:
    best, best_len = None, None
    for center in CENTER_NODES:
        links = maps.route(node(state), center)
        if links is None:
            continue
        if best_len is None or len(links) < best_len:
            best, best_len = center, len(links)
    return best


def _heal_at_center_legs(state: GameState) -> list[Leg]:
    center = _nearest_center(state)
    return legs_to(state, center) if center else []


def _train_nearby_legs(state: GameState) -> list[Leg]:
    return []


def _lead_hurt(state: GameState) -> bool:
    mon = lead(state)
    return mon is not None and mon.hp < mon.max_hp * 0.5


def _heal_done(state: GameState) -> bool:
    mon = lead(state)
    return mon is None or mon.hp >= mon.max_hp


GOALS: list[Goal] = [
    Goal(
        id="get_starter",
        description="Get a starter Pokémon from Professor Oak",
        available=lambda s: True,
        done=lambda s: "got_starter" in s.flags,
        legs=_get_starter_legs,
        after="choose_charmander",
    ),
    Goal(
        id="deliver_parcel",
        description="Deliver Oak's Parcel: fetch it from the Viridian Mart, then bring it to Oak",
        available=lambda s: "got_starter" in s.flags and "got_pokedex" not in s.flags,
        done=lambda s: "got_pokedex" in s.flags,
        legs=_deliver_parcel_legs,
        after="talk_oak",
    ),
    Goal(
        id="wake_old_man",
        description="Wake the old man who is blocking the road north out of Viridian City",
        available=lambda s: (
            "oak_got_parcel" in s.flags
            and s.map_id == maps.VIRIDIAN_CITY
            and any(sprite.picture == OLD_MAN_PICTURE for sprite in s.sprites)
        ),
        # Only Viridian City can say whether he has moved: anywhere else his sprite is simply
        # not loaded, which would read as "done" from the far side of the region.
        done=lambda s: (
            s.map_id == maps.VIRIDIAN_CITY
            and not any(sprite.picture == OLD_MAN_PICTURE for sprite in s.sprites)
        ),
        legs=_wake_old_man_legs,
        after="talk_old_man",
    ),
    Goal(
        id="buy_pokeballs",
        description="Buy Poké Balls at the Viridian Mart",
        available=lambda s: "got_pokedex" in s.flags and s.money >= 600 and balls(s) < 3,
        done=lambda s: balls(s) >= 3 or s.money < 200,
        legs=_buy_pokeballs_legs,
        after="buy_pokeballs",
    ),
    Goal(
        id="buy_potions",
        # Pewter only: the Viridian Mart sells no Potions, and this is the last counter before
        # Brock, which is the first fight where one decides anything. Availability is pinned to
        # standing in Pewter so a run never walks back through the forest for a Potion.
        description="Buy Potions at the Pewter Mart",
        available=lambda s: (
            "got_pokedex" in s.flags
            and node(s) in PEWTER_NODES
            and s.money >= POTION_BUDGET
            and potions(s) < POTIONS_WANTED
            and "beat_brock" not in s.flags
        ),
        done=lambda s: potions(s) >= POTIONS_WANTED or s.money < POTION_BUDGET,
        legs=_buy_potions_legs,
        after="buy_potions",
    ),
    Goal(
        id="train_to_level_12",
        description="Train on Route 2 until CHARMANDER reaches level 12",
        available=lambda s: "got_pokedex" in s.flags and lead(s) is not None and lead(s).level < 12,
        done=lambda s: lead(s) is None or lead(s).level >= 12,
        legs=_train_to_level_12_legs,
        after="wander",
    ),
    Goal(
        id="cross_viridian_forest",
        description="Cross Viridian Forest to Pewter City",
        available=lambda s: (
            lead(s) is not None
            and lead(s).level >= 12
            and node(s) not in PEWTER_NODES
            and "beat_brock" not in s.flags
        ),
        done=lambda s: node(s) in PEWTER_NODES,
        legs=_cross_viridian_forest_legs,
        after=None,
    ),
    Goal(
        id="beat_brock",
        description="Challenge Brock at the Pewter Gym",
        available=lambda s: (
            node(s) in PEWTER_NODES
            and lead(s) is not None
            and lead(s).level >= 12
            and "beat_brock" not in s.flags
        ),
        done=lambda s: "beat_brock" in s.flags,
        legs=_beat_brock_legs,
        after="talk_brock",
    ),
    Goal(
        id="heal_at_center",
        description="Heal at the nearest Pokémon Center",
        available=lambda s: _lead_hurt(s) and _nearest_center(s) is not None,
        done=_heal_done,
        legs=_heal_at_center_legs,
        after="heal",
    ),
    Goal(
        id="train_nearby",
        description="Train in the grass nearby",
        available=lambda s: lead(s) is not None and s.map_id in GRASS_MAPS,
        done=lambda s: False,
        legs=_train_nearby_legs,
        after="wander",
    ),
]

STANDING_CLAUSE = "Build a party of three and keep them healthy."
"""Appended to the active goal when a battle question asks what the fight is for. The goal table
says where we are going; this says what we are keeping true along the way, which is what makes
catching and healing read as part of the plan rather than a distraction from it."""


def battle_goal(goal: "Goal | None", *, fallback: str) -> str:
    """The objective sent with a battle question: the goal Jev is pursuing, plus the standing
    clause. `fallback` (the `--battle-goal` flag) covers the gap before a goal is picked."""
    if goal is None:
        return fallback
    return f"{goal.description}. {STANDING_CLAUSE}"


ALWAYS = ("heal_at_center", "train_nearby")


def available_goals(state: GameState) -> list[Goal]:
    """`GOALS`, in table order, filtered to what's available and not already done."""
    return [g for g in GOALS if g.available(state) and not g.done(state)]


def goal_by_id(goal_id: str) -> Goal:
    for g in GOALS:
        if g.id == goal_id:
            return g
    raise KeyError(goal_id)
