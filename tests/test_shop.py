"""The clerk's shopping list: what a Mart visit tries to buy, from the bag and the money."""

from jevplays.executor.shop import MAX_POKEBALLS, MAX_POTIONS, POKEBALL_PRICE, POTION_PRICE, shopping_list
from jevplays.state.snapshot import BagItem
from tests.support import overworld_state as state


def test_an_empty_bag_with_money_wants_balls_then_potions():
    assert shopping_list(state(money=5000, bag=())) == [("POKE BALL", MAX_POKEBALLS), ("POTION", MAX_POTIONS)]


def test_a_stocked_bag_wants_nothing():
    full = (BagItem("POKE BALL", MAX_POKEBALLS), BagItem("POTION", MAX_POTIONS))
    assert shopping_list(state(money=5000, bag=full)) == []


def test_balls_come_first_and_potions_get_what_money_is_left():
    money = 3 * POKEBALL_PRICE + 2 * POTION_PRICE + 50
    wants = shopping_list(state(money=money, bag=(BagItem("POKE BALL", MAX_POKEBALLS - 3),)))
    assert wants == [("POKE BALL", 3), ("POTION", 2)]


def test_no_money_means_no_list():
    assert shopping_list(state(money=150, bag=())) == []
