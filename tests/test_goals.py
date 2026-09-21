from jevplays.executor.goals import MILESTONES, active_milestone, battle_goal, legs_to
from jevplays.executor.maps import OAKS_LAB, PALLET_TOWN, PEWTER_GYM, VIRIDIAN_CITY
from jevplays.state.snapshot import BagItem
from tests.support import overworld_state as state


def milestone(goal_id: str):
    return next(m for m in MILESTONES if m.id == goal_id)


def test_legs_to_builds_edge_and_warp_legs_from_the_route():
    legs = legs_to(state(map_id=PALLET_TOWN, x=5, y=6), "viridian_mart")
    assert [leg.kind for leg in legs] == ["edge", "edge", "warp"]
    assert legs[0].direction == "north" and legs[-1].dest_map == 42


def test_battle_goal_is_the_active_milestone_plus_the_standing_clause():
    """What Jev is told a battle is for. The milestone it is working towards changes under it, so
    the battle question follows that milestone rather than a string fixed for the whole run."""
    assert battle_goal(milestone("beat_brock"), fallback="Win every battle and explore") == (
        "Challenge Brock at the Pewter Gym. Build a party of three and keep them healthy."
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
    done = state(flags={"got_starter", "got_pokedex", "beat_brock"})
    assert active_milestone(done) is None


def test_get_pokedex_legs_go_to_the_mart_before_the_parcel_and_the_lab_after():
    before = state(flags={"got_starter"})
    legs = milestone("get_pokedex").legs(before)
    assert legs[-1].kind == "warp" and legs[-1].dest_map == 42

    after = state(
        map_id=VIRIDIAN_CITY,
        x=29,
        y=20,
        flags={"got_starter", "got_oaks_parcel"},
        bag=(BagItem("OAKS PARCEL", 1),),
    )
    legs = milestone("get_pokedex").legs(after)
    assert legs[-1].dest_map == OAKS_LAB


def test_milestone_beat_brock_legs_end_at_the_gym_door():
    from_viridian = state(map_id=VIRIDIAN_CITY, x=29, y=20, flags={"got_starter", "got_pokedex"})
    legs = milestone("beat_brock").legs(from_viridian)
    assert legs[-1].kind == "walk" and legs[-1].target == (4, 2)

    in_gym = state(map_id=PEWTER_GYM, x=4, y=6, flags={"got_starter", "got_pokedex"})
    legs = milestone("beat_brock").legs(in_gym)
    assert len(legs) == 1 and legs[0].kind == "walk" and legs[0].target == (4, 2)
