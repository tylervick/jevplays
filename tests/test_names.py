from jevplays.state.names import (
    MoveData,
    item_name,
    map_name,
    move_data,
    species_name,
    trainer_class_name,
    type_name,
)


def test_known_maps_have_display_names():
    assert map_name(0) == "Pallet Town"
    assert map_name(38) == "Red's House 2F"
    assert map_name(40) == "Oak's Lab"
    assert map_name(51) == "Viridian Forest"


def test_routes_are_derived_from_their_id():
    assert map_name(12) == "Route 1"
    assert map_name(36) == "Route 25"


def test_unknown_map_falls_back_to_its_number():
    assert map_name(200) == "Map 200"


def test_species_use_internal_ids():
    assert species_name(176) == "CHARMANDER"
    assert species_name(177) == "SQUIRTLE"
    assert species_name(165) == "RATTATA"
    assert species_name(0) == "Species 0"


def test_move_data_carries_type_power_and_pp():
    assert move_data(10) == MoveData(name="SCRATCH", type="Normal", power=40, pp=35)
    assert move_data(45) == MoveData(name="GROWL", type="Normal", power=0, pp=40)
    assert move_data(52).type == "Fire"
    assert move_data(0) is None


def test_type_item_and_trainer_names():
    assert type_name(20) == "Fire" and type_name(0) == "Normal" and type_name(9) == "Type 9"
    assert item_name(4) == "POKE BALL" and item_name(200) == "Item 200"
    assert trainer_class_name(25) == "RIVAL1" and trainer_class_name(60) == "Trainer 60"


def test_every_move_type_is_a_known_type_name():
    from jevplays.state.names import MOVES, TYPES

    assert move_data(60).type == "Psychic"  # PSYBEAM; pokered spells the constant PSYCHIC_TYPE
    unknown = {m.type for m in MOVES.values()} - set(TYPES.values())
    assert unknown == set()
