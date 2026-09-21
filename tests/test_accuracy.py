import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "Scripts" / "accuracy.py"
spec = importlib.util.spec_from_file_location("accuracy", SCRIPT)
accuracy_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(accuracy_mod)


def decision(choice, enemy_types, ours_types=("Fire",)):
    return {
        "kind": "battle",
        "id": f"d-{choice}",
        "state_summary": {
            "our_pokemon": {
                "name": "CHARMANDER",
                "types": list(ours_types),
                "moves": [
                    {"name": "EMBER", "type": "Fire", "kind": "attack"},
                    {"name": "SCRATCH", "type": "Normal", "kind": "attack"},
                    {"name": "GROWL", "type": "Normal", "kind": "status"},
                ],
            },
            "enemy_pokemon": {"name": "X", "types": list(enemy_types)},
        },
        "answers": {"move": {"primitive": "choice", "choice": choice}},
    }


def test_accuracy_counts_matches_against_the_best_typed_move():
    log = [
        decision("EMBER", ["Grass"]),  # ok
        decision("SCRATCH", ["Grass"]),  # miss
        # Rock resists both; STAB keeps Ember (0.75) ahead of Scratch (0.5), so Scratch is a miss.
        # Without STAB the two would tie and this row would wrongly read ok: this is the row that
        # proves the script passes the attacker's types through.
        decision("SCRATCH", ["Rock", "Ground"]),  # miss
        {"kind": "goal", "id": "g", "state_summary": {}, "answers": {}},  # ignored
    ]
    judged, matched, rows = accuracy_mod.accuracy(log)
    assert (judged, matched) == (3, 1)
    assert [r["ok"] for r in rows] == [True, False, False]


def test_main_rejects_a_directory_without_a_run(tmp_path, capsys):
    assert accuracy_mod.main([str(tmp_path)]) == 2
    assert "run.json" in capsys.readouterr().err
