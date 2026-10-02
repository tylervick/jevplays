from dataclasses import replace

from jevplays.executor.goals import MILESTONES, active_milestone, battle_goal, legs_to
from jevplays.executor.maps import OAKS_LAB, PALLET_TOWN, PEWTER_GYM, ROUTE_1, VIRIDIAN_CITY
from jevplays.state.snapshot import BagItem
from tests.support import overworld_state as state


def milestone(goal_id: str):
    return next(m for m in MILESTONES if m.id == goal_id)


def test_legs_to_builds_edge_and_warp_legs_from_the_route():
    legs = legs_to(state(map_id=PALLET_TOWN, x=5, y=6), "viridian_mart")
    assert [leg.kind for leg in legs] == ["edge", "edge", "warp"]
    assert legs[0].direction == "north" and legs[-1].dest_map == 42
    # An edge leg names the map it comes out on too (maps.MAP_IDS), so the navigator can tell
    # the crossing from a blackout that dropped us somewhere else.
    assert legs[0].dest_map == ROUTE_1


def test_battle_goal_is_the_active_milestone_plus_the_standing_clause():
    """What Jev is told a battle is for. The milestone it is working towards changes under it, so
    the battle question follows that milestone rather than a string fixed for the whole run."""
    assert battle_goal(milestone("beat_brock"), fallback="Win every battle and explore") == (
        "Challenge Brock at the Pewter Gym and earn the Boulder Badge. "
        "Build a party of three and keep them healthy."
    )


def test_battle_goal_falls_back_to_the_flag_when_no_goal_is_active():
    assert battle_goal(None, fallback="Win every battle and explore") == "Win every battle and explore"


# --- Milestone 4b: the three-milestone spine ---


def test_milestones_are_the_spine_in_order():
    assert [m.id for m in MILESTONES] == ["get_starter", "get_pokedex", "beat_brock"]


def test_active_milestone_progresses_through_the_spine():
    assert active_milestone(state()).id == "get_starter"
    assert active_milestone(state(flags={"got_starter"})).id == "get_pokedex"
    assert active_milestone(state(flags={"got_starter", "got_pokedex"})).id == "beat_brock"
    # The flag alone is not done (#40): the badge bit is what ends the spine.
    done = replace(state(flags={"got_starter", "got_pokedex", "beat_brock"}), badges=1)
    assert active_milestone(done) is None


def test_get_pokedex_legs_go_to_the_mart_before_the_parcel_and_the_lab_after():
    before = state(flags={"got_starter"})
    legs = milestone("get_pokedex").legs(before, {})
    assert legs[-1].kind == "warp" and legs[-1].dest_map == 42

    after = state(
        map_id=VIRIDIAN_CITY,
        x=29,
        y=20,
        flags={"got_starter", "got_oaks_parcel"},
        bag=(BagItem("OAKS PARCEL", 1),),
    )
    legs = milestone("get_pokedex").legs(after, {})
    assert legs[-1].dest_map == OAKS_LAB


def test_milestone_beat_brock_legs_end_at_the_gym_door():
    from_viridian = state(map_id=VIRIDIAN_CITY, x=29, y=20, flags={"got_starter", "got_pokedex"})
    legs = milestone("beat_brock").legs(from_viridian, {})
    assert legs[-1].kind == "walk" and legs[-1].target == (4, 2)

    in_gym = state(map_id=PEWTER_GYM, x=4, y=6, flags={"got_starter", "got_pokedex"})
    legs = milestone("beat_brock").legs(in_gym, {})
    assert len(legs) == 1 and legs[0].kind == "walk" and legs[0].target == (4, 2)


def test_brock_is_only_beaten_once_the_badge_bit_is_set_not_when_the_flag_is():
    """Gen 1 sets `beat_brock` when the battle ends and the badge bit one dialog later (#40)."""
    brock = MILESTONES[2]
    mid_dialog = state(flags=("got_starter", "got_pokedex", "beat_brock"))
    assert brock.done(mid_dialog) is False and active_milestone(mid_dialog) is brock
    awarded = replace(mid_dialog, badges=1)
    assert brock.done(awarded) is True and active_milestone(awarded) is None


def test_the_brock_milestone_names_the_fight_it_walks_into():
    """Story fact, so it lives here beside the milestone rather than in the brain: Brock's Onix is
    level 14, and that is the number the readiness word is measured against (#42)."""
    brock = next(g for g in MILESTONES if g.id == "beat_brock")
    assert brock.expects_level == 14
    assert next(g for g in MILESTONES if g.id == "get_pokedex").expects_level is None


# --- Past Brock: Misty, opt-in with `until` ---

PAST_BROCK = ("got_starter", "got_pokedex", "beat_brock")


def test_the_story_goes_on_to_misty_after_the_default_spine():
    """`MILESTONES` stays the default spine (it ends at the Boulder Badge); the full story,
    which a run opts into with `--until`, carries on to the Cascade Badge."""
    from jevplays.executor.goals import ALL_MILESTONES

    assert [m.id for m in ALL_MILESTONES] == ["get_starter", "get_pokedex", "beat_brock", "beat_misty"]
    assert ALL_MILESTONES[:3] == MILESTONES
    misty = ALL_MILESTONES[3]
    assert misty.description == "Challenge Misty at the Cerulean Gym and earn the Cascade Badge"
    assert misty.after == "talk_leader" and misty.destination == "cerulean_gym"
    assert misty.expects_level == 21 and misty.badge == "Cascade Badge"
    assert milestone("beat_brock").badge == "Boulder Badge"
    assert milestone("get_pokedex").badge is None and milestone("get_pokedex").destination is None


def test_misty_is_available_with_one_badge_and_done_with_two():
    from jevplays.executor.goals import ALL_MILESTONES

    misty = ALL_MILESTONES[3]
    assert not misty.available(state(flags=PAST_BROCK))
    one = replace(state(flags=PAST_BROCK), badges=1)
    assert misty.available(one) and not misty.done(one)
    assert misty.done(replace(one, badges=2))


def test_active_milestone_stops_at_until():
    one = replace(state(flags=PAST_BROCK), badges=1)
    assert active_milestone(one) is None  # the default ends at the Boulder Badge, as before
    assert active_milestone(one, until="beat_brock") is None
    assert active_milestone(one, until="beat_misty").id == "beat_misty"
    assert active_milestone(replace(one, badges=2), until="beat_misty") is None
    # Earlier milestones come first whatever `until` names.
    assert active_milestone(state(), until="beat_misty").id == "get_starter"


def test_active_milestone_rejects_an_unknown_until():
    import pytest

    with pytest.raises(ValueError):
        active_milestone(state(), until="beat_giovanni")


def test_misty_legs_route_over_the_walked_graph_and_add_no_walk():
    """No links past Pewter are hand-written: with nothing walked there is no route, and with the
    crossings the run made it routes to the gym door and stops (`talk_leader` does the rest)."""
    from jevplays.executor.maps import CERULEAN_CITY, CERULEAN_GYM, PEWTER_CITY, edge, warp

    misty = milestone_by_any_id("beat_misty")
    one = replace(state(map_id=PEWTER_CITY, x=10, y=10, flags=PAST_BROCK), badges=1)
    assert misty.legs(one, {}) == []
    walked = {
        "pewter_city": [edge("east", "cerulean_city")],
        "cerulean_city": [warp(CERULEAN_GYM, "cerulean_gym")],
    }
    legs = misty.legs(one, walked)
    assert [(leg.kind, leg.dest_map) for leg in legs] == [("edge", CERULEAN_CITY), ("warp", CERULEAN_GYM)]
    in_gym = replace(one, map_id=CERULEAN_GYM)
    assert misty.legs(in_gym, walked) == []


def milestone_by_any_id(goal_id: str):
    from jevplays.executor.goals import ALL_MILESTONES

    return next(m for m in ALL_MILESTONES if m.id == goal_id)


def test_node_falls_back_to_the_map_level_name_for_a_state_with_no_place():
    """Test-built states carry no place; the goal tables must still route from them."""
    from dataclasses import replace

    from jevplays.executor.goals import node
    from tests.support import overworld_state

    state = overworld_state(map_id=1)
    assert state.place == "" and node(state) == "viridian_city"
    assert node(replace(state, place="map_60_p2")) == "map_60_p2"
