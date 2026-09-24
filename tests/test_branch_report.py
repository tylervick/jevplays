import importlib.util
from pathlib import Path

from jevplays.branch.store import BranchKey, BranchResult, BranchStore, DecisionInfo

SCRIPT = Path(__file__).resolve().parents[1] / "Scripts" / "branch-report.py"
spec = importlib.util.spec_from_file_location("branch_report", SCRIPT)
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)

SEEDS = 8


def measured(
    path: Path, decisions: dict[int, dict[str, int]], *, model="jev-1.13.0", seeds=SEEDS, kind="battle"
) -> BranchStore:
    """A store holding `decisions`: decision number -> alternative -> frames on every seed. The
    first alternative listed is Jev's choice."""
    store = BranchStore(path)
    store.set_meta("run", str(path))
    store.set_meta("model", model)
    store.set_meta("seeds", str(seeds))
    for n, frames in decisions.items():
        alts = list(frames)
        store.put_decision_info(DecisionInfo(n, kind, alts[0], alts, alts[0], None, 1000))
        for alt, f in frames.items():
            for seed in range(seeds):
                store.finish_branch(BranchKey(n, alt, seed), BranchResult("done", f + seed, 0, 1, 0))
    return store


def battle_line(out: str) -> str:
    return next(line for line in out.splitlines() if line.startswith("battle"))


ONE = {1: {"move:A": 600, "move:B": 300}}
TWO = {2: {"move:A": 300, "move:B": 900}}


def test_pooling_two_runs_scores_like_one_store_holding_both(tmp_path, capsys):
    a = measured(tmp_path / "a.sqlite", ONE)
    b = measured(tmp_path / "b.sqlite", TWO)
    both = measured(tmp_path / "both.sqlite", {**ONE, **TWO})
    assert report.summary([a, b]) == 0
    pooled = capsys.readouterr().out
    assert report.summary([both]) == 0
    single = capsys.readouterr().out
    assert battle_line(pooled) == battle_line(single)
    assert "pooled 2 runs" in pooled and "pooled" not in single


def test_runs_measured_with_a_different_model_or_seed_count_are_not_pooled(tmp_path, capsys):
    a = measured(tmp_path / "a.sqlite", ONE)
    other_model = measured(tmp_path / "m.sqlite", TWO, model="jev-2.0.0")
    other_seeds = measured(tmp_path / "k.sqlite", TWO, seeds=4)
    assert report.summary([a, other_model]) == 2
    assert "jev-2.0.0" in capsys.readouterr().err
    assert report.summary([a, other_seeds]) == 2
    assert "K" in capsys.readouterr().err


EXPLORE = {
    # chosen "explore:grass" is the best on all three
    1: {"explore:grass": 300, "explore:exit_north": 600},
    2: {"explore:grass": 300, "explore:door_41": 900},
    3: {"explore:grass": 300, "explore:npc_3": 900},
    # chosen "explore:npc_3" is the best
    4: {"explore:npc_3": 300, "explore:grass": 900},
    # chosen "explore:door_41" loses to "explore:grass"
    5: {"explore:door_41": 900, "explore:grass": 300},
}


def by_choice_lines(out: str) -> list[str]:
    lines = out.splitlines()
    start = lines.index("explore by choice:") + 1
    end = start
    while end < len(lines) and lines[end].startswith("  "):
        end += 1
    return lines[start:end]


def test_by_choice_prints_nothing_without_the_flag(tmp_path, capsys):
    store = measured(tmp_path / "a.sqlite", EXPLORE, kind="explore")
    assert report.summary([store]) == 0
    out = capsys.readouterr().out
    assert "by choice" not in out


def test_by_choice_prints_one_line_per_choice_kind_sorted_by_n_descending(tmp_path, capsys):
    store = measured(tmp_path / "a.sqlite", EXPLORE, kind="explore")
    assert report.summary([store], by_choice=True) == 0
    out = capsys.readouterr().out
    lines = by_choice_lines(out)
    kinds = [line.split()[0] for line in lines]
    # grass (n=3) sorts first; door and npc (n=1 each) are unordered between themselves
    assert kinds[0] == "grass"
    assert set(kinds[1:]) == {"door", "npc"}
    grass_line = next(line for line in lines if line.split()[0] == "grass")
    door_line = next(line for line in lines if line.split()[0] == "door")
    npc_line = next(line for line in lines if line.split()[0] == "npc")
    assert "n    3" in grass_line
    assert "n    1" in door_line
    assert "n    1" in npc_line
    # grass was chosen and was the best every time: zero regret, tied 100%
    assert "regret 0.0s" in grass_line
    assert "as good as best 100%" in grass_line
    # door lost to grass by 600 frames = 10s on every seed: no bootstrap interval with n=1
    assert "regret 10.0s" in door_line
    assert "as good as best 0%" in door_line


def test_by_choice_works_pooled_across_run_dirs(tmp_path, capsys):
    a = measured(tmp_path / "a.sqlite", {1: EXPLORE[1], 2: EXPLORE[2]}, kind="explore")
    b = measured(tmp_path / "b.sqlite", {3: EXPLORE[3], 4: EXPLORE[4], 5: EXPLORE[5]}, kind="explore")
    both = measured(tmp_path / "both.sqlite", EXPLORE, kind="explore")
    assert report.summary([a, b], by_choice=True) == 0
    pooled = by_choice_lines(capsys.readouterr().out)
    assert report.summary([both], by_choice=True) == 0
    single = by_choice_lines(capsys.readouterr().out)
    assert pooled == single
