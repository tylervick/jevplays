"""Display names for map ids. Species, moves, types, and items join in milestone 2."""

_CITIES = {
    0: "Pallet Town",
    1: "Viridian City",
    2: "Pewter City",
    3: "Cerulean City",
    4: "Lavender Town",
    5: "Vermilion City",
    6: "Celadon City",
    7: "Fuchsia City",
    8: "Cinnabar Island",
    9: "Indigo Plateau",
    10: "Saffron City",
}

_EARLY_GAME = {
    37: "Red's House 1F",
    38: "Red's House 2F",
    39: "Blue's House",
    40: "Oak's Lab",
    41: "Viridian Pokémon Center",
    42: "Viridian Mart",
    43: "Viridian School",
    44: "Viridian Nickname House",
    45: "Viridian Gym",
    46: "Diglett's Cave (Route 2)",
    47: "Viridian Forest North Gate",
    48: "Route 2 Trade House",
    49: "Route 2 Gate",
    50: "Viridian Forest South Gate",
    51: "Viridian Forest",
    52: "Museum 1F",
    53: "Museum 2F",
    54: "Pewter Gym",
    55: "Pewter Nidoran House",
    56: "Pewter Mart",
    57: "Pewter Speech House",
    58: "Pewter Pokémon Center",
    59: "Mt. Moon 1F",
}

MAP_NAMES: dict[int, str] = {**_CITIES, **_EARLY_GAME}
# Map ids 12..36 are Route 1..Route 25 in order.
MAP_NAMES.update({map_id: f"Route {map_id - 11}" for map_id in range(12, 37)})


def map_name(map_id: int) -> str:
    return MAP_NAMES.get(map_id, f"Map {map_id}")
