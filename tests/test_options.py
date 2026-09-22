import re

from jevplays.emulator import ram
from jevplays.executor import maps
from jevplays.executor.goals import Goal, legs_to
from jevplays.executor.navigate import Leg
from jevplays.executor.options import (
    NPC_CAP,
    Memory,
    generate,
    option_verb,
    place_words,
    sprite_noun,
)
from jevplays.state.snapshot import Sprite, snapshot
from tests.support import FakeEmulator, install_map, write_mon

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

DEFAULT_SPRITES = ((3, 0x29, 6, 1), (4, 0x04, 1, 6), (5, 0x04, 1, 1))
"""nurse at (6,1), reachable; a youngster at (1,6), reachable; a youngster at (1,1), deep inside
the wall square -- both its adjacent tiles and the tiles two steps beyond them are wall (or off
the map), so it is never offered even with the counter jump."""

DEFAULT_CONNECTIONS = {"north": 13, "east": 12}
DEFAULT_WARPS = [(0, 7, 0, 41), (1, 7, 0, 41), (7, 7, 0, 42)]


def town(memory=None, sprites=DEFAULT_SPRITES, connections=None, warps=None, grass_rate=25):
    emu = FakeEmulator()
    install_map(
        emu,
        ROWS,
        warps=DEFAULT_WARPS if warps is None else warps,
        connections=DEFAULT_CONNECTIONS if connections is None else connections,
    )
    emu.set_sprites(list(sprites))
    emu.mem[0xD362], emu.mem[0xD361] = 4, 4  # the player at (4,4)  (wXCoord, wYCoord)
    emu.mem[ram.wGrassRate] = grass_rate  # a map whose grass can start a battle, unless a test says otherwise
    return emu, snapshot(emu), memory or Memory.empty()


def hurt_lead(emu, *, hp=5, max_hp=20):
    """Write a single, hurt party lead onto `emu.mem` -- everything `hp_bucket` needs."""
    write_mon(
        emu.mem,
        ram.wPartyMons,
        ram.wPartyMonNicks,
        species=176,
        level=5,
        hp=hp,
        max_hp=max_hp,
        types=(20, 20),
        moves=(10,),
        pps=(35,),
        nickname="CHARMANDER",
    )
    emu.mem[ram.wPartyCount] = 1


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


def test_an_item_on_the_ground_is_picked_up_rather_than_talked_to():
    """A Poké Ball sprite is an item lying there, not somebody to talk to. The macro is the same
    `talk_<slot>` -- walking up and pressing A is how an item ball is picked up -- so only the
    words change, and they are the only part of it Jev ever reads."""
    emu, state, memory = town(sprites=((3, 0x3D, 6, 1), (4, 0x04, 1, 6)))
    texts = {o.id: o.text for o in generate(emu, state, memory, None)}
    assert texts["npc_3"] == "pick up an item on the ground to the north-east"
    assert texts["npc_4"].startswith("talk to a youngster")
    ball = next(o for o in generate(emu, state, memory, None) if o.id == "npc_3")
    assert ball.kind == "npc" and ball.after == "talk_3"


def test_an_unreachable_npc_is_not_offered_and_the_cap_holds():
    emu, state, memory = town(sprites=tuple((s, 0x04, 5, 6) for s in range(1, 10)) + ((11, 0x04, 1, 1),))
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


def test_a_counter_npc_is_offered_two_tiles_away_facing_across_it():
    # cols 0-1 are wall for every row (the counter and, behind it, the nurse's own tile); cols
    # 2-3 are floor. The nurse's four adjacent tiles are all wall, so only the two-away tile
    # across the counter (col 2) is ever a candidate.
    emu = FakeEmulator()
    install_map(emu, ["##..", "##..", "##..", "##.."])
    emu.set_sprites([(3, 0x29, 0, 1)])  # the nurse, behind the counter
    emu.mem[0xD362], emu.mem[0xD361] = 3, 3  # the player well clear of the counter
    state = snapshot(emu)
    nurse = next(o for o in generate(emu, state, Memory.empty(), None) if o.id == "npc_3")
    assert nurse.target == (2, 1) and nurse.face == "left" and nurse.after == "heal"


def test_an_exit_whose_edge_cannot_be_reached_is_not_offered():
    """Route 2's north edge is behind Viridian Forest: the connection is in RAM either way, but
    offering it from the wrong side of a wall only gets the navigator stuck and the option marked
    `tried` for something it never had a chance at."""
    emu = FakeEmulator()
    install_map(emu, ["####", "####", "....", "...."], connections={"north": 13, "south": 12})
    emu.mem[0xD362], emu.mem[0xD361] = 1, 3  # the player in the open southern half
    state = snapshot(emu)
    ids = [o.id for o in generate(emu, state, Memory.empty(), None)]
    assert "exit_south" in ids and "exit_north" not in ids


def test_an_unmapped_destination_reads_somewhere_new():
    emu, state, memory = town(connections={"north": 199}, warps=[(0, 7, 0, 199)])
    texts = {o.id: o.text for o in generate(emu, state, memory, None)}
    assert texts["exit_north"] == "go north to somewhere new"
    assert texts["door_199"] == "enter somewhere new"


def test_heal_option_comes_first_for_a_hurt_lead_with_a_route_to_a_center():
    emu, state, memory = town()
    hurt_lead(emu)
    state = snapshot(emu)  # map id 0 is pallet_town, which routes to viridian_pokecenter
    opts = generate(emu, state, memory, None)
    assert opts[0].id == "heal" and opts[0].kind == "heal" and opts[0].after == "heal"
    assert opts[0].legs == tuple(legs_to(state, "viridian_pokecenter"))


def test_no_heal_option_inside_a_pokemon_center():
    emu, state, memory = town()
    hurt_lead(emu)
    emu.mem[ram.wCurMap] = maps.VIRIDIAN_POKECENTER
    state = snapshot(emu)
    opts = generate(emu, state, memory, None)
    assert not any(o.kind == "heal" for o in opts)


def milestone_stub(*, description="get the parcel to the professor", legs=(), after="talk_oak", done=False):
    return Goal(
        id="test_milestone",
        description=description,
        available=lambda s: True,
        done=lambda s: done,
        legs=lambda s: list(legs),
        after=after,
    )


def test_milestone_option_comes_first_with_the_new_text():
    milestone = milestone_stub(legs=[Leg(kind="walk", target=(5, 5))])
    emu, state, memory = town()
    opts = generate(emu, state, memory, milestone)
    assert opts[0].id == "milestone" and opts[0].kind == "milestone"
    assert opts[0].text == "work on the milestone: get the parcel to the professor"
    assert opts[0].after == "talk_oak"
    assert opts[0].legs == (Leg(kind="walk", target=(5, 5)),)


def test_milestone_option_is_omitted_on_an_unmapped_node():
    milestone = milestone_stub()
    emu, state, memory = town()
    emu.mem[ram.wCurMap] = 250  # not in maps.NODE_NAMES
    state = snapshot(emu)
    opts = generate(emu, state, memory, milestone)
    assert not any(o.kind == "milestone" for o in opts)


def test_a_milestone_that_can_neither_be_walked_to_nor_acted_on_is_not_offered():
    """#53. A milestone whose route comes back empty has no legs, and with no `after` macro it
    also has nothing to do where it stands -- so it does literally nothing, reports itself done,
    stamps no memory, and comes back `(new)` for Jev to pick again. The probe past Brock chose
    one 654 times in 86 seconds without leaving the building."""
    milestone = milestone_stub(legs=(), after=None)
    emu, state, memory = town()
    opts = generate(emu, state, memory, milestone)
    assert not any(o.kind == "milestone" for o in opts)


def test_a_milestone_with_no_legs_but_a_macro_is_still_offered():
    """The other reason legs come back empty: we are already standing where the milestone
    happens (talk to Oak in his lab). That one has work to do here and must keep being offered."""
    milestone = milestone_stub(legs=(), after="talk_oak")
    emu, state, memory = town()
    opts = generate(emu, state, memory, milestone)
    assert opts[0].kind == "milestone" and opts[0].legs == ()


def test_texts_and_labels_carry_no_numbers():
    # Route names carry a digit by design (map_name(13) == "Route 2"), so this uses a map with
    # no connections and covers every other kind: door, npc, grass, heal, and milestone (whose
    # description here is itself digit-free, same as this test needs of everything else).
    emu, state, memory = town(connections={})
    hurt_lead(emu)
    state = snapshot(emu)
    milestone = milestone_stub(description="get the parcel to the professor")
    for o in generate(emu, state, memory, milestone):
        assert not re.search(r"\d", o.labelled()), o.labelled()


def test_place_words_and_nouns():
    assert sprite_noun(0x29) == "the nurse" and sprite_noun(0x03) == "Professor Oak"
    assert sprite_noun(0x3D) == "an item on the ground"
    assert option_verb("an item on the ground") == "pick up" and option_verb("the nurse") == "talk to"
    assert sprite_noun(200) == "someone"
    assert place_words((4, 4), Sprite(1, 4, 4, 1), 4) == "just to the north"
    assert place_words((4, 4), Sprite(1, 4, 12, 12), 4) == "to the south-east"
    assert place_words((4, 4), Sprite(1, 0x26, 0, 5), 0x26) == "behind the counter"


def test_grass_is_not_offered_where_no_wild_pokemon_live():
    """Pallet Town has grass tiles and no encounter table, so standing in it can never start a
    battle. Offering it cost a run the whole option budget waiting for one (#44). The game knows:
    `wGrassRate` is zero on a map with no wild Pokémon."""
    emu, state, memory = town(grass_rate=0)
    assert "grass" not in [o.id for o in generate(emu, state, memory, milestone=None)]


def test_grass_is_offered_where_wild_pokemon_do_live():
    emu, state, memory = town(grass_rate=25)  # Route 1's rate
    assert "grass" in [o.id for o in generate(emu, state, memory, milestone=None)]
