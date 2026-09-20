"""Story progress flags. The table is pokered's event list; the tracked subset is what goals read."""

import json
from pathlib import Path

from jevplays.emulator import ram

EVENTS: dict[str, int] = json.loads(
    (Path(__file__).parent / "data" / "events.json").read_text(encoding="utf-8")
)

TRACKED_FLAGS: tuple[str, ...] = (
    "oak_appeared_in_pallet",
    "followed_oak_into_lab",
    "oak_asked_to_choose_mon",
    "got_starter",
    "battled_rival_in_oaks_lab",
    "got_oaks_parcel",
    "oak_got_parcel",
    "got_pokedex",
    "got_pokeballs_from_oak",
    "got_town_map",
    "beat_brock",
)


def flag_index(name: str) -> int:
    return EVENTS[name]


def flags_set(mem: ram.Memory) -> frozenset[str]:
    return frozenset(name for name in TRACKED_FLAGS if ram.flag_bit(mem, EVENTS[name]))
