import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "Scripts" / "demo-loop.py"
spec = importlib.util.spec_from_file_location("demo_loop", SCRIPT)
demo_loop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo_loop)


def make_run(root: Path, name: str, decisions: int) -> Path:
    run = root / name
    run.mkdir(parents=True)
    (run / "run.json").write_text("{}")
    (run / "decisions.jsonl").write_text("".join(json.dumps({"i": i}) + "\n" for i in range(decisions)))
    return run


def test_progress_is_the_newest_run_directorys_decision_count(tmp_path):
    """The supervisor watches the run the way a viewer would: is it still making decisions? It
    reads the newest run directory, because every restart begins a new one."""
    make_run(tmp_path, "20260101-000000", 3)
    make_run(tmp_path, "20260101-010000", 7)
    assert demo_loop.progress(tmp_path) == 7


def test_progress_of_a_runs_directory_with_nothing_in_it_is_zero(tmp_path):
    assert demo_loop.progress(tmp_path) == 0
    (tmp_path / "half-made").mkdir()
    assert demo_loop.progress(tmp_path) == 0  # no run.json yet: not a run directory


def test_a_run_that_has_stopped_deciding_for_longer_than_the_budget_is_stalled():
    """#67: a run can sit in BATTLE_WAIT making no decisions while the process stays up and the
    log looks finished. Nothing in the run notices, so the supervisor has to."""
    assert demo_loop.stalled(idle_for=301, stall_after=300) is True
    assert demo_loop.stalled(idle_for=299, stall_after=300) is False


def test_the_backoff_grows_then_settles(tmp_path):
    """A run that dies instantly and repeatedly should not be restarted in a tight loop, but a
    demo should not take minutes to come back either."""
    assert demo_loop.backoff(0) == 2
    assert demo_loop.backoff(1) == 4
    assert demo_loop.backoff(5) >= demo_loop.backoff(4)
    assert demo_loop.backoff(50) == demo_loop.MAX_BACKOFF_S
