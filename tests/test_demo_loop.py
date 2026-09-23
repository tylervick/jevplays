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


def utc(y, mo, d, h=12) -> float:
    from datetime import UTC, datetime

    return datetime(y, mo, d, h, tzinfo=UTC).timestamp()


def make_run_at(root: Path, name: str, stamps: list[float]) -> Path:
    run = root / name
    run.mkdir(parents=True)
    (run / "run.json").write_text("{}")
    (run / "decisions.jsonl").write_text("".join(json.dumps({"ts": ts}) + "\n" for ts in stamps))
    return run


def test_the_days_decisions_are_counted_across_every_run_by_their_own_timestamps(tmp_path):
    """The daily ceiling is a budget for the day, not for one run: the demo restarts a run at
    the badge and after every stall. Counting from the logs on disk means a restarted supervisor
    picks up the same count, and a run that straddles midnight is split where its decisions fall."""
    from datetime import date

    make_run_at(tmp_path, "20260921-230000", [utc(2026, 9, 21, 23), utc(2026, 9, 22, 0), utc(2026, 9, 22, 1)])
    make_run_at(tmp_path, "20260922-020000", [utc(2026, 9, 22, 2)] * 4)
    (tmp_path / "half-made").mkdir()  # no run.json: not a run
    assert demo_loop.decisions_on(tmp_path, date(2026, 9, 22)) == 6
    assert demo_loop.decisions_on(tmp_path, date(2026, 9, 21)) == 1
    assert demo_loop.decisions_on(tmp_path / "missing", date(2026, 9, 22)) == 0


def test_a_torn_last_line_is_not_a_decision_and_does_not_stop_the_count(tmp_path):
    """A run killed mid-append can leave half a line; the count is a budget, not a parser test."""
    from datetime import date

    run = make_run_at(tmp_path, "20260922-020000", [utc(2026, 9, 22)] * 2)
    with (run / "decisions.jsonl").open("a") as f:
        f.write('{"ts": 17')
    assert demo_loop.decisions_on(tmp_path, date(2026, 9, 22)) == 2


def test_pruning_drops_runs_last_written_over_two_days_ago_and_never_the_newest(tmp_path):
    """runs/ is save-state data growing ~50 MB a day. Two days keeps today's count honest (a run
    from yesterday may still hold decisions made after midnight) and recent runs for accuracy.py."""
    import os

    now = utc(2026, 9, 22)
    old = make_run_at(tmp_path, "20260919-120000", [])
    recent = make_run_at(tmp_path, "20260921-120000", [])
    for path, at in ((old, now - 3 * 86400), (recent, now - 1 * 86400)):
        for f in [path, *path.iterdir()]:
            os.utime(f, (at, at))
    stray = tmp_path / "notes"
    stray.mkdir()
    os.utime(stray, (now - 30 * 86400,) * 2)

    assert demo_loop.prune(tmp_path, now=now) == [old]
    assert not old.exists() and recent.exists() and stray.exists()  # only run directories go

    only = tmp_path / "only"
    make_run_at(only, "20260101-000000", [])
    lone = only / "20260101-000000"
    for f in [lone, *lone.iterdir()]:
        os.utime(f, (0, 0))
    assert demo_loop.prune(only, now=now) == []  # the newest run stays, however old


def test_a_run_waiting_on_purpose_is_not_stalled():
    """#67's watchdog kills a run that stops deciding. A run paused because nobody is watching,
    or resting on a spent budget, stops deciding on purpose and must be left alone -- and when it
    wakes, its quiet time is not held against it."""
    assert demo_loop.waiting_on_purpose("unwatched")
    assert demo_loop.waiting_on_purpose("resting")
    assert not demo_loop.waiting_on_purpose("running")
    assert not demo_loop.waiting_on_purpose("paused")  # the loop's own "stuck" pause is a stall
    assert not demo_loop.waiting_on_purpose(None)  # no answer from the page


def test_the_run_command_carries_the_demo_limits():
    import argparse

    args = argparse.Namespace(
        state="states/route1.state",
        host="0.0.0.0",
        port=8765,
        runs_dir=Path("runs/demo"),
        speed=6.0,
        pause_after=60.0,
        max_viewers=20,
    )
    cmd = demo_loop.command(args, max_decisions=37)
    flags = dict(zip(cmd[4::2], cmd[5::2], strict=False))
    assert cmd[:4] == ["uv", "run", "jevplays", "run"]
    assert flags["--max-decisions"] == "37"
    assert flags["--pause-after"] == "60.0"
    assert flags["--max-viewers"] == "20"
    assert flags["--speed"] == "6.0"


def test_with_no_state_the_run_starts_from_the_intro_so_viewers_see_jev_pick_the_starter():
    """#80. From a save on Route 1 the starter was already chosen; from the intro, Jev chooses it
    on screen. `--state` still starts somewhere else."""
    import argparse

    args = argparse.Namespace(
        state=None,
        host="0.0.0.0",
        port=8765,
        runs_dir=Path("runs/demo"),
        speed=3.0,
        pause_after=60.0,
        max_viewers=20,
    )
    assert "--state" not in demo_loop.command(args, max_decisions=5)
    args.state = "states/route1.state"
    cmd = demo_loop.command(args, max_decisions=5)
    assert cmd[cmd.index("--state") + 1] == "states/route1.state"
