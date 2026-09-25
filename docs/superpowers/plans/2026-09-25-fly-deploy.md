# The Demo on Fly.io Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the public demo on one Fly.io Machine, deployed from `main`, resuming its run across
deploys, with ntfy alerts from inside the Machine and from a scheduled outside check.

**Architecture:** `Scripts/demo-loop.py` (the supervisor) stays the process that runs; it learns to
resume a run a SIGTERM cut short, to wait for a missing ROM, to exit on a crash loop so Fly restarts
it, and to post to ntfy. A `Dockerfile` and `fly.toml` package it with the ROM on a Fly volume,
never in the image. `ci.yml` gains an `image` job (build and smoke-check) and a gated `deploy` job;
`uptime.yml` polls `/health` on a schedule.

**Tech Stack:** Python 3.14 stdlib (`signal`, `urllib.request`), pytest, Docker (uv base image),
Fly.io (`fly.toml`, flyctl 0.4.107), GitHub Actions, bash + curl, ntfy.

**Spec:** `docs/superpowers/specs/2026-09-24-fly-deploy-design.md`. Read it first; this plan argues
from it.

## Global Constraints

- The ROM, save states, `.ram` files and `mise.local.toml` never enter git, the Docker build
  context, the image, or a registry. The ROM lives only at `/data/rom/pokemon-red.gb` on the Fly
  volume, uploaded by Tyler.
- Do not run `fly deploy`, `fly apps create`, `fly secrets set`, or set GitHub secrets/variables.
  Tyler does every account step (spec, "Rollout").
- No secret in the repo: `TYPESAFE_API_KEY`, `NTFY_URL`, `NTFY_TOKEN`, `FLY_API_TOKEN` live in
  `fly secrets` / GitHub secrets. On ntfy a topic name is a secret.
- Do not describe how the Mac mini's tunnel works anywhere in the repo.
- Without `NTFY_URL`, `mise run demo` on a laptop behaves exactly as before.
- Every GitHub Action is pinned to a commit SHA with the tag in a comment; `hk check --all`
  (actionlint, zizmor) must pass.
- Pinned values, already resolved on 2026-09-25:
  - base image `ghcr.io/astral-sh/uv:0.12.17-python3.14-trixie-slim@sha256:63018e7b676ef735eee4da4f9c2e7b5f5e3851fa023745d78ce91d1a099a35fd`
  - flyctl `0.4.107` (mise `aqua:superfly/flyctl`, and the action's `version:` input)
  - `superfly/flyctl-actions/setup-flyctl@fc53c09e1bc3be6f54706524e3b82c4f462f77be # 1.5`
- Demo settings on Fly: `--speed 3 --daily-decisions 3000`, `--runs-dir /data/runs`, port 8765,
  `shared-cpu-1x`, 1 GB, `auto_stop_machines = "off"`.
- `mise run check` passes before every commit; conventional commits (`feat(tooling):`,
  `docs:`); work lands on branch `tylervick/production` through a PR, never on `main`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **SIGTERM between runs** (during the backoff sleep): nothing is running, so nothing is stopped
   or marked, and the supervisor exits 0. Test in Task 1.
2. **SIGTERM before a new run has written its directory**: the previous run (which ended by
   itself) must not be marked and resumed. Test in Task 1.
3. **A resumed run that then crashes**: it must not be resumed again on every restart (the marker
   is deleted as it resumes). Test in Task 1.
4. **ntfy unreachable or refusing**: the demo keeps going; a failed post is printed, never raised.
   Test in Task 3.
5. **A marker with no checkpoint** (the run was `kill -9`ed before its exit checkpoint): start
   fresh rather than hand `--resume` a directory it will refuse. Test in Task 1.

## File Structure

- `Scripts/demo-loop.py` (modify): resume marker, SIGTERM shutdown, crash-loop exit, ROM wait,
  `notify()`. Tasks 1-3.
- `tests/test_demo_loop.py` (modify): the supervisor's tests. Tasks 1-3.
- `Dockerfile`, `.dockerignore`, `fly.toml` (create): the image and the Machine. Task 4.
- `tests/test_container.py` (create): static checks that game data cannot enter the image and
  that `fly.toml` and the `CMD` agree. Task 4.
- `mise.toml` (modify): pin flyctl. Task 4.
- `Scripts/ntfy.sh` (create): one ntfy post from a workflow. Task 5.
- `tests/test_ntfy_sh.py` (create). Task 5.
- `.github/workflows/ci.yml` (modify): `image` job (Task 4), `deploy` job (Task 5).
- `.github/workflows/uptime.yml` (create). Task 5.
- `README.md` (modify): "Production" section. Task 6.

---

### Task 1: The supervisor resumes a run a SIGTERM cut short

**Files:**
- Modify: `Scripts/demo-loop.py` (constants block near line 44; `progress` at 62; `command`/`start`
  at 134-161; `supervise` at 172-224)
- Test: `tests/test_demo_loop.py`

**Interfaces:**
- Produces (later tasks rely on these exact names):
  - `INTERRUPTED: str = "interrupted"` — marker file name inside a run directory.
  - `class Shutdown(Exception)` — raised by the SIGTERM handler.
  - `resumable(runs_dir: Path) -> Path | None`
  - `command(args, *, max_decisions: int, resume: Path | None = None) -> list[str]`
  - `start(args, *, max_decisions: int, resume: Path | None = None) -> subprocess.Popen`
  - `supervise(args, *, start_run=start, stop_run=stop, sleep=time.sleep, health=status, say=_quiet) -> int`
    where `say: Callable[[str], None]` is how events are announced (Task 3 swaps the default to
    `notify`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_demo_loop.py` (it already imports `json`, `Path`, and loads the script as
`demo_loop`, and defines `make_run(root, name, decisions)`):

```python
import argparse


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_demo_loop.py -q`
Expected: the new tests FAIL with `AttributeError: module 'demo_loop' has no attribute 'INTERRUPTED'`
(or `resumable`/`Shutdown`); the existing tests still pass.

- [ ] **Step 3: Implement**

In `Scripts/demo-loop.py`:

Add to the imports: `from collections.abc import Callable`.

After `WAITING_ON_PURPOSE`, add:

```python
INTERRUPTED = "interrupted"
"""Written into a run directory when a SIGTERM made the supervisor stop that run. Fly sends SIGTERM
before every deploy and every stop; the next supervisor resumes the run that holds this, once."""


class Shutdown(Exception):
    """SIGTERM arrived: the machine is being stopped or redeployed."""


def _shutdown(signum, frame) -> None:
    raise Shutdown


def _quiet(message: str) -> None:
    """What `supervise` announces events to when nobody asked to hear about them."""
```

Replace `progress`'s first four lines with a shared helper, and add `resumable` after it:

```python
def _newest(runs_dir: Path) -> Path | None:
    runs = _runs(runs_dir)
    return max(runs, key=lambda p: p.name) if runs else None


def progress(runs_dir: Path) -> int:
    """Decisions made by the newest run under `runs_dir`, or 0 when there is not one yet."""
    newest = _newest(runs_dir)
    if newest is None:
        return 0
    log = newest / "decisions.jsonl"
    if not log.is_file():
        return 0
    with log.open(encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def resumable(runs_dir: Path) -> Path | None:
    """The newest run, when a SIGTERM stopped it and it has a checkpoint to go on from. A run that
    finished, died, or was killed as stalled was never marked, and is replaced by a new one."""
    newest = _newest(runs_dir)
    if newest is None or not (newest / INTERRUPTED).is_file():
        return None
    return newest if any(newest.glob("checkpoint-*.state")) else None
```

Change `command` and `start` to take `resume`:

```python
def command(args, *, max_decisions: int, resume: Path | None = None) -> list[str]:
    cmd = [
        # ... the existing list, unchanged ...
    ]
    if resume is not None:
        cmd += ["--resume", str(resume)]
    elif args.state is not None:
        cmd += ["--state", args.state]
    if args.max_viewers is not None:
        cmd += ["--max-viewers", str(args.max_viewers)]
    return cmd


def start(args, *, max_decisions: int, resume: Path | None = None) -> subprocess.Popen:
    return subprocess.Popen(
        command(args, max_decisions=max_decisions, resume=resume), start_new_session=True
    )
```

Replace `supervise` with:

```python
def supervise(
    args,
    *,
    start_run=start,
    stop_run=stop,
    sleep: Callable[[float], None] = time.sleep,
    health=status,
    say: Callable[[str], None] = _quiet,
) -> int:
    if shutil.which("uv") is None:
        print("uv is not on PATH; run this through `mise run demo`", file=sys.stderr)
        return 2
    if not os.environ.get("JEVPLAYS_ROM"):
        print("JEVPLAYS_ROM is not set; run this through `mise run demo`", file=sys.stderr)
        return 2

    resume = resumable(args.runs_dir)
    failures = 0
    runs = 0
    proc = None
    current: Path | None = None
    before: Path | None = None
    previous_handler = signal.signal(signal.SIGTERM, _shutdown)
    try:
        while True:
            runs += 1
            for gone in prune(args.runs_dir, now=time.time()):
                print(f"[demo] pruned {gone}", flush=True)
            day = utc_today()
            left = max(0, args.daily_decisions - decisions_on(args.runs_dir, day))
            started = time.monotonic()
            before = _newest(args.runs_dir)
            if resume is not None:
                (resume / INTERRUPTED).unlink()
            proc = start_run(args, max_decisions=left, resume=resume)
            current, resume = resume, None
            print(
                f"[demo] run {runs} {'resumed ' + current.name if current else 'started'} "
                f"(speed {args.speed}x, {left} of {args.daily_decisions} decisions left today)",
                flush=True,
            )

            seen = progress(args.runs_dir)
            moved_at = time.monotonic()
            while proc.poll() is None:
                sleep(POLL_S)
                now = progress(args.runs_dir)
                said = health(args.host, args.port)
                if now != seen or waiting_on_purpose(said):
                    seen, moved_at = now, time.monotonic()
                if said == "resting" and utc_today() != day:
                    print(
                        f"[demo] run {runs} rested into a new day; starting one with today's budget",
                        flush=True,
                    )
                    stop_run(proc)
                    break
                if stalled(idle_for=time.monotonic() - moved_at, stall_after=args.stall_after):
                    print(
                        f"[demo] run {runs} made no decision for {args.stall_after:.0f}s; restarting it",
                        flush=True,
                    )
                    stop_run(proc)
                    break

            lasted = time.monotonic() - started
            # A run that barely lived did not fail at playing the game -- it failed to start, and the
            # port is the usual reason. Back off on those; come straight back from a finished run.
            failures = failures + 1 if lasted < 30 else 0
            wait = backoff(failures) if failures else 2
            print(f"[demo] run {runs} ended after {lasted:.0f}s; next in {wait}s", flush=True)
            sleep(wait)
    except Shutdown:
        if proc is not None and proc.poll() is None:
            print("[demo] SIGTERM: stopping the run so it writes its exit checkpoint", flush=True)
            stop_run(proc)
            newest = _newest(args.runs_dir)
            run_dir = current or (newest if newest != before else None)
            if run_dir is not None:
                (run_dir / INTERRUPTED).write_text(datetime.now(UTC).isoformat(timespec="seconds") + "\n")
        return 0
    finally:
        signal.signal(signal.SIGTERM, previous_handler)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_demo_loop.py -q`
Expected: all pass, including the pre-existing `test_the_run_command_carries_the_demo_limits` and
`test_with_no_state_the_run_starts_from_the_intro_so_viewers_see_jev_pick_the_starter`.

- [ ] **Step 5: Check the CLI accepts what the supervisor now sends**

Run: `uv run jevplays run --help | grep -E -- "--resume|--runs-dir|--max-decisions"`
Expected: all three flags listed. (`--resume` is refused only with `--state` or `--no-log`,
`src/jevplays/cli.py:442-446`, and the supervisor sends neither with it.)

- [ ] **Step 6: Lint, full check, commit**

```bash
mise run check
git add Scripts/demo-loop.py tests/test_demo_loop.py
git commit -m "feat(tooling): the demo supervisor resumes a run a SIGTERM cut short

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Wait for a missing ROM; exit on a crash loop

**Files:**
- Modify: `Scripts/demo-loop.py` (constants; the checks at the top of `supervise`; after the
  `failures` line)
- Test: `tests/test_demo_loop.py`

**Interfaces:**
- Consumes: `Harness`, `FakeProc`, `supervise(...)` from Task 1.
- Produces: `CRASH_LOOP_AFTER: int = 5`, `ROM_POLL_S: float = 30.0`,
  `missing_rom_message(rom: str) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_demo_loop.py -q -k "crash_loop or rom"`
Expected: FAIL — `CRASH_LOOP_AFTER`/`ROM_POLL_S` missing, and the ROM test starts a run at once.

- [ ] **Step 3: Implement**

Constants, after `MAX_BACKOFF_S`:

```python
CRASH_LOOP_AFTER = 5
"""Runs in a row that each died inside 30s before the supervisor exits, so that Fly's restart
policy restarts the Machine: Fly restarts on a process exit, never on a failing health check."""
ROM_POLL_S = 30.0
"""How often a supervisor with no ROM yet looks again."""


def missing_rom_message(rom: str) -> str:
    return (
        f"no ROM at {rom}; waiting for it. Upload your own dump with: "
        f"fly ssh sftp put <path/to/pokemon-red.gb> {rom}"
    )
```

In `supervise`, move `previous_handler = signal.signal(...)` and the `try:` up so they begin
right after the two existing `return 2` checks, and put the ROM wait first inside the `try:`,
before `resume = resumable(...)`:

```python
    previous_handler = signal.signal(signal.SIGTERM, _shutdown)
    proc = None
    current: Path | None = None
    before: Path | None = None
    try:
        rom = os.environ["JEVPLAYS_ROM"]
        if not Path(rom).is_file():
            print(f"[demo] {missing_rom_message(rom)}", flush=True)
            while not Path(rom).is_file():
                sleep(ROM_POLL_S)
            print(f"[demo] found the ROM at {rom}", flush=True)
        resume = resumable(args.runs_dir)
        failures = 0
        runs = 0
        while True:
            # ... unchanged ...
```

After `failures = failures + 1 if lasted < 30 else 0`, add:

```python
            if failures >= CRASH_LOOP_AFTER:
                print(
                    f"[demo] {failures} runs in a row died within 30s; exiting so the machine restarts",
                    file=sys.stderr,
                    flush=True,
                )
                return 1
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_demo_loop.py -q`
Expected: all pass.

- [ ] **Step 5: Check and commit**

```bash
mise run check
git add Scripts/demo-loop.py tests/test_demo_loop.py
git commit -m "feat(tooling): the demo supervisor waits for its ROM and exits on a crash loop

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: ntfy from the supervisor

**Files:**
- Modify: `Scripts/demo-loop.py`
- Test: `tests/test_demo_loop.py`

**Interfaces:**
- Consumes: `supervise(..., say=...)`, `missing_rom_message`, `CRASH_LOOP_AFTER` from Tasks 1-2.
- Produces: `notify(message: str, *, env: Mapping[str, str] = os.environ, urlopen=urllib.request.urlopen) -> bool`.
  The messages below are exact strings; the README (Task 6) lists them.

- [ ] **Step 1: Write the failing tests**

```python
import contextlib

import pytest


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
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_demo_loop.py -q`
Expected: the new tests FAIL (`notify` missing; `said` empty).

- [ ] **Step 3: Implement**

Imports: add `from collections.abc import Callable, Mapping` (replacing the Task 1 import).

Replace `_quiet` with `notify` (defined before `supervise`, since it is its default):

```python
def notify(
    message: str, *, env: Mapping[str, str] = os.environ, urlopen=urllib.request.urlopen
) -> bool:
    """Post `message` to ntfy at $NTFY_URL, with $NTFY_TOKEN as a bearer token when set. Without
    NTFY_URL it does nothing, so a demo on a laptop behaves as it always has. A failed post is
    printed and dropped: an alert must never be what stops the demo."""
    url = env.get("NTFY_URL")
    if not url:
        return False
    request = urllib.request.Request(
        url, data=message.encode("utf-8"), method="POST", headers={"Title": "jevplays demo"}
    )
    if env.get("NTFY_TOKEN"):
        request.add_header("Authorization", f"Bearer {env['NTFY_TOKEN']}")
    try:
        with urlopen(request, timeout=10):
            pass
    except OSError as error:
        print(f"[demo] ntfy post failed: {error}", file=sys.stderr, flush=True)
        return False
    return True
```

In `supervise`: change the default `say: Callable[[str], None] = notify`, and add the calls:

- ROM wait, right after its `print`: `say(missing_rom_message(rom))`
- After `resume = resumable(args.runs_dir)`:
  `say(f"demo started, resuming run {resume.name}" if resume else "demo started, new run")`
- Before the inner `while proc.poll() is None:` add `told_resting = False`; inside it, after
  `said = health(...)`:
  ```python
                if said == "resting" and not told_resting:
                    told_resting = True
                    say(f"daily budget of {args.daily_decisions} decisions spent; resting until 00:00 UTC")
  ```
- In the new-day branch, before `stop_run(proc)`: `say("new UTC day; starting a run with today's budget")`
- In the stall branch, before `stop_run(proc)`:
  `say(f"run {runs} made no decision for {args.stall_after:.0f}s; restarting it")`
- In the crash-loop branch: build the message once and both print and say it:
  ```python
            if failures >= CRASH_LOOP_AFTER:
                message = f"{failures} runs in a row died within 30s; exiting so the machine restarts"
                print(f"[demo] {message}", file=sys.stderr, flush=True)
                say(message)
                return 1
  ```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_demo_loop.py -q`
Expected: all pass. (The `Harness` unsets `NTFY_URL`, and passes its own `say`, so no test posts.)

- [ ] **Step 5: Check and commit**

```bash
mise run check
git add Scripts/demo-loop.py tests/test_demo_loop.py
git commit -m "feat(tooling): the demo supervisor posts what happens to ntfy

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: The image and the Machine

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `fly.toml`, `tests/test_container.py`
- Modify: `mise.toml` (`[tools]`), `.github/workflows/ci.yml` (new `image` job)

**Interfaces:**
- Consumes: the supervisor's CLI flags (`--host`, `--runs-dir`, `--speed`, `--daily-decisions`)
  and its missing-ROM message, which contains `fly ssh sftp put` (Task 2).
- Produces: a job named `image` in `ci.yml` (Task 5's `deploy` needs it); the Fly volume mounted
  at `/data`; `JEVPLAYS_ROM=/data/rom/pokemon-red.gb`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_container.py`:

```python
"""The image must never be able to hold game data, and fly.toml and the Dockerfile must agree
on where the volume is. No Docker here: these read the files; CI's `image` job builds it."""

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAME_DATA = {
    "roms",
    "states",
    "runs",
    ".worktrees",
    "**/*.gb",
    "**/*.gbc",
    "**/*.state",
    "**/*.ram",
    "mise.local.toml",
}
MAY_COPY = {"pyproject.toml", "uv.lock", "README.md", ".python-version", "src", "Scripts/demo-loop.py"}


def dockerfile() -> list[str]:
    return (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()


def fly() -> dict:
    return tomllib.loads((ROOT / "fly.toml").read_text(encoding="utf-8"))


def test_the_build_context_leaves_out_every_kind_of_game_data():
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    ignored = {line.strip() for line in lines if line.strip() and not line.startswith("#")}
    assert GAME_DATA <= ignored


def test_the_image_copies_only_the_package_and_the_supervisor():
    sources = set()
    for line in dockerfile():
        if line.startswith("COPY "):
            parts = [p for p in line.split()[1:] if not p.startswith("--")]
            sources.update(parts[:-1])
    assert sources and sources <= MAY_COPY


def test_the_rom_and_the_runs_live_on_the_volume():
    config = fly()
    mount = config["mounts"]["destination"]
    assert config["env"]["JEVPLAYS_ROM"].startswith(mount + "/")
    [cmd] = [json.loads(line[len("CMD ") :]) for line in dockerfile() if line.startswith("CMD ")]
    assert cmd[cmd.index("--runs-dir") + 1].startswith(mount + "/")


def test_the_machine_runs_always_and_is_checked_on_health():
    """The demo pauses itself when unwatched; Fly auto-stop would fight that and the resume."""
    service = fly()["http_service"]
    assert service["internal_port"] == 8765
    assert service["auto_stop_machines"] == "off"
    assert [c["path"] for c in service["checks"]] == ["/health"]


def test_fly_waits_longer_than_the_supervisor_does_for_a_run_to_checkpoint():
    """`stop()` gives a run 15s after SIGTERM to write its exit checkpoint before SIGKILL."""
    timeout = fly()["kill_timeout"]
    assert fly()["kill_signal"] == "SIGTERM"
    assert int(str(timeout).rstrip("s")) > 15
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_container.py -q`
Expected: FAIL with `FileNotFoundError` for `.dockerignore`, `Dockerfile`, `fly.toml`.

- [ ] **Step 3: Write `.dockerignore`**

```gitignore
# The build context. Game data must never reach it: the ROM is the owner's own dump and lives only
# on the Fly volume; save states, .ram files and runs/ are copies of its memory. The patterns match
# at any depth, and tests/test_container.py checks they stay here.
roms
states
runs
.worktrees
**/*.gb
**/*.gbc
**/*.state
**/*.ram
mise.local.toml
.mise.local.toml

# Not needed to build, and large.
.git
.venv
**/__pycache__
.pytest_cache
.ruff_cache
docs
tests
```

- [ ] **Step 4: Write `Dockerfile`**

```dockerfile
# The demo supervisor (Scripts/demo-loop.py) and the package it runs, headless. No game data:
# .dockerignore keeps it out of the context and the COPY lines below name everything that goes in.
# The ROM is on the Fly volume at /data/rom (see fly.toml and README.md "Production").
FROM ghcr.io/astral-sh/uv:0.12.17-python3.14-trixie-slim@sha256:63018e7b676ef735eee4da4f9c2e7b5f5e3851fa023745d78ce91d1a099a35fd

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_SYNC=1 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first, so a change to src/ does not reinstall them.
COPY pyproject.toml uv.lock README.md .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY Scripts/demo-loop.py ./Scripts/demo-loop.py
RUN uv sync --frozen --no-dev

EXPOSE 8765
CMD ["uv", "run", "python", "Scripts/demo-loop.py", "--host", "0.0.0.0", "--runs-dir", "/data/runs", "--speed", "3", "--daily-decisions", "3000"]
```

- [ ] **Step 5: Write `fly.toml`**

```toml
# The public demo: one Machine running Scripts/demo-loop.py. Design:
# docs/superpowers/specs/2026-09-24-fly-deploy-design.md. Deployed by ci.yml's `deploy` job.
app = "jevplays"
primary_region = "sjc"

# The supervisor forwards SIGTERM to the run, which writes its exit checkpoint; stop() allows it
# 15s before SIGKILL, so Fly must wait longer than that.
kill_signal = "SIGTERM"
kill_timeout = 30

[build]
  dockerfile = "Dockerfile"

[env]
  JEVPLAYS_ROM = "/data/rom/pokemon-red.gb"

# Holds the ROM (uploaded once with `fly ssh sftp put`) and runs/. Never in the image.
[mounts]
  source = "jevplays_data"
  destination = "/data"

[http_service]
  internal_port = 8765
  force_https = true
  # The demo pauses itself when nobody is watching; Fly stopping the Machine would fight that.
  auto_stop_machines = "off"
  auto_start_machines = true
  min_machines_running = 1

  [[http_service.checks]]
    grace_period = "60s"
    interval = "30s"
    timeout = "5s"
    method = "GET"
    path = "/health"

[[vm]]
  size = "shared-cpu-1x"
  memory = "1gb"
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_container.py -q`
Expected: 5 passed.

- [ ] **Step 7: Pin flyctl in mise**

In `mise.toml` `[tools]`, after `pinact`:

```toml
# For the one-time Fly setup and `fly logs`; the deploy job pins the same version.
"aqua:superfly/flyctl" = "0.4.107"
```

Run: `mise install && mise exec -- flyctl version`
Expected: prints `flyctl v0.4.107 ...`.

- [ ] **Step 8: Add the `image` job to `.github/workflows/ci.yml`**

Append under `jobs:` (same indentation as `test:`):

```yaml
  image:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0
        with: {persist-credentials: false}
      - run: docker build -t jevplays .
      - name: The image holds no game data
        run: |
          docker run --rm jevplays sh -c \
            'test ! -e /data && ! find /app \( -name "*.gb" -o -name "*.gbc" -o -name "*.state" -o -name "*.ram" \) | grep .'
      - name: The emulator imports headless
        run: docker run --rm jevplays uv run python -c "import pyboy, jevplays.cli"
      - name: With no ROM it waits and says how to upload one
        run: |
          set +e
          out=$(timeout 20 docker run --rm -e JEVPLAYS_ROM=/data/rom/pokemon-red.gb jevplays 2>&1)
          code=$?
          echo "$out"
          test "$code" -eq 124 && grep -q "fly ssh sftp put" <<<"$out"
```

- [ ] **Step 9: Lint, check, commit, and let CI build the image**

```bash
mise run check
git add Dockerfile .dockerignore fly.toml mise.toml tests/test_container.py .github/workflows/ci.yml
git commit -m "feat(tooling): a Dockerfile and fly.toml for the demo, with the ROM on a volume

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git push -u origin tylervick/production
gh pr create --draft --title "The demo on Fly.io" --body "Spec: docs/superpowers/specs/2026-09-24-fly-deploy-design.md (draft while the plan is carried out)

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
gh pr checks --watch
```

Expected: `test` and `image` both pass. There is no Docker on this machine, so CI is where the image
is first built; if `image` fails, read its log (`gh run view --log-failed`), fix, and push again
before starting Task 5.

---

### Task 5: Deploy job, uptime check, and the workflows' ntfy post

**Files:**
- Create: `Scripts/ntfy.sh`, `tests/test_ntfy_sh.py`, `.github/workflows/uptime.yml`
- Modify: `.github/workflows/ci.yml` (new `deploy` job)

**Interfaces:**
- Consumes: the `test` and `image` jobs (Task 4); `fly.toml` (Task 4).
- Produces: `Scripts/ntfy.sh MESSAGE` — posts MESSAGE to `$NTFY_URL` with `$NTFY_TOKEN` as bearer
  when set; exits 0 without `NTFY_URL`; a failed post prints to stderr and still exits 0.
- Repository settings Tyler creates (named here, never set by this plan): secrets
  `FLY_API_TOKEN`, `NTFY_URL`, `NTFY_TOKEN`; variables `FLY_DEPLOY` (`true` to deploy) and
  `DEMO_URL` (e.g. `https://jevplays.fly.dev`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ntfy_sh.py`:

```python
"""Scripts/ntfy.sh is how the workflows post to ntfy. Exercised against a local HTTP server."""

import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "Scripts" / "ntfy.sh"


def serve_once(status: int = 200):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            received.append((self.path, self.headers.get("Authorization"), self.rfile.read(length).decode()))
            self.send_response(status)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    return server, thread, received


def run(message: str, **env) -> subprocess.CompletedProcess:
    base = {k: v for k, v in os.environ.items() if k not in ("NTFY_URL", "NTFY_TOKEN")}
    return subprocess.run(["bash", str(SCRIPT), message], env={**base, **env}, capture_output=True, text=True)


def test_it_posts_the_message_with_the_token():
    server, thread, received = serve_once()
    result = run("deploy ok", NTFY_URL=f"http://127.0.0.1:{server.server_port}/demo", NTFY_TOKEN="tk")
    thread.join(5)
    server.server_close()
    assert result.returncode == 0
    assert received == [("/demo", "Bearer tk", "deploy ok")]


def test_without_a_url_it_does_nothing():
    assert run("deploy ok").returncode == 0


def test_a_refused_post_is_reported_but_never_fails_the_job():
    server, thread, received = serve_once(status=403)
    result = run("deploy ok", NTFY_URL=f"http://127.0.0.1:{server.server_port}/demo")
    thread.join(5)
    server.server_close()
    assert result.returncode == 0
    assert "ntfy post failed" in result.stderr
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_ntfy_sh.py -q`
Expected: FAIL — `bash: .../Scripts/ntfy.sh: No such file or directory` (returncode 127).

- [ ] **Step 3: Write `Scripts/ntfy.sh`**

```bash
#!/usr/bin/env bash
# Post one message to ntfy from a workflow: Scripts/ntfy.sh "deploy ok".
# NTFY_URL is the server and topic (a secret: on ntfy the topic name is the password), NTFY_TOKEN
# an access token when the server wants one. Without NTFY_URL this does nothing. A failed post is
# reported and never fails the job: an alert is not worth a red build.
set -euo pipefail

[ -n "${NTFY_URL:-}" ] || exit 0

args=(-fsS -m 10 -H "Title: jevplays demo" --data-binary "$1")
if [ -n "${NTFY_TOKEN:-}" ]; then
  args+=(-H "Authorization: Bearer ${NTFY_TOKEN}")
fi
curl "${args[@]}" "$NTFY_URL" >/dev/null || echo "ntfy post failed" >&2
```

Run: `chmod +x Scripts/ntfy.sh && uv run pytest tests/test_ntfy_sh.py -q`
Expected: 3 passed.

- [ ] **Step 4: Add the `deploy` job to `.github/workflows/ci.yml`**

```yaml
  # Deploys main to Fly once the tests and the image check pass. Off until Tyler sets the repository
  # variable FLY_DEPLOY to "true" (after the app, volume, ROM and secrets exist), so main does not
  # fail on a deploy that cannot work yet. The build runs on Fly's builder from this checkout, which
  # holds no game data; the ROM stays on the volume.
  deploy:
    needs: [test, image]
    if: github.event_name == 'push' && github.ref == 'refs/heads/main' && vars.FLY_DEPLOY == 'true'
    runs-on: ubuntu-latest
    concurrency: {group: deploy, cancel-in-progress: false}
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0
        with: {persist-credentials: false}
      - uses: superfly/flyctl-actions/setup-flyctl@fc53c09e1bc3be6f54706524e3b82c4f462f77be # 1.5
        with: {version: 0.4.107}
      - run: flyctl deploy --remote-only
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
      - name: Tell ntfy
        if: always()
        env:
          NTFY_URL: ${{ secrets.NTFY_URL }}
          NTFY_TOKEN: ${{ secrets.NTFY_TOKEN }}
          RESULT: ${{ job.status }}
          SHA: ${{ github.sha }}
        run: Scripts/ntfy.sh "deploy ${RESULT}: ${SHA:0:7}"
```

- [ ] **Step 5: Write `.github/workflows/uptime.yml`**

```yaml
name: uptime
# The demo cannot report its own Machine being down, so this does. Inert until the repository
# variable DEMO_URL is set. GitHub runs schedules late at times: an outage can take 10-30 minutes
# to be noticed. Posts to ntfy only on a change, reading the last run's conclusion as the state:
# this job fails while the demo is down.
on:
  schedule:
    - cron: "*/10 * * * *"
  workflow_dispatch:
permissions:
  contents: read
  actions: read
jobs:
  check:
    if: vars.DEMO_URL != ''
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0
        with: {persist-credentials: false}
      - name: Check /health and post on a change
        env:
          DEMO_URL: ${{ vars.DEMO_URL }}
          NTFY_URL: ${{ secrets.NTFY_URL }}
          NTFY_TOKEN: ${{ secrets.NTFY_TOKEN }}
          GH_TOKEN: ${{ github.token }}
          REPO: ${{ github.repository }}
        run: |
          if curl -fsS -m 15 -o /dev/null "$DEMO_URL/health"; then now=up; else now=down; fi
          last=$(gh run list -R "$REPO" --workflow uptime.yml --status completed --limit 1 \
            --json conclusion -q '.[0].conclusion // "success"')
          if [ "$last" = failure ]; then was=down; else was=up; fi
          echo "demo is $now (was $was)"
          if [ "$now" != "$was" ]; then
            if [ "$now" = down ]; then Scripts/ntfy.sh "demo is down: $DEMO_URL/health is not answering"
            else Scripts/ntfy.sh "demo is back up"; fi
          fi
          test "$now" = up
```

- [ ] **Step 6: Lint and check**

Run: `mise run check`
Expected: pass. If zizmor or actionlint objects, fix the workflow, not the linter config; if an
action pin is questioned, `mise run pin-actions` re-verifies SHAs against their tags.

- [ ] **Step 7: Commit and push**

```bash
git add Scripts/ntfy.sh tests/test_ntfy_sh.py .github/workflows/ci.yml .github/workflows/uptime.yml
git commit -m "feat(tooling): deploy main to Fly behind a switch, and check the demo is up

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git push
gh pr checks --watch
```

Expected: `test` and `image` pass; `deploy` does not appear on a pull request (it is `push`-only).

---

### Task 6: README "Production"

**Files:**
- Modify: `README.md` (a new `## Production` section after "A demo anyone can watch"; one line in
  "A public link")

**Interfaces:**
- Consumes: every exact name above: `fly.toml`'s app `jevplays`, volume `jevplays_data` at `/data`,
  `JEVPLAYS_ROM=/data/rom/pokemon-red.gb`, secrets, variables, and the supervisor's ntfy messages
  from Task 3.

- [ ] **Step 1: Write the section**

Insert after the "A public link" subsection:

````markdown
## Production

The public demo runs on one Fly.io Machine (`fly.toml`, `Dockerfile`), deployed by CI from `main`.
Design: `docs/superpowers/specs/2026-09-24-fly-deploy-design.md`. The ROM is never in the image or
the repository: it lives on the Machine's volume, uploaded once by hand.

One-time setup (flyctl is pinned in `mise.toml`: run these as `mise exec -- flyctl ...`, written
below by its short name `fly`):

```bash
fly apps create jevplays
fly volumes create jevplays_data --region sjc --size 1
fly secrets set TYPESAFE_API_KEY=... NTFY_URL=https://<ntfy server>/<topic> NTFY_TOKEN=...
fly deploy                        # the Machine starts and waits for its ROM
fly ssh sftp put /path/to/your/pokemon-red.gb /data/rom/pokemon-red.gb
```

(`sftp put` does not create directories: first `fly ssh console -C "mkdir -p /data/rom"`.)

Then in the GitHub repository settings: secrets `FLY_API_TOKEN` (`fly tokens create deploy`),
`NTFY_URL` and `NTFY_TOKEN`; variables `FLY_DEPLOY=true` and `DEMO_URL=https://jevplays.fly.dev`.

From then on every push to `main` that passes CI deploys. A deploy stops the Machine with SIGTERM;
the run writes its exit checkpoint and the next Machine resumes it, so viewers see the page
reconnect about a minute later on the same run. `fly logs` shows the supervisor's `[demo]` lines.

What ntfy says, and what it means:

- `demo started, new run` / `demo started, resuming run <stamp>`: a deploy or restart.
- `no ROM at ...; waiting for it`: the volume has no ROM; upload it as above.
- `run N made no decision for 300s; restarting it`: the #67 watchdog fired.
- `daily budget of 3000 decisions spent; resting until 00:00 UTC`, then
  `new UTC day; starting a run with today's budget`.
- `5 runs in a row died within 30s; exiting so the machine restarts`: runs cannot start; Fly
  restarts the Machine, and after ten tries stops it. `fly logs` says why.
- `deploy success: <sha>` / `deploy failure: <sha>`: from CI.
- `demo is down: ...` / `demo is back up`: from the `uptime` workflow, every 10 minutes (GitHub
  runs it late at times).
````

- [ ] **Step 2: Point "A public link" at it**

At the end of the "### A public link" subsection's first paragraph, add:
`The hosted demo runs this same supervisor on Fly.io; see "Production" below.`

- [ ] **Step 3: Check and commit**

```bash
mise run check
git add README.md
git commit -m "docs: how the demo runs on Fly.io and what its alerts mean

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git push
gh pr ready
```

---

## After the plan: Tyler's rollout (not agent work)

Straight from the spec's "Rollout": the one-time setup above, the first deploy, the ROM upload,
the two repository variables. Then check the page, `/health`, a push to `main` that deploys and
resumes, and one ntfy post of each kind; measure CPU over a 20-minute viewing session and resize to
`shared-cpu-2x` if it throttles, recording the size in the spec; stop the Mac mini's supervisor and
tunnel; close #73 as superseded.
