"""Display names for map ids. Species, moves, types, and items join in milestone 2."""

import json
from dataclasses import dataclass
from pathlib import Path

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


_DATA = Path(__file__).parent / "data"


def _load(name: str) -> dict:
    return json.loads((_DATA / name).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class MoveData:
    name: str
    type: str
    power: int
    pp: int


SPECIES: dict[int, str] = {int(k): v for k, v in _load("species.json").items()}
MOVES: dict[int, MoveData] = {int(k): MoveData(**v) for k, v in _load("moves.json").items()}
ITEMS: dict[int, str] = {int(k): v for k, v in _load("items.json").items()}
TRAINER_CLASSES: dict[int, str] = {int(k): v for k, v in _load("trainers.json").items()}

# pokered constants/type_constants.asm. Ids 9..19 are unused in the game.
TYPES: dict[int, str] = {
    0: "Normal",
    1: "Fighting",
    2: "Flying",
    3: "Poison",
    4: "Ground",
    5: "Rock",
    6: "Bird",
    7: "Bug",
    8: "Ghost",
    20: "Fire",
    21: "Water",
    22: "Grass",
    23: "Electric",
    24: "Psychic",
    25: "Ice",
    26: "Dragon",
}


def species_name(species_id: int) -> str:
    return SPECIES.get(species_id, f"Species {species_id}")


def move_data(move_id: int) -> MoveData | None:
    return MOVES.get(move_id)


def type_name(type_id: int) -> str:
    return TYPES.get(type_id, f"Type {type_id}")


def item_name(item_id: int) -> str:
    return ITEMS.get(item_id, f"Item {item_id}")


def trainer_class_name(class_id: int) -> str:
    return TRAINER_CLASSES.get(class_id, f"Trainer {class_id}")
