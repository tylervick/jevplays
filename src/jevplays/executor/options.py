"""What the loop can do next, built fresh from the map every decision.

`generate` reads the same RAM the navigator already reads (connections, warps, sprites, the
walkability grid) and turns it into a list of `Option`s: exits, doors, reachable NPCs, tall
grass, the active milestone, and a heal trip when the lead needs one. Jev picks one by id; the
loop runs its `legs` and then its `after` macro. Jev has no memory between calls, so every
option carries a `memory` word (`Memory.word`) that says whether this run has done it before.
"""

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

from jevplays.brain.buckets import hp_bucket
from jevplays.emulator import ram
from jevplays.executor import maps, world
from jevplays.executor.goals import Goal, legs_to
from jevplays.executor.goals import node as goals_node
from jevplays.executor.navigate import Leg
from jevplays.executor.shop import shopping_list
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
    ("mt_moon_pokecenter", maps.MT_MOON_POKECENTER),
    ("cerulean_pokecenter", maps.CERULEAN_POKECENTER),
)
"""Pokémon Center nodes the `heal` option can route to, and their map ids. The ones past Pewter
are reached only over the run's walked graph: until the run has been inside, there is no route."""

_SPRITES_PATH = Path(__file__).resolve().parent.parent / "state" / "data" / "sprites.json"
SPRITE_NOUNS: dict[int, str] = {
    int(k): v for k, v in json.loads(_SPRITES_PATH.read_text(encoding="utf-8")).items()
}


@dataclass(frozen=True)
class Option:
    id: str  # exit_north | door_41 | npc_3 | grass | milestone | heal
    kind: str  # exit | door | npc | grass | milestone | heal
    text: str  # what Jev reads, without the memory word
    memory: str  # new | visited | visited, leads nowhere new | talked already | tried
    legs: tuple[Leg, ...]
    after: str | None  # macro name: talk_<slot> | heal | shop | wander | the milestone's after | None
    target: tuple[int, int] | None = None  # the tile the npc option talks from
    face: str | None = None  # the direction it faces
    dest_map: int | None = None  # exit/door destination

    def labelled(self) -> str:
        return f"{self.text} ({self.memory})"


_OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}
"""The way back along a map connection. Gen 1's are symmetric."""


Landing = tuple[str, int, int | str | None]
"""The identity of a way out as the option generator sees it, before anyone knows where it lands:
("warp", destination map, destination warp id or None) for a door, ("edge", destination map,
direction) for a map connection. `Memory.landings` records the place each one led to (#137)."""


def option_landing(option: "Option") -> Landing | None:
    if option.kind not in ("exit", "door") or option.dest_map is None or not option.legs:
        return None
    leg = option.legs[0]
    if option.kind == "exit":
        return ("edge", option.dest_map, leg.direction)
    return ("warp", option.dest_map, leg.warp_id)


def _outdoors(place: str) -> bool:
    map_id = maps.map_id_of(place)
    return map_id is not None and map_id < ram.FIRST_INDOOR_MAP


@dataclass
class Memory:
    """What this run has already done, so Jev can be told rather than have to remember.

    Owned by the loop, one per run, written to `runs/<stamp>/memory.json` after every change
    and reloaded on `--resume`.
    """

    visited_maps: set[int]
    talked: set[tuple[int, int]]  # (map id, sprite slot)
    tried: set[tuple[int, str]]  # (map id, option id)
    links: dict[str, list[maps.Link]] = field(default_factory=dict)
    """The map graph this run has walked: node name -> the links crossed out of it. `maps.route`
    searches it alongside the hand-written `maps.LINKS`, which is what lets a milestone or a heal
    trip be planned from a map nobody typed into the table (#35)."""
    exits: dict[str, set[Landing]] = field(default_factory=dict)
    """place -> the ways out offered there, from every spot in it Jev was asked on (a union: what is
    offered depends on where we stand)."""
    landings: dict[Landing, str | None] = field(default_factory=dict)
    """way out -> the place it was found to lead to, written at the crossing. None for one taken by
    a run from before places existed: still "visited", but the frontier search cannot follow it."""

    @classmethod
    def empty(cls) -> "Memory":
        return cls(visited_maps=set(), talked=set(), tried=set(), links={}, exits={}, landings={})

    def to_dict(self) -> dict:
        return {
            "visited_maps": sorted(self.visited_maps),
            "talked": sorted([list(pair) for pair in self.talked]),
            "tried": sorted([list(pair) for pair in self.tried]),
            "links": {
                node: [[link.kind, link.dest_node, link.direction, link.dest_map] for link in crossed]
                for node, crossed in sorted(self.links.items())
            },
            "exits": {
                place: sorted((list(way) for way in offered), key=str)
                for place, offered in sorted(self.exits.items())
            },
            "landings": [[list(way), place] for way, place in sorted(self.landings.items(), key=str)],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Memory":
        return cls(
            visited_maps=set(d.get("visited_maps", [])),
            talked={tuple(pair) for pair in d.get("talked", [])},
            tried={tuple(pair) for pair in d.get("tried", [])},
            # `.get` rather than `[]`: a memory.json written before the graph existed has no
            # links key, and `--resume` has to keep reading it (#35).
            links={
                node: [maps.Link(kind=k, dest_node=n, direction=w, dest_map=m) for k, n, w, m in crossed]
                for node, crossed in d.get("links", {}).items()
            },
            # A memory.json from before places existed keys exits by map id and lists ladders:
            # those exits are dropped (they named maps, not places) and each ladder becomes a
            # landing with no known place (#137).
            exits={
                place: {tuple(way) for way in offered}
                for place, offered in d.get("exits", {}).items()
                if not str(place).isdigit()
            },
            landings={
                **{("warp", dest, warp_id): None for _map, dest, warp_id in d.get("ladders", [])},
                **{tuple(way): place for way, place in d.get("landings", [])},
            },
        )

    def note_map(self, map_id: int) -> None:
        self.visited_maps.add(map_id)

    def note_crossing(
        self,
        from_node: str,
        to_node: str,
        *,
        direction: str | None = None,
        dest_map: int | None = None,
        back_dest_map: int = maps.WARP_LAST_MAP,
    ) -> None:
        """Remember a crossing the run actually walked, and the way back along it.

        Recorded from crossings rather than from each map's connection table because the table
        reports the whole map's connections, not the ones reachable from where we stand: Route
        2's two halves both list `north`, while only the north half can walk it. A crossing is
        ground truth, and it knows both ends, which a warp's `0xFF` "back the way you came in"
        destination does not (#35).

        Gen 1's overworld connections are symmetric, so one walk teaches both directions; a
        warp's reverse is the `WARP_LAST_MAP` door that `maps.LINKS` already uses for a
        building's way out, unless the caller saw a warp straight back (`back_dest_map`): a cave
        ladder names the floor it leads to, has no `WARP_LAST_MAP` warp at all, and a way back
        recorded as one sent a heal trip from Mt. Moon B2F looking for a warp that is not there.
        """
        if direction is not None:
            forward = maps.edge(direction, to_node)
            back = maps.edge(_OPPOSITE[direction], from_node)
        else:
            forward = maps.warp(dest_map, to_node)
            back = maps.warp(back_dest_map, from_node)
        self._add_link(from_node, forward)
        self._add_link(to_node, back)

    def _add_link(self, node: str, link: maps.Link) -> None:
        """One link per (kind, destination), preferring the one that names a destination map.

        Walking a warp both ways records `warp(dest)` going in and `warp(WARP_LAST_MAP)` coming
        back out, for the same pair of nodes. Both are true, but only a concrete map id gives the
        navigator something to check a crossing against, so it wins."""
        here = self.links.setdefault(node, [])
        for i, seen in enumerate(here):
            if (seen.kind, seen.dest_node) != (link.kind, link.dest_node):
                continue
            if seen.dest_map in (None, maps.WARP_LAST_MAP) and link.dest_map not in (
                None,
                maps.WARP_LAST_MAP,
            ):
                here[i] = link
            return
        here.append(link)

    def note_exits(self, place: str, options: "list[Option]") -> None:
        """Remember the ways out this place offered."""
        offered = {landing for o in options if (landing := option_landing(o)) is not None}
        self.exits.setdefault(place, set()).update(offered)

    def note_landing(self, landing: Landing, place: str | None) -> None:
        """Remember where a way out was found to lead, at the moment it was crossed."""
        self.landings[landing] = place

    def leads_nowhere_new(self, here: str, landing: Landing) -> bool:
        """Whether everything beyond `landing` has been seen: every place reachable from where it
        lands, over ways out already taken and never back through `here` nor into an outdoor
        map, has had every way out it offered taken. A building is the one-place case; a cave
        ladder whose pockets below are exhausted is the case this exists for (#137).

        Said only when it is sure: a landing never taken, one whose place is unknown, one that
        opens onto an outdoor map other than here, or a place Jev was never asked on all answer
        False, because any of them may lead somewhere new."""
        start = self.landings.get(landing)
        if start is None or start == here or _outdoors(start):
            return False
        seen = {here}
        stack = [start]
        while stack:
            place = stack.pop()
            if place in seen:
                continue
            seen.add(place)
            if place not in self.exits:
                return False
            for way in self.exits[place]:
                if way not in self.landings:
                    return False
                beyond = self.landings[way]
                if beyond is None:
                    return False
                if beyond in seen:
                    continue
                if _outdoors(beyond):
                    return False
                stack.append(beyond)
        return True

    def note_talked(self, map_id: int, slot: int) -> None:
        self.talked.add((map_id, slot))

    def note_tried(self, map_id: int, option_id: str) -> None:
        self.tried.add((map_id, option_id))

    def word(self, map_id: int, place: str, option: "Option") -> str:
        if (map_id, option.id) in self.tried:
            return "tried"
        if option.kind == "npc":
            slot = int(option.id.split("_", 1)[1])
            return "talked already" if (map_id, slot) in self.talked else "new"
        landing = option_landing(option)
        if option.kind == "door" and option.legs[0].warp_id is not None:
            # One of several ladders to the same floor: the floor being visited says nothing
            # about where this one lands (#129).
            return "visited" if landing in self.landings else "new"
        if option.kind in ("exit", "door"):
            if option.dest_map not in self.visited_maps:
                return "new"
            # Only the dead end is said. "visited, leads on to new places" was tried and drew Jev
            # harder than "new" did: 4 of 4 probe runs went Pewter <-> Route 2 thousands of times,
            # both ways reading so, with Route 3 "(new)" at 0.20 against 0.72.
            if landing is not None and self.leads_nowhere_new(place, landing):
                return "visited, leads nowhere new"
            return "visited"
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
    return compass_words(player, (sprite.x, sprite.y))


def compass_words(player: tuple[int, int], cell: tuple[int, int]) -> str:
    dx, dy = cell[0] - player[0], cell[1] - player[1]
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


def _door_options(emu, warps: tuple[world.Warp, ...], state: GameState, grid: world.MapGrid) -> list[Option]:
    """One option per place a door leads to. Usually that is one per destination map; a cave
    floor's ladders to the same floor land in different walled-off pockets, so each landing (the
    warp's destination warp id) is an option of its own, told apart by where it is (#129).

    A door is offered only when it can be walked to: Mt. Moon B1F's way out to Route 4 is in
    another pocket of the floor, and offered from this one it failed, read "(tried)", and was
    chosen again a hundred times over. "Walked to" is judged on the terrain alone -- a sprite in a
    corridor moves -- and a warp on a tile the grid calls a wall cannot be judged, so it is offered
    as it always was."""
    options = []
    for dest in sorted({w.dest for w in warps}):
        landings = sorted({w.warp_id for w in warps if w.dest == dest})
        if len(landings) == 1:
            on_ground = any(w.dest == dest and grid.walkable(w.x, w.y) for w in warps)
            if on_ground and _walk_to_landing(grid, state.tile, warps, dest, landings[0]) is None:
                continue
            options.append(_door_option(emu, dest, None, state))
            continue
        ladders = []
        for warp_id in landings:
            walk = _walk_to_landing(grid, state.tile, warps, dest, warp_id)
            if walk is not None:
                ladders.append((walk, warp_id))
        ladders.sort()
        drafts = [_door_option(emu, dest, warp_id, state, where=cell) for (_n, cell), warp_id in ladders]
        texts = [d.text for d in drafts]
        for rank, draft in enumerate(drafts):
            same = [i for i, t in enumerate(texts) if t == draft.text]
            if len(same) > 1:
                draft = replace(draft, text=f"{draft.text}, the {_ORDINALS[same.index(rank)]}")
                draft = replace(draft, legs=(replace(draft.legs[0], label=draft.text),))
            options.append(draft)
    return options


_ORDINALS = ("nearest", "second nearest", "third nearest", "fourth nearest", "fifth nearest")


def _walk_to_landing(grid, here, warps, dest, warp_id) -> tuple[int, tuple[int, int]] | None:
    """(steps, tile) to the nearest walkable warp of one landing over the terrain, or None when
    none can be reached."""
    best = None
    for w in warps:
        if w.dest != dest or w.warp_id != warp_id or not grid.walkable(w.x, w.y):
            continue
        path = [] if (w.x, w.y) == here else world.astar(grid, here, (w.x, w.y))
        if path is not None and (best is None or len(path) < best[0]):
            best = (len(path), (w.x, w.y))
    return best


def first_leg_walkable(grid: world.MapGrid, here: tuple[int, int], warps, legs) -> bool:
    """Whether a planned route can start from where we stand, judged on the terrain.

    The run's map graph knows maps, not the walled-off pockets of a cave floor: a heal trip from
    Mt. Moon B1F's exit pocket was planned up a ladder to 1F that only another pocket has, offered,
    failed at once, and was chosen 2,300 times with the lead at critical HP. A first leg the grid
    cannot judge -- no such warp on walkable ground -- is let through, as before."""
    if not legs:
        return True
    leg = legs[0]
    if leg.kind == "edge":
        return world.reachable_edge(grid, here, leg.direction, frozenset()) is not None
    if leg.kind != "warp":
        return True
    on_ground = [w for w in warps if w.dest == leg.dest_map and grid.walkable(w.x, w.y)]
    if not on_ground:
        return True
    return any((w.x, w.y) == here or world.astar(grid, here, (w.x, w.y)) is not None for w in on_ground)


def _door_option(
    emu, dest: int, warp_id: int | None, state: GameState, where: tuple[int, int] | None = None
) -> Option:
    # WARP_LAST_MAP means "back out the way you came in", whose map id is in `wLastMap`. The
    # option's `dest_map` reads it so the door gets a memory word like any other; the leg
    # keeps WARP_LAST_MAP, so the navigator still cannot check where it lands (#8).
    text = "go back outside" if dest == ram.WARP_LAST_MAP else f"enter {_place_name(dest)}"
    stock = world.mart_inventory(emu, dest)
    # Only a shelf the run can buy from is worth naming: broke, or with nothing the clerk
    # would buy, the door advertised a shelf it could not use and Jev walked in and out (#52).
    if stock and shopping_list(state):
        # What a Mart is for, in the game's own words: nothing else Jev saw said so, and a
        # run passed the Mart 25 times with an empty bag and never caught anything (#110).
        text += f", which sells {', '.join(stock)}"
    if where is not None and where != state.tile:
        text += f" {compass_words(state.tile, where)}"
    elif where is not None:
        text += " right here"
    return Option(
        id=f"door_{dest}" if warp_id is None else f"door_{dest}_{warp_id}",
        kind="door",
        text=text,
        memory="",
        legs=(Leg(kind="warp", dest_map=dest, label=text, warp_id=warp_id),),
        after=None,
        dest_map=emu.mem[ram.wLastMap] if dest == ram.WARP_LAST_MAP else dest,
    )


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


def _npc_options(emu, grid: world.MapGrid, state: GameState) -> list[Option]:
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
            if state.party and all(mon.hp == mon.max_hp for mon in state.party):
                # Nobody to heal: like the broke clerk, the step would come back at once as a
                # success and read "(new)" for good. Eight probe runs past Brock talked to a nurse
                # at full HP for most of 30 minutes each.
                continue
            after = "heal"
        elif sprite.picture == CLERK_PICTURE:
            if not shopping_list(state):
                # Nothing the clerk would buy can be afforded or carried: the step would come back
                # at once as a success, never be marked tried, and read "(new)" for good. Past Brock
                # four runs chose it 200 times in a row.
                continue
            after = "shop"
            stock = world.mart_inventory(emu, state.map_id)
            if stock:
                text += f" to buy {', '.join(stock)}"
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


def _heal_option(state: GameState, node: str, links: dict, grid: world.MapGrid, warps) -> Option | None:
    if node in {n for n, _ in CENTERS}:
        return None  # the nurse there is the heal option
    lead = state.party[0] if state.party else None
    if lead is None or hp_bucket(lead.hp, lead.max_hp) not in ("hurt", "low", "critical"):
        return None
    best: tuple[int, str, int] | None = None
    for center_node, center_map in CENTERS:
        hops = maps.route(node, center_node, links=links)
        if hops is None:
            continue
        if best is None or len(hops) < best[0]:
            best = (len(hops), center_node, center_map)
    if best is None:
        return None
    _length, center_node, center_map = best
    legs = tuple(legs_to(state, center_node, links))
    if not first_leg_walkable(grid, state.tile, warps, legs):
        return None
    return Option(
        id="heal",
        kind="heal",
        text=f"go heal at {map_name(center_map)}",
        memory="",
        legs=legs,
        after="heal",
    )


def _milestone_option(
    state: GameState, milestone: Goal | None, node: str, links: dict, grid: world.MapGrid, warps
) -> Option | None:
    if milestone is None or milestone.done(state):
        return None
    if node not in maps.LINKS and node not in links:
        # The guard used to ask "is this node in the hand-written table". The graph makes the
        # right question "is this node in the graph at all" (#35): with no way out of here
        # nothing can be routed, and a milestone whose legs come back empty for that reason
        # would still carry its `after` macro and run it in the wrong place -- `choose_charmander`
        # walking up to a table that is not there. One crossing out of here is enough to lift it.
        return None
    legs = tuple(milestone.legs(state, links))
    if not legs and milestone.destination is not None and node != milestone.destination:
        # The same two meanings of empty legs, told apart by where the milestone happens rather
        # than by its macro: past Pewter nothing is hand-written, so until the run has walked to
        # the gym there is no route, and `talk_leader` run here would talk to whoever is
        # northernmost on the wrong map. Offer nothing; the exits and doors carry the run (#53).
        return None
    if not legs and milestone.after is None:
        # Empty legs mean one of two things: we are standing where the milestone happens (talk to
        # Oak in his lab), or `maps.route` found no way there at all. The macro tells them apart
        # -- without one there is nothing to do here and nowhere to walk, so the option would run,
        # report itself done, stamp nothing, and come back `(new)` for Jev to pick again. A probe
        # past Brock chose one 654 times in 86 seconds that way (#53). Offer nothing instead and
        # let the exits and doors carry the run: a beat Jev can reach by exploring is not a goal.
        return None
    if not first_leg_walkable(grid, state.tile, warps, legs):
        return None
    return Option(
        id="milestone",
        kind="milestone",
        text=f"work on the milestone: {milestone.description}",
        memory="",
        legs=legs,
        after=milestone.after,
    )


def towards_name(emu, dest_map: int) -> str:
    """What the direction word calls the place a milestone happens in: the outdoor map that shares
    its town-map cell -- the gym's town, not the gym -- or its own name when none does."""
    cell = world.town_map_cell(emu, dest_map)
    for map_id in range(ram.FIRST_INDOOR_MAP):
        if map_id in MAP_NAMES and world.town_map_cell(emu, map_id) == cell:
            return map_name(map_id)
    return _place_name(dest_map)


def _towards(
    emu,
    state: GameState,
    memory: Memory,
    milestone: Goal | None,
    connections: dict[str, int],
    drafts: list[Option],
) -> list[Option]:
    """The one way out of here that ends nearest the milestone's town on the town map, when it is
    nearer than here, ends ", towards <town>" (#136). The word is a bucket on the game's own map,
    not a bearing or a distance: past Brock every exit read "(visited)" and nothing said which way
    Cerulean lay, so all 8 probe runs got into Mt. Moon and drifted back west. Only a milestone
    that names where it happens (`Goal.destination`) has a town to point at; the hand-routed ones
    are offered as a route.

    Never "go back outside" or a building that leads nowhere new: where we came from is not the
    way on, and the first version pulled a run straight back out of Mt. Moon 1F past three new
    ladders because Route 4's cell is nearer than the cave's. Never a tie: two ladders to one
    floor say nothing.

    "Here" is this map's cell, unless the map's own way on is out of reach: Route 4's cell is its
    eastern part, beyond Mt. Moon, and from its west end the east edge to Cerulean cannot be
    walked to, so nothing read nearer than "here" and 7 of 8 runs stepped back to Route 3, whose
    Route 4 exit did read "towards", 5,600 times. A connection the RAM lists but the grid cannot
    reach, leading somewhere nearer than this cell, is the game's own sign that the cell is not
    where we stand: then "here" is the nearest exit we can take, and the cave reads as the way."""
    if milestone is None or milestone.destination is None:
        return drafts
    goal_map = maps.map_id_of(milestone.destination)
    if goal_map is None:
        return drafts
    goal = world.town_map_cell(emu, goal_map)

    def distance(map_id: int) -> int:
        return _town_map_distance(world.town_map_cell(emu, map_id), goal)

    here = distance(state.map_id)
    offered = {o.id for o in drafts}
    if any(f"exit_{d}" not in offered and distance(dest) < here for d, dest in connections.items()):
        exits = [distance(o.dest_map) for o in drafts if o.kind == "exit" and o.dest_map is not None]
        here = min(exits, default=_FAR)
    candidates = [
        o
        for o in drafts
        if o.kind in ("exit", "door")
        and o.dest_map is not None
        and o.legs[0].dest_map != ram.WARP_LAST_MAP
        and not ((way := option_landing(o)) is not None and memory.leads_nowhere_new(goals_node(state), way))
    ]
    if not candidates:
        return drafts
    best = min(distance(o.dest_map) for o in candidates)
    nearest = [o for o in candidates if distance(o.dest_map) == best]
    if best >= here or len(nearest) != 1:
        return drafts
    name = towards_name(emu, goal_map)
    return [replace(o, text=f"{o.text}, towards {name}") if o is nearest[0] else o for o in drafts]


_FAR = 1 << 8
"""Farther than any town-map cell: "here" when no exit can be taken at all."""


def _town_map_distance(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


GRASS_TEXT = "train in the tall grass here"
PARTY_GOAL = 3
"""The party the standing goal asks for (`goals.STANDING_CLAUSE`)."""


def _grass_text(state: GameState) -> str:
    """The grass option, saying so when a catch there is impossible for want of a ball. Runs
    bought their Poké Balls in Pewter, after the grass, and caught nothing; nothing at the grass
    said a ball was missing (#110). A fact that goes away once there is a ball or a full party,
    so there is nothing for shopping to fail to discharge (#52)."""
    has_ball = any(item.name == "POKE BALL" and item.quantity > 0 for item in state.bag)
    if has_ball or len(state.party) >= PARTY_GOAL:
        return GRASS_TEXT
    return f"{GRASS_TEXT}, with no Poké Balls to catch with"


def generate(emu, state: GameState, memory: Memory, milestone: Goal | None) -> list[Option]:
    mem = emu.mem
    node = goals_node(state)
    grid = world.build_grid(emu)

    drafts: list[Option] = []
    warps = world.read_warps(mem)
    milestone_option = _milestone_option(state, milestone, node, memory.links, grid, warps)
    if milestone_option is not None:
        drafts.append(milestone_option)
    heal_option = _heal_option(state, node, memory.links, grid, warps)
    if heal_option is not None:
        drafts.append(heal_option)
    blocked = frozenset(world.blocked_by_sprites(state.sprites))
    connections = world.read_connections(mem)
    drafts.extend(_exit_options(connections, grid, state.tile, blocked))
    drafts.extend(_door_options(emu, world.read_warps(mem), state, grid))
    drafts.extend(_npc_options(emu, grid, state))
    # Grass tiles are not the same thing as wild Pokémon: Pallet Town and Viridian City both
    # have patches with no encounter table, and standing in one waits out the whole option
    # budget for a battle that cannot start (#44). wGrassRate is the game's own answer.
    if grid.grass() and mem[ram.wGrassRate] > 0:
        drafts.append(
            Option(
                id="grass",
                kind="grass",
                text=_grass_text(state),
                memory="",
                legs=(),
                after="wander",
            )
        )

    memory.note_exits(node, drafts)
    drafts = _towards(emu, state, memory, milestone, connections, drafts)
    return [replace(option, memory=memory.word(state.map_id, node, option)) for option in drafts]
