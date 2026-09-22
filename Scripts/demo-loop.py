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
"""

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

STALL_AFTER_S = 300.0
"""Seconds without a new decision before a run is treated as hung (#67)."""
MAX_BACKOFF_S = 60
POLL_S = 5.0


def progress(runs_dir: Path) -> int:
    """Decisions made by the newest run under `runs_dir`, or 0 when there is not one yet."""
    if not runs_dir.is_dir():
        return 0
    runs = [p for p in runs_dir.iterdir() if (p / "run.json").is_file()]
    if not runs:
        return 0
    newest = max(runs, key=lambda p: p.name)
    log = newest / "decisions.jsonl"
    if not log.is_file():
        return 0
    with log.open(encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def stalled(*, idle_for: float, stall_after: float) -> bool:
    return idle_for > stall_after


def backoff(consecutive_failures: int) -> int:
    """2, 4, 8 ... capped. A run that ends properly passes 0 and comes back in two seconds."""
    return min(MAX_BACKOFF_S, 2 ** (consecutive_failures + 1))


def start(args) -> subprocess.Popen:
    cmd = [
        "uv",
        "run",
        "jevplays",
        "run",
        "--state",
        args.state,
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--runs-dir",
        str(args.runs_dir),
        "--speed",
        str(args.speed),
    ]
    return subprocess.Popen(cmd, start_new_session=True)


def supervise(args) -> int:
    if shutil.which("uv") is None:
        print("uv is not on PATH; run this through `mise run demo`", file=sys.stderr)
        return 2
    if not os.environ.get("JEVPLAYS_ROM"):
        print("JEVPLAYS_ROM is not set; run this through `mise run demo`", file=sys.stderr)
        return 2

    failures = 0
    runs = 0
    while True:
        runs += 1
        started = time.monotonic()
        proc = start(args)
        print(f"[demo] run {runs} started (pid {proc.pid}, speed {args.speed}x)", flush=True)

        seen = progress(args.runs_dir)
        moved_at = time.monotonic()
        while proc.poll() is None:
            time.sleep(POLL_S)
            now = progress(args.runs_dir)
            if now != seen:
                seen, moved_at = now, time.monotonic()
            elif stalled(idle_for=time.monotonic() - moved_at, stall_after=args.stall_after):
                print(
                    f"[demo] run {runs} made no decision for {args.stall_after:.0f}s; restarting it",
                    flush=True,
                )
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                break

        lasted = time.monotonic() - started
        # A run that barely lived did not fail at playing the game -- it failed to start, and the
        # port is the usual reason. Back off on those; come straight back from a finished run.
        failures = failures + 1 if lasted < 30 else 0
        wait = backoff(failures) if failures else 2
        print(f"[demo] run {runs} ended after {lasted:.0f}s; next in {wait}s", flush=True)
        time.sleep(wait)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", default="states/route1.state")
    ap.add_argument("--host", default="0.0.0.0", help="0.0.0.0 serves the dashboard to the local network")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--runs-dir", type=Path, default=Path("runs/demo"))
    ap.add_argument("--speed", type=float, default=6.0, help="multiple of the game's own clock")
    ap.add_argument("--stall-after", type=float, default=STALL_AFTER_S)
    args = ap.parse_args()
    try:
        return supervise(args)
    except KeyboardInterrupt:
        print("\n[demo] stopped", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
