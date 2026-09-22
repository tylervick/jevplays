"""What the loop can do next, built fresh from the map every decision.

`generate` reads the same RAM the navigator already reads (connections, warps, sprites, the
walkability grid) and turns it into a list of `Option`s: exits, doors, reachable NPCs, tall
grass, the active milestone, and a heal trip when the lead needs one. Jev picks one by id; the
loop runs its `legs` and then its `after` macro. Jev has no memory between calls, so every
option carries a `memory` word (`Memory.word`) that says whether this run has done it before.
"""

import json
from dataclasses import dataclass, replace
from pathlib import Path

from jevplays.brain.buckets import hp_bucket
from jevplays.emulator import ram
from jevplays.executor import maps, world
from jevplays.executor.goals import Goal, legs_to
from jevplays.executor.navigate import Leg
from jevplays.executor.talk import FACING_OFFSET, adjacent_tile
from jevplays.state.names import MAP_NAMES, map_name
from jevplays.state.snapshot import GameState, Sprite

NPC_CAP = 6
"""The most NPC options offered at once: the nearest this many, by walked path length."""

NEAR_TILES = 4
"""Manhattan distance within which a place word gets a "near " prefix."""

NURSE_PICTURE = 0x29
CLERK_PICTURE = 0x26
COUNTER_PICTURES = frozenset((NURSE_PICTURE, CLERK_PICTURE))
"""Sprites that stand behind a counter: their place word ignores position entirely."""

CENTERS: tuple[tuple[str, int], ...] = (
    ("viridian_pokecenter", maps.VIRIDIAN_POKECENTER),
    ("pewter_pokecenter", maps.PEWTER_POKECENTER),
)
"""Pokémon Center nodes the `heal` option can route to, and their map ids."""

_SPRITES_PATH = Path(__file__).resolve().parent.parent / "state" / "data" / "sprites.json"
SPRITE_NOUNS: dict[int, str] = {
    int(k): v for k, v in json.loads(_SPRITES_PATH.read_text(encoding="utf-8")).items()
}


@dataclass(frozen=True)
class Option:
    id: str  # exit_north | door_41 | npc_3 | grass | milestone | heal
    kind: str  # exit | door | npc | grass | milestone | heal
    text: str  # what Jev reads, without the memory word
    memory: str  # new | visited | talked already | tried
    legs: tuple[Leg, ...]
    after: str | None  # macro name: talk_<slot> | heal | shop | wander | the milestone's after | None
    target: tuple[int, int] | None = None  # the tile the npc option talks from
    face: str | None = None  # the direction it faces
    dest_map: int | None = None  # exit/door destination

    def labelled(self) -> str:
        return f"{self.text} ({self.memory})"


@dataclass
class Memory:
    """What this run has already done, so Jev can be told rather than have to remember.

    Owned by the loop, one per run, written to `runs/<stamp>/memory.json` after every change
    and reloaded on `--resume`.
    """

    visited_maps: set[int]
    talked: set[tuple[int, int]]  # (map id, sprite slot)
    tried: set[tuple[int, str]]  # (map id, option id)

    @classmethod
    def empty(cls) -> "Memory":
        return cls(visited_maps=set(), talked=set(), tried=set())

    def to_dict(self) -> dict:
        return {
            "visited_maps": sorted(self.visited_maps),
            "talked": sorted([list(pair) for pair in self.talked]),
            "tried": sorted([list(pair) for pair in self.tried]),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Memory":
        return cls(
            visited_maps=set(d.get("visited_maps", [])),
            talked={tuple(pair) for pair in d.get("talked", [])},
            tried={tuple(pair) for pair in d.get("tried", [])},
        )

    def note_map(self, map_id: int) -> None:
        self.visited_maps.add(map_id)

    def note_talked(self, map_id: int, slot: int) -> None:
        self.talked.add((map_id, slot))

    def note_tried(self, map_id: int, option_id: str) -> None:
        self.tried.add((map_id, option_id))

    def word(self, map_id: int, option: "Option") -> str:
        if (map_id, option.id) in self.tried:
            return "tried"
        if option.kind == "npc":
            slot = int(option.id.split("_", 1)[1])
            return "talked already" if (map_id, slot) in self.talked else "new"
        if option.kind in ("exit", "door"):
            return "visited" if option.dest_map in self.visited_maps else "new"
        return "new"


def sprite_noun(picture: int) -> str:
    return SPRITE_NOUNS.get(picture, "someone")


GROUND_SUFFIX = "on the ground"
"""How `sprites.json` ends the nouns for an item ball: "an item on the ground", "a fossil on the
ground". A ball is not talked to, so the option reads "pick up" instead."""


def option_verb(noun: str) -> str:
    """What the option does to a sprite: "talk to" for a person, "pick up" for an item lying on
    the ground. The macro is `talk_<slot>` either way -- walking up to an item ball and pressing
    A is how it is picked up -- so this changes only the words Jev reads."""
    return "pick up" if noun.endswith(GROUND_SUFFIX) else "talk to"


def place_words(player: tuple[int, int], sprite: Sprite, picture: int) -> str:
    if picture in COUNTER_PICTURES:
        return "behind the counter"
    dx, dy = sprite.x - player[0], sprite.y - player[1]
    ns = "north" if dy < 0 else "south" if dy > 0 else ""
    ew = "east" if dx > 0 else "west" if dx < 0 else ""
    compass = f"{ns}-{ew}" if ns and ew else ns or ew
    near = "just " if abs(dx) + abs(dy) <= NEAR_TILES else ""
    return f"{near}to the {compass}"


def _place_name(map_id: int) -> str:
    return map_name(map_id) if map_id in MAP_NAMES else "somewhere new"


def _exit_options(
    connections: dict[str, int],
    grid: world.MapGrid,
    here: tuple[int, int],
    blocked: frozenset,
) -> list[Option]:
    """One option per map connection the player can actually walk to.

    A connection the RAM lists is not always a way out from where we stand: Route 2's north edge
    is behind Viridian Forest, so "go north to Pewter City" would be offered from the south half
    of the route and the navigator would give up on it (and Jev would be told it was `tried`).
    `reachable_edge` is the same search the edge leg itself runs, so what is offered is what the
    walk would find.
    """
    options = []
    for direction in ("north", "south", "west", "east"):
        if direction not in connections:
            continue
        if world.reachable_edge(grid, here, direction, blocked) is None:
            continue
        dest = connections[direction]
        text = f"go {direction} to {_place_name(dest)}"
        options.append(
            Option(
                id=f"exit_{direction}",
                kind="exit",
                text=text,
                memory="",
                # The destination is on the leg as well as on the option: the connection table
                # says which map this edge comes out on, so the navigator can tell the crossing
                # from a blackout that moved us somewhere else entirely mid-walk.
                legs=(Leg(kind="edge", direction=direction, dest_map=dest, label=text),),
                after=None,
                dest_map=dest,
            )
        )
    return options


def _door_options(warps: tuple[world.Warp, ...]) -> list[Option]:
    options = []
    for dest in sorted({w.dest for w in warps}):
        # WARP_LAST_MAP means "back out the way you came in", whose map id is only in `wLastMap`,
        # which nothing here reads: so this door is always `(new)` and its leg has no destination
        # for the navigator to check. Reading `wLastMap` would fix both; deferred with #8.
        text = "go back outside" if dest == ram.WARP_LAST_MAP else f"enter {_place_name(dest)}"
        options.append(
            Option(
                id=f"door_{dest}",
                kind="door",
                text=text,
                memory="",
                legs=(Leg(kind="warp", dest_map=dest, label=text),),
                after=None,
                dest_map=dest,
            )
        )
    return options


_FACE_ORDER = ("left", "right", "up", "down")
"""The order `_npc_target` tries facings in. Horizontal before vertical: a counter's open front
is normally to one side, not past a wall corner underneath or above it, so on a tie (both the
Mart's clerk and, on a different map, a similarly-cornered sprite) this is what picks the tile
that is actually in front of the counter over one that merely happens to be the same distance
away around a corner."""


def _npc_target(
    grid: world.MapGrid, blocked: frozenset, start: tuple[int, int], sprite: Sprite
) -> tuple[int, tuple[int, int], str] | None:
    """The nearest reachable tile to talk to `sprite` from, and the face to talk with.

    Tries the four adjacent tiles first. When none of those is both walkable and reachable
    (a sprite standing behind a counter or table, like the nurse and the Mart clerk), tries the
    tile two steps away in each direction instead, accepting one only when the tile between is
    NOT walkable -- that's what makes it a counter to talk across rather than just a longer walk
    to an ordinary neighbour, which the first pass would already have found.
    """
    best: tuple[int, tuple[int, int], str] | None = None
    for face in _FACE_ORDER:
        near = adjacent_tile(sprite, face)
        if not grid.walkable(*near) or near in blocked:
            continue
        path = world.astar(grid, start, near, blocked=blocked)
        if path is None:
            continue
        if best is None or len(path) < best[0]:
            best = (len(path), near, face)
    if best is not None:
        return best
    for face in _FACE_ORDER:
        near = adjacent_tile(sprite, face)
        if grid.walkable(*near):
            continue  # not a counter -- an ordinary neighbour, already tried above
        dx, dy = FACING_OFFSET[face]
        far = (near[0] + dx, near[1] + dy)
        if not grid.walkable(*far) or far in blocked:
            continue
        path = world.astar(grid, start, far, blocked=blocked)
        if path is None:
            continue
        if best is None or len(path) < best[0]:
            best = (len(path), far, face)
    return best


def _npc_options(grid: world.MapGrid, state: GameState) -> list[Option]:
    blocked = frozenset(world.blocked_by_sprites(state.sprites))
    candidates: list[tuple[int, Sprite, tuple[int, int], str]] = []
    for sprite in state.sprites:
        if sprite.picture == 0:
            continue
        best = _npc_target(grid, blocked, state.tile, sprite)
        if best is not None:
            candidates.append((best[0], sprite, best[1], best[2]))
    candidates.sort(key=lambda c: c[0])
    options = []
    for _path_len, sprite, neighbour, face in candidates[:NPC_CAP]:
        noun = sprite_noun(sprite.picture)
        text = f"{option_verb(noun)} {noun} {place_words(state.tile, sprite, sprite.picture)}"
        after = f"talk_{sprite.slot}"
        if sprite.picture == NURSE_PICTURE:
            after = "heal"
        elif sprite.picture == CLERK_PICTURE:
            after = "shop"
        options.append(
            Option(
                id=f"npc_{sprite.slot}",
                kind="npc",
                text=text,
                memory="",
                legs=(Leg(kind="walk", target=neighbour, label=text),),
                after=after,
                target=neighbour,
                face=face,
            )
        )
    return options


def _heal_option(state: GameState, node: str) -> Option | None:
    if node in {n for n, _ in CENTERS}:
        return None  # the nurse there is the heal option
    lead = state.party[0] if state.party else None
    if lead is None or hp_bucket(lead.hp, lead.max_hp) not in ("hurt", "low", "critical"):
        return None
    best: tuple[int, str, int] | None = None
    for center_node, center_map in CENTERS:
        links = maps.route(node, center_node)
        if links is None:
            continue
        if best is None or len(links) < best[0]:
            best = (len(links), center_node, center_map)
    if best is None:
        return None
    _length, center_node, center_map = best
    return Option(
        id="heal",
        kind="heal",
        text=f"go heal at {map_name(center_map)}",
        memory="",
        legs=tuple(legs_to(state, center_node)),
        after="heal",
    )


def _milestone_option(state: GameState, milestone: Goal | None, node: str) -> Option | None:
    if milestone is None or milestone.done(state) or node.startswith("map_"):
        return None
    return Option(
        id="milestone",
        kind="milestone",
        text=f"work on the milestone: {milestone.description}",
        memory="",
        legs=tuple(milestone.legs(state)),
        after=milestone.after,
    )


def generate(emu, state: GameState, memory: Memory, milestone: Goal | None) -> list[Option]:
    mem = emu.mem
    node = maps.node_of(state.map_id, *state.tile)
    grid = world.build_grid(emu)

    drafts: list[Option] = []
    milestone_option = _milestone_option(state, milestone, node)
    if milestone_option is not None:
        drafts.append(milestone_option)
    heal_option = _heal_option(state, node)
    if heal_option is not None:
        drafts.append(heal_option)
    blocked = frozenset(world.blocked_by_sprites(state.sprites))
    drafts.extend(_exit_options(world.read_connections(mem), grid, state.tile, blocked))
    drafts.extend(_door_options(world.read_warps(mem)))
    drafts.extend(_npc_options(grid, state))
    # Grass tiles are not the same thing as wild Pokémon: Pallet Town and Viridian City both
    # have patches with no encounter table, and standing in one waits out the whole option
    # budget for a battle that cannot start (#44). wGrassRate is the game's own answer.
    if grid.grass() and mem[ram.wGrassRate] > 0:
        drafts.append(
            Option(
                id="grass",
                kind="grass",
                text="train in the tall grass here",
                memory="",
                legs=(),
                after="wander",
            )
        )

    return [replace(option, memory=memory.word(state.map_id, option)) for option in drafts]
