"""The early game's map graph: how to get from one map to the next. Warps and edges are read from
the running game; this table only says which neighbour to take. Route 2 is two nodes because the
forest splits it and its map id is the same on both sides."""

from dataclasses import dataclass

from jevplays.emulator.ram import WARP_LAST_MAP

PALLET_TOWN, VIRIDIAN_CITY, PEWTER_CITY = 0, 1, 2
ROUTE_1, ROUTE_2, ROUTE_22 = 12, 13, 33
REDS_HOUSE_1F, REDS_HOUSE_2F, BLUES_HOUSE, OAKS_LAB = 37, 38, 39, 40
VIRIDIAN_POKECENTER, VIRIDIAN_MART = 41, 42
VIRIDIAN_FOREST_NORTH_GATE, VIRIDIAN_FOREST_SOUTH_GATE, VIRIDIAN_FOREST = 47, 50, 51
PEWTER_GYM, PEWTER_MART, PEWTER_POKECENTER = 54, 56, 58

NODE_NAMES = {
    PALLET_TOWN: "pallet_town",
    VIRIDIAN_CITY: "viridian_city",
    PEWTER_CITY: "pewter_city",
    ROUTE_1: "route_1",
    ROUTE_22: "route_22",
    REDS_HOUSE_1F: "reds_house_1f",
    REDS_HOUSE_2F: "reds_house_2f",
    BLUES_HOUSE: "blues_house",
    OAKS_LAB: "oaks_lab",
    VIRIDIAN_POKECENTER: "viridian_pokecenter",
    VIRIDIAN_MART: "viridian_mart",
    VIRIDIAN_FOREST_NORTH_GATE: "viridian_forest_north_gate",
    VIRIDIAN_FOREST_SOUTH_GATE: "viridian_forest_south_gate",
    VIRIDIAN_FOREST: "viridian_forest",
    PEWTER_GYM: "pewter_gym",
    PEWTER_MART: "pewter_mart",
    PEWTER_POKECENTER: "pewter_pokecenter",
}
ROUTE_2_SPLIT_ROW = 25

MAP_IDS: dict[str, int] = {name: map_id for map_id, name in NODE_NAMES.items()}
MAP_IDS["route_2_south"] = MAP_IDS["route_2_north"] = ROUTE_2
"""Node name -> map id: the reverse of `NODE_NAMES`, plus Route 2's two nodes, which are halves
of one map and so share its id. It is what turns a `Link`'s destination node back into the map id
an edge leg lands on, so the navigator can tell an arrival from a blackout. A node with no entry
(`map_<id>` for an unmapped map) is simply absent, and a leg built for it carries no `dest_map`
and is not checked."""


def node_of(map_id: int, x: int, y: int) -> str:
    if map_id == ROUTE_2:
        return "route_2_south" if y >= ROUTE_2_SPLIT_ROW else "route_2_north"
    return NODE_NAMES.get(map_id, f"map_{map_id}")


@dataclass(frozen=True)
class Link:
    kind: str  # "edge" | "warp"
    dest_node: str
    direction: str | None = None
    dest_map: int | None = None


def edge(direction, node):
    return Link("edge", node, direction=direction)


def warp(dest_map, node):
    return Link("warp", node, dest_map=dest_map)


EXIT = WARP_LAST_MAP

LINKS: dict[str, list[Link]] = {
    "reds_house_2f": [warp(REDS_HOUSE_1F, "reds_house_1f")],
    "reds_house_1f": [warp(EXIT, "pallet_town"), warp(REDS_HOUSE_2F, "reds_house_2f")],
    "blues_house": [warp(EXIT, "pallet_town")],
    "oaks_lab": [warp(EXIT, "pallet_town")],
    "pallet_town": [
        edge("north", "route_1"),
        warp(OAKS_LAB, "oaks_lab"),
        warp(REDS_HOUSE_1F, "reds_house_1f"),
        warp(BLUES_HOUSE, "blues_house"),
    ],
    "route_1": [edge("north", "viridian_city"), edge("south", "pallet_town")],
    "viridian_city": [
        edge("south", "route_1"),
        edge("north", "route_2_south"),
        edge("west", "route_22"),
        warp(VIRIDIAN_POKECENTER, "viridian_pokecenter"),
        warp(VIRIDIAN_MART, "viridian_mart"),
    ],
    "route_22": [edge("east", "viridian_city")],
    "viridian_pokecenter": [warp(EXIT, "viridian_city")],
    "viridian_mart": [warp(EXIT, "viridian_city")],
    "route_2_south": [
        edge("south", "viridian_city"),
        warp(VIRIDIAN_FOREST_SOUTH_GATE, "viridian_forest_south_gate"),
    ],
    "viridian_forest_south_gate": [warp(VIRIDIAN_FOREST, "viridian_forest"), warp(EXIT, "route_2_south")],
    "viridian_forest": [
        warp(VIRIDIAN_FOREST_NORTH_GATE, "viridian_forest_north_gate"),
        warp(VIRIDIAN_FOREST_SOUTH_GATE, "viridian_forest_south_gate"),
    ],
    "viridian_forest_north_gate": [warp(EXIT, "route_2_north"), warp(VIRIDIAN_FOREST, "viridian_forest")],
    "route_2_north": [
        edge("north", "pewter_city"),
        warp(VIRIDIAN_FOREST_NORTH_GATE, "viridian_forest_north_gate"),
    ],
    "pewter_city": [
        edge("south", "route_2_north"),
        warp(PEWTER_GYM, "pewter_gym"),
        warp(PEWTER_MART, "pewter_mart"),
        warp(PEWTER_POKECENTER, "pewter_pokecenter"),
    ],
    "pewter_gym": [warp(EXIT, "pewter_city")],
    "pewter_mart": [warp(EXIT, "pewter_city")],
    "pewter_pokecenter": [warp(EXIT, "pewter_city")],
}


def route(from_node: str, to_node: str) -> list[Link] | None:
    """Breadth-first over LINKS; the list of links to follow, or None."""
    from collections import deque

    if from_node == to_node:
        return []
    came: dict[str, tuple[str, Link] | None] = {from_node: None}
    queue = deque([from_node])
    while queue:
        node = queue.popleft()
        for link in LINKS.get(node, []):
            if link.dest_node in came:
                continue
            came[link.dest_node] = (node, link)
            if link.dest_node == to_node:
                path = []
                cur = to_node
                while came[cur] is not None:
                    prev, prev_link = came[cur]
                    path.append(prev_link)
                    cur = prev
                return path[::-1]
            queue.append(link.dest_node)
    return None
