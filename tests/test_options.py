import json
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


def town(memory=None, sprites=DEFAULT_SPRITES, connections=None, warps=None, grass_rate=25, map_id=None):
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
    if map_id is not None:
        emu.mem[ram.wCurMap] = map_id
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


def milestone_stub(
    *, description="get the parcel to the professor", legs=(), after="talk_oak", done=False, dest=None
):
    """`dest` routes to a node the way a real milestone does; `legs` hands back a fixed list.

    They are alternatives, not a pair: passing both would silently drop `legs` and leave a test
    asserting against a plan it did not ask for."""
    assert not (dest and legs), "milestone_stub takes dest or legs, not both"
    plan = (lambda s, links: legs_to(s, dest, links=links)) if dest else (lambda s, links: list(legs))
    return Goal(
        id="test_milestone",
        description=description,
        available=lambda s: True,
        done=lambda s: done,
        legs=plan,
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


def test_a_node_with_no_way_out_of_it_still_withholds_the_milestone():
    """Generalises the old `map_` guard rather than dropping it (#35). A node the router knows
    nothing about can route nowhere, and a milestone offered there would still carry its `after`
    macro and run it in the wrong place -- `choose_charmander` walking up to a table that is not
    there. What changes is the question: not "is this node in the hand-written table" but "is it
    in the graph at all", so one crossing out of here lifts it."""
    emu, state, memory = town(map_id=250)  # not in maps.NODE_NAMES, and nothing walked out of it
    acts_here = milestone_stub(legs=(), after="choose_charmander")
    assert not any(o.kind == "milestone" for o in generate(emu, state, memory, acts_here))
    walked = Memory.empty()
    walked.note_crossing("map_250", "pallet_town", direction="south")
    assert generate(emu, state, walked, acts_here)[0].kind == "milestone"


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


# --- the graph the run builds (#35) ------------------------------------------------------------


def test_a_crossing_records_the_link_it_walked_and_its_reverse():
    """Gen 1 overworld connections are symmetric, so one walk east teaches the way back west.
    Without the reverse the return path would need a second walk to learn, which is the whole
    thing this is for."""
    memory = Memory.empty()
    memory.note_crossing("pewter_city", "map_14", direction="east")
    assert [(x.kind, x.dest_node, x.direction) for x in memory.links["pewter_city"]] == [
        ("edge", "map_14", "east")
    ]
    assert [(x.kind, x.dest_node, x.direction) for x in memory.links["map_14"]] == [
        ("edge", "pewter_city", "west")
    ]


def test_a_warp_crossing_records_the_way_back_out():
    memory = Memory.empty()
    memory.note_crossing("map_14", "map_60", dest_map=60)
    assert [(x.kind, x.dest_node, x.dest_map) for x in memory.links["map_14"]] == [("warp", "map_60", 60)]
    assert [(x.kind, x.dest_node, x.dest_map) for x in memory.links["map_60"]] == [
        ("warp", "map_14", maps.WARP_LAST_MAP)
    ]


def test_recording_the_same_crossing_twice_changes_nothing():
    memory = Memory.empty()
    memory.note_crossing("pewter_city", "map_14", direction="east")
    memory.note_crossing("pewter_city", "map_14", direction="east")
    assert len(memory.links["pewter_city"]) == 1 and len(memory.links["map_14"]) == 1


def test_links_survive_a_round_trip_through_the_run_directory():
    memory = Memory.empty()
    memory.note_crossing("pewter_city", "map_14", direction="east")
    back = Memory.from_dict(json.loads(json.dumps(memory.to_dict())))
    assert back.links == memory.links


def test_a_memory_written_before_the_graph_existed_still_loads():
    """`--resume` reads whatever `runs/<stamp>/memory.json` holds, and the ones already on disk
    have no links key."""
    back = Memory.from_dict({"visited_maps": [1], "talked": [], "tried": []})
    assert back.links == {} and back.visited_maps == {1}


def crossed_east_from_pewter():
    """A memory that has walked Pewter -> Route 3, which `maps.LINKS` does not know about."""
    memory = Memory.empty()
    memory.note_crossing("pewter_city", "map_14", direction="east")
    return memory


def test_legs_to_plans_over_the_walked_graph_and_stamps_the_destination_map():
    """The `dest_map` is what lets the navigator tell the crossing from a blackout, so a leg
    built for a synthesised node has to carry one too (#8, #35)."""
    _emu, state, _memory = town(map_id=14)
    legs = legs_to(state, "pewter_pokecenter", links=crossed_east_from_pewter().links)
    assert [(x.kind, x.direction, x.dest_map) for x in legs] == [
        ("edge", "west", maps.PEWTER_CITY),
        ("warp", None, maps.PEWTER_POKECENTER),
    ]


def test_a_milestone_is_offered_from_an_unmapped_map_once_the_way_back_is_known():
    """The `map_` guard existed because an unmapped node could never route. It can now, and #53
    is what makes dropping the guard safe: a milestone that still cannot be routed has no legs
    and no macro, so it is not offered at all."""
    emu, state, memory = town(map_id=14)
    milestone = milestone_stub(dest="pewter_gym", after=None)
    assert not any(o.kind == "milestone" for o in generate(emu, state, Memory.empty(), milestone))
    opts = generate(emu, state, crossed_east_from_pewter(), milestone)
    assert opts[0].kind == "milestone" and opts[0].legs


def test_a_heal_trip_can_be_planned_back_from_a_map_nobody_typed_in():
    """This is what the graph is for: a run that walked east can come home and heal instead of
    blacking out and losing the ground it took."""
    emu, state, memory = town(map_id=14)
    hurt_lead(emu)
    state = snapshot(emu)
    assert not any(o.kind == "heal" for o in generate(emu, state, Memory.empty(), None))
    heal = next(o for o in generate(emu, state, crossed_east_from_pewter(), None) if o.kind == "heal")
    assert heal.legs and heal.after == "heal"


def test_walking_a_warp_both_ways_keeps_one_link_with_a_destination_to_check():
    """Going in records `warp(dest)` and coming back out records `warp(WARP_LAST_MAP)` for the
    same pair of nodes. Both are true, but only the first carries a map id the navigator can
    check a crossing against, so the concrete one is the one kept (#8, #35)."""
    memory = Memory.empty()
    memory.note_crossing("map_15", "map_59", dest_map=59)  # walked in
    memory.note_crossing("map_59", "map_15", dest_map=15)  # and back out
    assert [(x.kind, x.dest_node, x.dest_map) for x in memory.links["map_15"]] == [("warp", "map_59", 59)]
    assert [(x.kind, x.dest_node, x.dest_map) for x in memory.links["map_59"]] == [("warp", "map_15", 15)]
