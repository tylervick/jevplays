from jevplays.state.types import TYPE_CHART, best_moves, effectiveness


def test_chart_has_the_82_gen1_rows_and_the_famous_ones():
    assert len(TYPE_CHART) == 82
    assert effectiveness("Fire", ["Grass"]) == 2.0
    assert effectiveness("Water", ["Fire"]) == 2.0
    assert effectiveness("Ground", ["Flying"]) == 0.0
    assert effectiveness("Normal", ["Ghost"]) == 0.0
    assert effectiveness("Fire", ["Rock"]) == 0.5
    assert effectiveness("Fighting", ["Rock"]) == 2.0
    assert effectiveness("Normal", ["Normal"]) == 1.0


def test_dual_types_multiply():
    assert effectiveness("Electric", ["Rock", "Ground"]) == 0.0
    assert effectiveness("Water", ["Rock", "Ground"]) == 4.0
    assert effectiveness("Fire", ["Bug", "Grass"]) == 4.0


def test_best_moves_prefers_effectiveness_then_stab_and_ignores_status_moves():
    moves = [
        {"name": "EMBER", "type": "Fire", "kind": "attack"},
        {"name": "SCRATCH", "type": "Normal", "kind": "attack"},
        {"name": "GROWL", "type": "Normal", "kind": "status"},
    ]
    assert best_moves(moves, ["Grass"], attacker_types=["Fire"]) == {"EMBER"}
    assert best_moves(moves, ["Rock", "Ground"], attacker_types=["Fire"]) == {"EMBER"}
    assert best_moves(moves, ["Normal"], attacker_types=["Normal"]) == {"SCRATCH"}
    assert best_moves([{"name": "GROWL", "type": "Normal", "kind": "status"}], ["Normal"]) == set()
