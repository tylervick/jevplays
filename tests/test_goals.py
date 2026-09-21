from jevplays.executor.goals import (  # noqa: F401
    GOALS,
    available_goals,
    battle_goal,
    goal_by_id,
    legs_to,
)
from jevplays.executor.maps import OAKS_LAB, PALLET_TOWN, ROUTE_1, VIRIDIAN_CITY
from jevplays.state.snapshot import BagItem, Mon, Sprite
from tests.support import OVERWORLD_LEAD as CHAR
from tests.support import overworld_state as state


def test_fresh_game_offers_only_the_starter_and_the_always_goals():
    ids = [g.id for g in available_goals(state(party=()))]
    assert ids[0] == "get_starter" and "deliver_parcel" not in ids


def test_after_the_starter_the_parcel_is_next_and_goes_to_the_mart_first():
    s = state(flags={"got_starter"})
    ids = [g.id for g in available_goals(s)]
    assert "deliver_parcel" in ids and "get_starter" not in ids
    legs = goal_by_id("deliver_parcel").legs(s)
    assert legs[-1].kind == "warp" and legs[-1].dest_map == 42


def test_with_the_parcel_in_hand_the_goal_returns_to_oak():
    s = state(
        map_id=VIRIDIAN_CITY,
        x=29,
        y=20,
        flags={"got_starter", "got_oaks_parcel"},
        bag=(BagItem("OAKS PARCEL", 1),),
    )
    legs = goal_by_id("deliver_parcel").legs(s)
    assert legs[-1].dest_map == OAKS_LAB and goal_by_id("deliver_parcel").after == "talk_oak"


def test_old_man_goal_needs_the_sprite_and_the_delivered_parcel():
    s = state(
        map_id=VIRIDIAN_CITY,
        x=29,
        y=20,
        flags={"got_starter", "got_pokedex", "oak_got_parcel"},
        sprites=(Sprite(5, 72, 18, 9),),
    )
    assert "wake_old_man" in [g.id for g in available_goals(s)]
    assert goal_by_id("wake_old_man").done(state(map_id=VIRIDIAN_CITY, flags={"oak_got_parcel"}, sprites=()))


def test_buying_and_training_gates():
    rich = state(flags={"got_starter", "got_pokedex"}, money=3000)
    assert "buy_pokeballs" in [g.id for g in available_goals(rich)]
    stocked = state(flags={"got_starter", "got_pokedex"}, bag=(BagItem("POKE BALL", 5),))
    assert "buy_pokeballs" not in [g.id for g in available_goals(stocked)]
    assert "train_to_level_12" in [g.id for g in available_goals(stocked)]
    strong = state(flags={"got_starter", "got_pokedex"}, party=(Mon(**{**CHAR.__dict__, "level": 12}),))
    assert "train_to_level_12" not in [g.id for g in available_goals(strong)]
    assert "cross_viridian_forest" in [g.id for g in available_goals(strong)]


def test_heal_goal_appears_when_the_lead_is_hurt_and_routes_to_a_center():
    hurt = state(
        map_id=ROUTE_1, x=10, y=20, party=(Mon(**{**CHAR.__dict__, "hp": 5}),), flags={"got_starter"}
    )
    goal = next(g for g in available_goals(hurt) if g.id == "heal_at_center")
    legs = goal.legs(hurt)
    assert legs[-1].dest_map == 41 and goal.after == "heal"


def test_legs_to_builds_edge_and_warp_legs_from_the_route():
    legs = legs_to(state(map_id=PALLET_TOWN, x=5, y=6), "viridian_mart")
    assert [leg.kind for leg in legs] == ["edge", "edge", "warp"]
    assert legs[0].direction == "north" and legs[-1].dest_map == 42


def test_the_old_man_is_only_done_while_standing_in_viridian_city():
    """His sprite is simply not loaded anywhere else, which would otherwise read as "done"."""
    away = state(map_id=ROUTE_1, flags={"oak_got_parcel"}, sprites=())
    assert not goal_by_id("wake_old_man").done(away)


def test_battle_goal_is_the_active_goal_plus_the_standing_clause():
    """What Jev is told a battle is for. The overworld goal it picked changes under it, so the
    battle question follows that goal rather than a string fixed for the whole run."""
    goal = goal_by_id("train_to_level_12")
    assert battle_goal(goal, fallback="Win every battle and explore") == (
        "Train on Route 2 until CHARMANDER reaches level 12. Build a party of three and keep them healthy."
    )


def test_battle_goal_falls_back_to_the_flag_when_no_goal_is_active():
    assert battle_goal(None, fallback="Win every battle and explore") == "Win every battle and explore"


def test_potions_are_bought_in_pewter_and_only_there():
    """The Viridian Mart's stock, read off the ROM, is Poké Balls, Antidote, Parlyz Heal and Burn
    Heal -- no Potion (#27). Pewter is where the goal goes, and it is not offered from the far
    side of the forest: nobody should walk back for it."""
    from jevplays.executor.maps import PEWTER_CITY, ROUTE_1

    in_pewter = state(map_id=PEWTER_CITY, x=16, y=17, flags={"got_starter", "got_pokedex"}, money=3000)
    assert "buy_potions" in [g.id for g in available_goals(in_pewter)]
    on_route_1 = state(map_id=ROUTE_1, flags={"got_starter", "got_pokedex"}, money=3000)
    assert "buy_potions" not in [g.id for g in available_goals(on_route_1)]


def test_the_potion_goal_is_done_once_the_bag_has_them_or_the_money_is_gone():
    from jevplays.executor.maps import PEWTER_CITY

    stocked = state(
        map_id=PEWTER_CITY, x=16, y=17, flags={"got_starter", "got_pokedex"}, bag=(BagItem("POTION", 2),)
    )
    assert goal_by_id("buy_potions").done(stocked)
    assert "buy_potions" not in [g.id for g in available_goals(stocked)]
    broke = state(map_id=PEWTER_CITY, x=16, y=17, flags={"got_starter", "got_pokedex"}, money=100)
    assert goal_by_id("buy_potions").done(broke)
