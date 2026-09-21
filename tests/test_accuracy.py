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


def explore_decision(id_, map_name, options, choice=None, fallback_reason="", action=""):
    answers = {"explore": {"primitive": "choice", "choice": choice}} if choice is not None else {}
    return {
        "kind": "explore",
        "id": id_,
        "state_summary": {"map": map_name, "options": options},
        "answers": answers,
        "fallback_reason": fallback_reason,
        "action": action,
    }


def test_exploration_summarises_decisions_by_kind_and_explore_picks_by_option_kind():
    log = [
        explore_decision(
            "e-door",
            "VIRIDIAN_CITY",
            {"door_41": "enter the Center (new)", "npc_3": "talk to the nurse (new)"},
            choice="door_41",
            action="explore: enter the Center",
        ),  # a plain, on-list choice
        explore_decision(
            "e-npc",
            "VIRIDIAN_CITY",
            {"npc_3": "talk to the nurse (new)", "grass": "train in the grass (new)"},
            choice="nonsense",
            fallback_reason="'nonsense' is not offered; using npc_3 instead",
            action="explore: talk to the nurse",
        ),  # an off-list choice: the recorded answer is what Jev said, npc_3 is what ran
        explore_decision(
            "e-milestone",
            "ROUTE_1",
            {"milestone": "go to Pewter (new)"},
            fallback_reason="no usable explore answer; using milestone instead",
            action="explore: go to Pewter",
        ),  # no explore answer at all: the fallback text is the only source
        decision("EMBER", ["Grass"]),
        decision("SCRATCH", ["Grass"]),
        {"kind": "prompt", "id": "p-1", "state_summary": {}, "answers": {}},
    ]
    summary = accuracy_mod.exploration(log)
    assert summary["by_kind"] == {"battle": 2, "explore": 3, "prompt": 1, "menu": 0}
    assert summary["explore_by_option_kind"] == {
        "exit": 0,
        "door": 1,
        "npc": 1,
        "grass": 0,
        "milestone": 1,
        "heal": 0,
    }
    assert summary["milestone_share"] == 1 / 3
    assert summary["maps_seen"] == 2
    assert summary["total"] == 6


def test_main_prints_zero_exploration_summary_when_the_run_has_no_explore_decisions(tmp_path, capsys):
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
    assert accuracy_mod.main([str(run.path)]) == 0
    out = capsys.readouterr().out
    assert "decisions: 1 (battle 1, explore 0, prompt 0, menu 0)" in out
    assert "explore picks: exit 0, door 0, npc 0, grass 0, milestone 0, heal 0" in out
    assert "milestone share: 0%" in out
    assert "maps seen: 0" in out


def test_a_heal_first_override_counts_as_heal_not_as_what_jev_said():
    """`needs_heal` can override a valid explore choice without marking a fallback, so the
    executed option must come from the action text, never from the recorded choice."""
    log = [
        explore_decision(
            "e-heal",
            "VIRIDIAN_CITY",
            {"exit_north": "go north to Route 2 (new)", "heal": "go heal at Viridian Pokémon Center (new)"},
            choice="exit_north",
            action="explore: go heal at Viridian Pokémon Center",
        )
    ]
    summary = accuracy_mod.exploration(log)
    assert summary["explore_by_option_kind"]["heal"] == 1
    assert summary["explore_by_option_kind"]["exit"] == 0
