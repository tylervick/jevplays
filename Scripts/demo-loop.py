#!/usr/bin/env -S uv run --script
"""Keep a jevplays run going, forever, so the dashboard is always worth opening.

    mise run demo                       # real time, on the local network
    Scripts/demo-loop.py --speed 6      # six times the game's own clock

One run ends at the Boulder Badge, so a demo anyone can drop in on needs something to start the
next one. That is all this is: start a run, watch it, start another when it stops.

Two things it watches for.

A run that **finishes or dies** is restarted, after a short backoff that grows if it keeps
happening -- a demo that cannot start should not spin on it, and a demo whose ROM has gone
missing should say so rather than hammer.

A run that **stalls** is killed and restarted. #67: the loop can sit in BATTLE_WAIT pressing A
at a screen that A does not advance, making no decisions while the process stays up and the log
ends on an ordinary battle turn. Nothing inside the run notices, so this does, by watching the
newest run directory's decision count.

Pacing is the thing to get right for viewing. Real time is the honest default but takes about two
hours to the badge; `--speed` multiplies the clock the sleep is computed against, so the same
decisions arrive sooner. Unpaced is not offered here: the whole run would be over in half a
minute and the demo would be a restart loop.

Behind a public link, three limits keep it from spending while nobody is there. A run pauses
once no dashboard has been open for `--pause-after` seconds and carries on when one opens. Each
run is started with what is left of `--daily-decisions` for the UTC day, counted from the logs
on disk; a run that reaches it rests with the page up, and is replaced once the day turns over.
Past `--max-viewers` tabs, the page is told the demo is full. Old run directories are pruned,
since they are save-state data and the watchdog and the budget both need logging kept on.
"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

STALL_AFTER_S = 300.0
"""Seconds without a new decision before a run is treated as hung (#67)."""
MAX_BACKOFF_S = 60
CRASH_LOOP_AFTER = 5
"""Runs in a row that each died inside 30s before the supervisor exits, so that Fly's restart
policy restarts the Machine: Fly restarts on a process exit, never on a failing health check."""
ROM_POLL_S = 30.0
"""How often a supervisor with no ROM yet looks again."""
POLL_S = 5.0
KEEP_RUNS_S = 2 * 86400
"""Run directories last written longer ago than this are pruned before each start."""
WAITING_ON_PURPOSE = frozenset({"unwatched", "resting"})
"""Dashboard statuses of a run that has stopped deciding by design, not because it hung."""

INTERRUPTED = "interrupted"
"""Written into a run directory when a SIGTERM made the supervisor stop that run. Fly sends SIGTERM
before every deploy and every stop; the next supervisor resumes the run that holds this, once."""


class Shutdown(Exception):
    """SIGTERM arrived: the machine is being stopped or redeployed."""


def _shutdown(signum, frame) -> None:
    raise Shutdown


def _quiet(message: str) -> None:
    """What `supervise` announces events to when nobody asked to hear about them."""


def _runs(runs_dir: Path) -> list[Path]:
    if not runs_dir.is_dir():
        return []
    return [p for p in runs_dir.iterdir() if (p / "run.json").is_file()]


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


def utc_today() -> date:
    return datetime.now(UTC).date()


def decisions_on(runs_dir: Path, day: date) -> int:
    """Decisions any run under `runs_dir` made on the UTC `day`, by each decision's own `ts`."""
    total = 0
    for run in _runs(runs_dir):
        log = run / "decisions.jsonl"
        if not log.is_file():
            continue
        with log.open(encoding="utf-8") as f:
            for line in f:
                try:
                    ts = json.loads(line)["ts"]
                except (ValueError, KeyError, TypeError):
                    continue  # a line torn by a kill mid-append
                if datetime.fromtimestamp(ts, UTC).date() == day:
                    total += 1
    return total


def _last_written(run: Path) -> float:
    return max([run.stat().st_mtime, *(f.stat().st_mtime for f in run.iterdir())])


def prune(runs_dir: Path, *, now: float, keep_s: float = KEEP_RUNS_S) -> list[Path]:
    """Delete run directories last written more than `keep_s` ago, except the newest. Returns
    what it deleted. Only directories holding a run.json are touched."""
    runs = sorted(_runs(runs_dir), key=lambda p: p.name)
    gone = [run for run in runs[:-1] if now - _last_written(run) > keep_s]
    for run in gone:
        shutil.rmtree(run)
    return gone


def status(host: str, port: int) -> str | None:
    """The run's dashboard status from /health, or None when the page does not answer."""
    probe = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    try:
        with urllib.request.urlopen(f"http://{probe}:{port}/health", timeout=2) as response:
            return json.load(response).get("status")
    except (OSError, ValueError):
        return None


def waiting_on_purpose(status: str | None) -> bool:
    return status in WAITING_ON_PURPOSE


def stalled(*, idle_for: float, stall_after: float) -> bool:
    return idle_for > stall_after


def backoff(consecutive_failures: int) -> int:
    """2, 4, 8 ... capped. A run that ends properly passes 0 and comes back in two seconds."""
    return min(MAX_BACKOFF_S, 2 ** (consecutive_failures + 1))


def missing_rom_message(rom: str) -> str:
    return (
        f"no ROM at {rom}; waiting for it. Upload your own dump with: "
        f"fly ssh sftp put <path/to/pokemon-red.gb> {rom}"
    )


def command(args, *, max_decisions: int, resume: Path | None = None) -> list[str]:
    cmd = [
        "uv",
        "run",
        "jevplays",
        "run",
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--runs-dir",
        str(args.runs_dir),
        "--speed",
        str(args.speed),
        "--max-decisions",
        str(max_decisions),
        "--pause-after",
        str(args.pause_after),
    ]
    if resume is not None:
        cmd += ["--resume", str(resume)]
    elif args.state is not None:
        cmd += ["--state", args.state]
    if args.max_viewers is not None:
        cmd += ["--max-viewers", str(args.max_viewers)]
    return cmd


def start(args, *, max_decisions: int, resume: Path | None = None) -> subprocess.Popen:
    return subprocess.Popen(command(args, max_decisions=max_decisions, resume=resume), start_new_session=True)


def stop(proc: subprocess.Popen) -> None:
    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)


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
            if failures >= CRASH_LOOP_AFTER:
                print(
                    f"[demo] {failures} runs in a row died within 30s; exiting so the machine restarts",
                    file=sys.stderr,
                    flush=True,
                )
                return 1
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--state",
        default=None,
        help="start every run from this save state; by default a run walks the intro and Jev picks the starter",
    )
    ap.add_argument("--host", default="0.0.0.0", help="0.0.0.0 serves the dashboard to the local network")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--runs-dir", type=Path, default=Path("runs/demo"))
    ap.add_argument("--speed", type=float, default=6.0, help="multiple of the game's own clock")
    ap.add_argument("--stall-after", type=float, default=STALL_AFTER_S)
    ap.add_argument(
        "--daily-decisions", type=int, default=1500, help="decisions per UTC day across every run"
    )
    ap.add_argument(
        "--pause-after", type=float, default=60.0, help="seconds with no viewer before a run pauses"
    )
    ap.add_argument("--max-viewers", type=int, default=20, help="dashboard tabs served at once")
    args = ap.parse_args()
    try:
        return supervise(args)
    except KeyboardInterrupt:
        print("\n[demo] stopped", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
