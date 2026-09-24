import importlib.util
from pathlib import Path

from jevplays.branch.store import BranchKey, BranchResult, BranchStore, DecisionInfo

SCRIPT = Path(__file__).resolve().parents[1] / "Scripts" / "branch-report.py"
spec = importlib.util.spec_from_file_location("branch_report", SCRIPT)
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)

SEEDS = 8


def measured(
    path: Path, decisions: dict[int, dict[str, int]], *, model="jev-1.13.0", seeds=SEEDS
) -> BranchStore:
    """A store holding `decisions`: decision number -> alternative -> frames on every seed. The
    first alternative listed is Jev's choice."""
    store = BranchStore(path)
    store.set_meta("run", str(path))
    store.set_meta("model", model)
    store.set_meta("seeds", str(seeds))
    for n, frames in decisions.items():
        alts = list(frames)
        store.put_decision_info(DecisionInfo(n, "battle", alts[0], alts, alts[0], None, 1000))
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
