import argparse
import contextlib
import importlib.util
import json
from pathlib import Path

import pytest

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


class FakeProc:
    """A run process the supervisor can poll. `polls` are what poll() answers in turn, the last
    repeating: None is still running, an int is the exit code."""

    def __init__(self, *polls):
        self.polls = list(polls) or [None]

    def poll(self):
        return self.polls.pop(0) if len(self.polls) > 1 else self.polls[0]


def demo_args(runs_dir: Path) -> argparse.Namespace:
    return argparse.Namespace(
        state=None,
        host="127.0.0.1",
        port=8765,
        runs_dir=runs_dir,
        speed=3.0,
        stall_after=300.0,
        daily_decisions=3000,
        pause_after=60.0,
        max_viewers=20,
    )


class Harness:
    """`supervise` with the process, the clock and the page replaced. Starting a run once the
    scripted processes have run out raises Shutdown, as a SIGTERM would, so every test ends."""

    def __init__(self, tmp_path: Path, monkeypatch, procs):
        rom = tmp_path / "rom.gb"
        rom.write_bytes(b"not a real rom")
        monkeypatch.setenv("JEVPLAYS_ROM", str(rom))
        monkeypatch.delenv("NTFY_URL", raising=False)
        monkeypatch.setattr(demo_loop.shutil, "which", lambda _: "/usr/bin/uv")
        self.runs_dir = tmp_path / "runs"
        self.procs = list(procs)
        self.started: list[Path | None] = []
        self.stopped: list[FakeProc] = []
        self.said: list[str] = []

    def start(self, args, *, max_decisions, resume=None):
        self.started.append(resume)
        if not self.procs:
            raise demo_loop.Shutdown
        return self.procs.pop(0)

    def stop(self, proc):
        self.stopped.append(proc)

    def supervise(self, *, sleep=lambda s: None, health=lambda host, port: None) -> int:
        return demo_loop.supervise(
            demo_args(self.runs_dir),
            start_run=self.start,
            stop_run=self.stop,
            sleep=sleep,
            health=health,
            say=self.said.append,
        )


def make_interrupted(root: Path, name: str, *, checkpoint: bool = True, marker: bool = True) -> Path:
    run = make_run(root, name, 30)
    if checkpoint:
        (run / "checkpoint-25.state").write_bytes(b"")
    if marker:
        (run / demo_loop.INTERRUPTED).write_text("")
    return run


def test_the_newest_run_a_sigterm_stopped_is_the_one_to_resume(tmp_path):
    make_interrupted(tmp_path, "20260101-000000")
    newest = make_interrupted(tmp_path, "20260101-010000")
    assert demo_loop.resumable(tmp_path) == newest


def test_a_run_that_ended_any_other_way_starts_over(tmp_path):
    """Finished at the badge, died, or killed as stalled: none was marked, and resuming a hang or
    a crash from the checkpoint before it would likely repeat it."""
    make_interrupted(tmp_path, "20260101-000000", marker=False)
    assert demo_loop.resumable(tmp_path) is None
    assert demo_loop.resumable(tmp_path / "missing") is None


def test_a_marked_run_with_no_checkpoint_starts_over(tmp_path):
    """A `kill -9` after the marker leaves nothing for --resume, which would refuse the directory."""
    make_interrupted(tmp_path, "20260101-000000", checkpoint=False)
    assert demo_loop.resumable(tmp_path) is None


def test_only_the_newest_run_is_considered(tmp_path):
    make_interrupted(tmp_path, "20260101-000000")
    make_run(tmp_path, "20260101-010000", 3)
    assert demo_loop.resumable(tmp_path) is None


def test_the_resume_command_continues_the_run_instead_of_starting_one(tmp_path):
    args = demo_args(tmp_path)
    args.state = "states/route1.state"
    cmd = demo_loop.command(args, max_decisions=9, resume=tmp_path / "20260101-000000")
    assert cmd[cmd.index("--resume") + 1] == str(tmp_path / "20260101-000000")
    assert "--state" not in cmd  # the CLI refuses --state with --resume
    assert cmd[cmd.index("--max-decisions") + 1] == "9"


def test_sigterm_stops_the_run_marks_it_and_exits_cleanly(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch, [FakeProc(None)])

    def sleep(_):
        make_run(h.runs_dir, "20260101-000000", 4)  # the run has made its directory by now
        raise demo_loop.Shutdown

    assert h.supervise(sleep=sleep) == 0
    assert len(h.stopped) == 1
    assert (h.runs_dir / "20260101-000000" / demo_loop.INTERRUPTED).is_file()


def test_sigterm_between_runs_stops_nothing_and_marks_nothing(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch, [FakeProc(0)])  # one run that ends; the next start is the SIGTERM
    make_run(h.runs_dir, "20260101-000000", 4)
    assert h.supervise() == 0
    assert h.stopped == []
    assert not list(h.runs_dir.rglob(demo_loop.INTERRUPTED))


def test_sigterm_before_the_new_run_has_a_directory_leaves_the_previous_run_alone(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch, [FakeProc(None)])
    old = make_run(h.runs_dir, "20260101-000000", 4)  # the last run, which ended at the badge

    def sleep(_):
        raise demo_loop.Shutdown  # the new run has not written its run.json yet

    assert h.supervise(sleep=sleep) == 0
    assert len(h.stopped) == 1
    assert not (old / demo_loop.INTERRUPTED).exists()


def test_the_first_run_after_a_restart_resumes_and_only_the_first(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch, [FakeProc(0), FakeProc(0)])
    run = make_interrupted(h.runs_dir, "20260101-000000")
    assert h.supervise() == 0
    assert h.started == [run, None, None]
    # Resumed once: if the resumed run now crashes, the next restart does not resume it again.
    assert not (run / demo_loop.INTERRUPTED).exists()


def test_sigterm_during_a_resumed_run_marks_that_run_again(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch, [FakeProc(None)])
    run = make_interrupted(h.runs_dir, "20260101-000000")

    def sleep(_):
        raise demo_loop.Shutdown

    assert h.supervise(sleep=sleep) == 0
    assert h.started == [run]
    assert (run / demo_loop.INTERRUPTED).is_file()


def test_a_demo_whose_runs_keep_dying_at_once_exits_so_fly_restarts_the_machine(tmp_path, monkeypatch):
    """Fly restarts a Machine only when its main process exits; a failing health check alone just
    takes it out of routing. Backing off forever would leave the demo down and the Machine up."""
    h = Harness(tmp_path, monkeypatch, [FakeProc(1) for _ in range(10)])
    assert h.supervise() == 1
    assert len(h.started) == demo_loop.CRASH_LOOP_AFTER


def test_a_missing_rom_is_waited_for_so_the_machine_stays_up_for_the_upload(tmp_path, monkeypatch, capsys):
    """The upload is `fly ssh sftp put`, which needs a running Machine. Exiting instead would have
    Fly restart it until it gave up and stopped it."""
    h = Harness(tmp_path, monkeypatch, [])
    rom = tmp_path / "data" / "pokemon-red.gb"
    monkeypatch.setenv("JEVPLAYS_ROM", str(rom))
    slept = []

    def sleep(s):
        slept.append(s)
        if len(slept) == 3:
            rom.parent.mkdir(parents=True)
            rom.write_bytes(b"uploaded")

    assert h.supervise(sleep=sleep) == 0  # the ROM arrives, the first run starts, then SIGTERM
    assert slept[:3] == [demo_loop.ROM_POLL_S] * 3
    assert h.started == [None]
    out = capsys.readouterr().out
    assert out.count("fly ssh sftp put") == 1  # said once, not every 30 seconds
    assert str(rom) in out


def test_sigterm_while_waiting_for_the_rom_exits_cleanly(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch, [])
    monkeypatch.setenv("JEVPLAYS_ROM", str(tmp_path / "nowhere.gb"))

    def sleep(_):
        raise demo_loop.Shutdown

    assert h.supervise(sleep=sleep) == 0
    assert h.started == []


def test_notify_posts_the_message_to_ntfy_with_the_token():
    sent = []

    def urlopen(request, timeout):
        sent.append(request)
        return contextlib.nullcontext()

    env = {"NTFY_URL": "https://ntfy.example/demo", "NTFY_TOKEN": "tk"}
    assert demo_loop.notify("hello", env=env, urlopen=urlopen) is True
    [request] = sent
    assert request.full_url == "https://ntfy.example/demo"
    assert request.data == b"hello" and request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer tk"


def test_notify_without_a_url_does_nothing_so_a_laptop_demo_is_unchanged():
    def urlopen(request, timeout):
        pytest.fail("posted without NTFY_URL")

    assert demo_loop.notify("hello", env={}, urlopen=urlopen) is False


def test_a_failed_post_never_stops_the_demo(capsys):
    def urlopen(request, timeout):
        raise OSError("connection refused")

    assert demo_loop.notify("hello", env={"NTFY_URL": "https://ntfy.example/demo"}, urlopen=urlopen) is False
    assert "ntfy post failed" in capsys.readouterr().err


def test_the_supervisor_says_when_it_starts_and_whether_it_resumed(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch, [])
    run = make_interrupted(h.runs_dir, "20260101-000000")
    h.supervise()
    assert h.said == [f"demo started, resuming run {run.name}"]


def test_a_fresh_start_says_so(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch, [])
    h.supervise()
    assert h.said == ["demo started, new run"]


def test_a_missing_rom_is_announced_once(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch, [])
    rom = tmp_path / "nowhere.gb"
    monkeypatch.setenv("JEVPLAYS_ROM", str(rom))
    slept = []

    def sleep(_):
        slept.append(1)
        if len(slept) == 2:
            rom.write_bytes(b"uploaded")

    h.supervise(sleep=sleep)
    assert h.said[0] == demo_loop.missing_rom_message(str(rom))
    assert h.said.count(demo_loop.missing_rom_message(str(rom))) == 1


def test_a_run_killed_as_stalled_is_announced(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch, [FakeProc(None)])
    monkeypatch.setattr(demo_loop, "stalled", lambda **_: True)
    h.supervise()
    assert "run 1 made no decision for 300s; restarting it" in h.said
    assert len(h.stopped) == 1


def test_a_spent_budget_is_announced_once_per_run(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch, [FakeProc(None, None, None, 0)])
    h.supervise(health=lambda host, port: "resting")
    assert [m for m in h.said if "budget" in m] == [
        "daily budget of 3000 decisions spent; resting until 00:00 UTC"
    ]


def test_a_new_day_is_announced(tmp_path, monkeypatch):
    from datetime import date

    days = iter([date(2026, 9, 24)] + [date(2026, 9, 25)] * 20)
    monkeypatch.setattr(demo_loop, "utc_today", lambda: next(days))
    h = Harness(tmp_path, monkeypatch, [FakeProc(None)])
    h.supervise(health=lambda host, port: "resting")
    assert "new UTC day; starting a run with today's budget" in h.said


def test_a_crash_loop_is_announced_before_the_exit(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch, [FakeProc(1) for _ in range(10)])
    assert h.supervise() == 1
    assert h.said[-1] == "5 runs in a row died within 30s; exiting so the machine restarts"


def test_the_default_announcer_is_notify():
    import inspect

    assert inspect.signature(demo_loop.supervise).parameters["say"].default is demo_loop.notify
