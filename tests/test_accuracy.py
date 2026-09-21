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


def test_calibration_pairs_only_outcomes_whose_decision_is_still_in_the_log():
    """A resume rolls decisions back into decisions.orphaned.jsonl but leaves outcomes.jsonl
    alone, so the join is what keeps a rolled-back prediction out of the score."""
    decisions = [decision("EMBER", ["Grass"])]
    outcomes = [
        {"decision_id": "d-EMBER", "question": "faint", "predicted": 0.8, "observed": True},
        {"decision_id": "rolled-back", "question": "faint", "predicted": 0.1, "observed": False},
    ]
    assert accuracy_mod.pairs(decisions, outcomes) == [(0.8, True)]


def test_main_reports_both_numbers_from_one_run_dir(tmp_path, capsys):
    from jevplays.brain.decision import BattleAction, Decision
    from jevplays.runlog import RunDir

    run = RunDir.create(tmp_path / "runs", rom=None, flags={})
    d = decision("EMBER", ["Grass"])
    run.append(
        Decision(
            id=d["id"],
            ts=1.0,
            kind="battle",
            state_summary=d["state_summary"],
            questions={},
            answers=d["answers"],
            action="use EMBER",
            action_value=BattleAction(kind="move", move="EMBER"),
        )
    )
    run.append_outcome(
        {"decision_id": d["id"], "question": "faint", "predicted": 1.0, "observed": True, "ts": 2.0}
    )
    assert accuracy_mod.main([str(run.path)]) == 0
    out = capsys.readouterr().out
    assert "moves judged: 1, matched the best type: 1 (100%)" in out
    assert "faint predictions resolved: 1" in out
    assert "Brier 0.000" in out


def test_main_says_so_when_no_prediction_was_ever_resolved(tmp_path, capsys):
    from jevplays.runlog import RunDir

    run = RunDir.create(tmp_path / "runs", rom=None, flags={})
    assert accuracy_mod.main([str(run.path)]) == 0
    assert "no faint predictions resolved" in capsys.readouterr().out
