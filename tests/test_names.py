from jevplays.state.names import map_name


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
