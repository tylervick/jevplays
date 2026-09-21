import re

from jevplays.executor.options import NPC_CAP, Memory, generate, place_words, sprite_noun
from jevplays.state.snapshot import Sprite, snapshot
from tests.support import FakeEmulator, install_map

# 8x8 grid cells (= 4x4 blocks; install_map pairs 2x2 characters into one block, and build_grid
# expands each block back into a 2x2 quadrant, so these characters land on the same coordinates
# generate() sees). '#' blocked, '.' floor, '~' grass. Rows 0-3, cols 0-3 are a solid wall square
# (block-uniform per install_map) so a sprite deep inside it truly has no walkable neighbour.
ROWS = [
    "####....",
    "####....",
    "####....",
    "####....",
    "....~~..",
    "....~~..",
    "........",
    "........",
]

DEFAULT_SPRITES = ((3, 0x29, 6, 1), (4, 0x04, 1, 6), (5, 0x04, 2, 0))
"""nurse at (6,1), reachable; a youngster at (1,6), reachable; a youngster at (2,0), inside the
wall square -- all four of its neighbours are wall, so it is never offered."""

DEFAULT_CONNECTIONS = {"north": 13, "east": 12}
DEFAULT_WARPS = [(0, 7, 0, 41), (1, 7, 0, 41), (7, 7, 0, 42)]


def town(memory=None, sprites=DEFAULT_SPRITES, connections=None):
    emu = FakeEmulator()
    install_map(
        emu,
        ROWS,
        warps=DEFAULT_WARPS,
        connections=DEFAULT_CONNECTIONS if connections is None else connections,
    )
    emu.set_sprites(list(sprites))
    emu.mem[0xD362], emu.mem[0xD361] = 4, 4  # the player at (4,4)  (wXCoord, wYCoord)
    return emu, snapshot(emu), memory or Memory.empty()


def test_options_cover_exits_doors_reachable_npcs_and_grass_in_order():
    emu, state, memory = town()
    ids = [o.id for o in generate(emu, state, memory, milestone=None)]
    assert ids == ["exit_north", "exit_east", "door_41", "door_42", "npc_3", "npc_4", "grass"]
    texts = {o.id: o.text for o in generate(emu, state, memory, None)}
    assert (
        texts["exit_north"] == "go north to Route 2" and texts["door_41"] == "enter Viridian Pokémon Center"
    )
    assert texts["npc_3"] == "talk to the nurse behind the counter"
    assert texts["npc_4"].startswith("talk to a youngster")
    assert texts["grass"] == "train in the tall grass here"


def test_an_unreachable_npc_is_not_offered_and_the_cap_holds():
    emu, state, memory = town(sprites=tuple((s, 0x04, 5, 6) for s in range(1, 10)) + ((11, 0x04, 2, 0),))
    npcs = [o for o in generate(emu, state, memory, None) if o.kind == "npc"]
    assert len(npcs) == NPC_CAP and all(o.id != "npc_11" for o in npcs)


def test_memory_words():
    emu, state, memory = town()
    memory.note_map(41)
    memory.note_talked(state.map_id, 3)
    memory.note_tried(state.map_id, "grass")
    words = {o.id: o.memory for o in generate(emu, state, memory, None)}
    assert words == {
        "exit_north": "new",
        "exit_east": "new",
        "door_41": "visited",
        "door_42": "new",
        "npc_3": "talked already",
        "npc_4": "new",
        "grass": "tried",
    }
    assert Memory.from_dict(memory.to_dict()) == memory


def test_npc_plan_walks_to_a_neighbour_and_faces_the_sprite():
    emu, state, memory = town()
    nurse = next(o for o in generate(emu, state, memory, None) if o.id == "npc_3")
    assert nurse.after == "heal" and nurse.legs[0].kind == "walk"
    assert nurse.face in ("up", "down", "left", "right") and nurse.target is not None


def test_texts_and_labels_carry_no_numbers():
    # Route names carry a digit by design (map_name(13) == "Route 2"), so this checks the map
    # that has no numbered exits: doors, NPCs, and grass, which are the option kinds that must
    # never leak one.
    emu, state, memory = town(connections={})
    for o in generate(emu, state, memory, None):
        assert not re.search(r"\d", o.labelled()), o.labelled()


def test_place_words_and_nouns():
    assert sprite_noun(0x29) == "the nurse" and sprite_noun(0x03) == "Professor Oak"
    assert sprite_noun(0x3D) == "an item on the ground"
    assert sprite_noun(200) == "someone"
    assert place_words((4, 4), Sprite(1, 4, 4, 1), 4) == "near to the north"
    assert place_words((4, 4), Sprite(1, 4, 12, 12), 4) == "to the south-east"
    assert place_words((4, 4), Sprite(1, 0x26, 0, 5), 0x26) == "behind the counter"
