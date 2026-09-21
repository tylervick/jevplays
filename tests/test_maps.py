from jevplays.executor.maps import LINKS, MAP_IDS, NODE_NAMES, ROUTE_2, VIRIDIAN_CITY, node_of, route


def test_node_of_splits_route_2_by_row():
    assert node_of(ROUTE_2, 8, 71) == "route_2_south" and node_of(ROUTE_2, 3, 11) == "route_2_north"
    assert node_of(VIRIDIAN_CITY, 20, 34) == "viridian_city"


def test_route_from_bedroom_to_the_gym_goes_through_the_forest():
    legs = route("reds_house_2f", "pewter_gym")
    nodes = [link.dest_node for link in legs]
    assert nodes == [
        "reds_house_1f",
        "pallet_town",
        "route_1",
        "viridian_city",
        "route_2_south",
        "viridian_forest_south_gate",
        "viridian_forest",
        "viridian_forest_north_gate",
        "route_2_north",
        "pewter_city",
        "pewter_gym",
    ]


def test_every_link_destination_is_a_known_node():
    for node, links in LINKS.items():
        for link in links:
            assert link.dest_node in LINKS, (node, link)


def test_map_ids_reverse_node_names_and_cover_both_halves_of_route_2():
    """The map id an edge leg lands on, per destination node. Route 2's two nodes are halves of
    one map, so both name the same id; every other node is the plain reverse of NODE_NAMES."""
    assert MAP_IDS["route_2_south"] == MAP_IDS["route_2_north"] == ROUTE_2
    assert all(MAP_IDS[name] == map_id for map_id, name in NODE_NAMES.items())
    assert set(LINKS) <= set(MAP_IDS)
