"""`jevplays run` boots the game and serves the dashboard; `jevplays state` inspects a save."""

import argparse
import asyncio
import contextlib
import json
import os
import signal
import socket
import sys
from pathlib import Path


def _rom_from_env() -> Path | None:
    path = os.environ.get("JEVPLAYS_ROM")
    return Path(path) if path else None


def cmd_state(args: argparse.Namespace) -> int:
    rom = args.rom or _rom_from_env()
    if rom is None:
        print("no ROM: pass --rom or set JEVPLAYS_ROM", file=sys.stderr)
        return 2
    if not args.state.is_file():
        print(f"no such state file: {args.state}", file=sys.stderr)
        return 2
    # Imported after the ROM and state checks so a run without a ROM (CI), or with a typo'd
    # state path, never loads PyBoy and SDL.
    from jevplays.emulator.pyboy import Emulator
    from jevplays.state.snapshot import snapshot

    with Emulator(rom) as emu:
        emu.load(args.state)
        print(json.dumps(snapshot(emu).to_dict(), indent=2, ensure_ascii=False))
    return 0


async def _print_goals(loop, interval: float = 0.2) -> None:
    """Print the overworld goal on the terminal whenever it changes, so a run is followable
    without the dashboard open. The loop owns `goal`; this only reads it."""
    last = object()
    while True:
        current = loop.goal.id if loop.goal is not None else None
        if current != last:
            print(f"goal: {current or 'none'}", flush=True)
            last = current
        await asyncio.sleep(interval)


def resolve_resume(run_dir) -> tuple[Path, int, int]:
    """Work out where `--resume` picks the run up: the newest checkpoint, the decision count it
    was written at, and how many later decisions had to be set aside.

    The checkpoint is the game as it stood just after decision `n`, so anything the log holds
    beyond `n` was written after it and rolled back with it: replaying those would show
    decisions that never happened and misnumber the next checkpoint. They move to
    `decisions.orphaned.jsonl` instead. Raises FileNotFoundError if there is no checkpoint.
    Takes a RunDir (untyped here so importing cli never pulls the log module in)."""
    path = run_dir.last_checkpoint()
    if path is None:
        raise FileNotFoundError(f"{run_dir.path} has no checkpoint to resume from")
    n = run_dir.checkpoint_number(path)
    orphaned = run_dir.truncate_to(n)
    run_dir.mark_resumed(from_checkpoint=n, orphaned=orphaned)
    return path, n, orphaned


def cmd_run(args: argparse.Namespace) -> int:
    rom = args.rom or _rom_from_env()
    if rom is None:
        print("no ROM: pass --rom or set JEVPLAYS_ROM", file=sys.stderr)
        return 2
    from jevplays.runlog import RunDir

    run_dir = None
    start_state = args.state
    if args.resume is not None:
        try:
            run_dir = RunDir.open(args.resume)
            start_state, checkpoint_n, orphaned = resolve_resume(run_dir)
        except FileNotFoundError as error:
            print(f"jevplays run: {error}", file=sys.stderr)
            return 2
        print(f"run: resuming {start_state} from checkpoint {checkpoint_n}", flush=True)
        if orphaned:
            print(
                f"run: {orphaned} decision(s) after the checkpoint moved to decisions.orphaned.jsonl",
                flush=True,
            )
    elif not args.no_log:
        run_dir = RunDir.create(
            args.runs_dir,
            rom=rom,
            flags={
                "state": str(args.state) if args.state else None,
                "resume": None,
                "port": args.port,
                "unpaced": args.unpaced,
                "no_brain": args.no_brain,
                "battle_goal": args.battle_goal,
            },
        )

    from jevplays.dashboard.events import status_event
    from jevplays.dashboard.server import Broadcaster, create_app, serve
    from jevplays.emulator.intro import walk_intro
    from jevplays.emulator.pyboy import Emulator
    from jevplays.loop import Loop, LoopConfig

    failures: list[Exception] = []

    async def main_async() -> None:
        broadcaster = Broadcaster()
        server = asyncio.create_task(serve(create_app(broadcaster), host=args.host, port=args.port))
        try:
            with Emulator(rom) as emu:
                if start_state:
                    what = "resuming from" if args.resume is not None else "loading"
                    await broadcaster.publish(status_event("running", f"{what} {start_state}"))
                    emu.load(start_state)
                else:
                    await broadcaster.publish(status_event("running", "walking the intro"))
                    walk_intro(emu)
                # walk_intro/emu.load are synchronous, so nothing above this has actually
                # suspended back to the event loop; without a real await, the server task
                # would not have run even once yet. Give it a moment so a bind failure (e.g.
                # the port is in use) is caught here instead of surfacing later, mid-loop.
                await asyncio.sleep(0.2)
                # A dead server task here means the bind failed. .result() raises its real
                # error instead of us printing a dashboard URL that is never going to answer.
                if server.done():
                    server.result()
                print(f"dashboard: {dashboard_url(args.host, args.port)}", flush=True)
                print(f"run: {run_dir.path}" if run_dir else "run: not logged (--no-log)", flush=True)
                await broadcaster.publish(status_event("running", "idle at the first decision point"))
                brain = None
                if not args.no_brain and os.environ.get("TYPESAFE_API_KEY"):
                    from jevplays.brain.client import Brain

                    brain = Brain()
                    print("brain: jev-latest", flush=True)
                else:
                    print("brain: off" + ("" if args.no_brain else " (no TYPESAFE_API_KEY)"), flush=True)
                config = LoopConfig(paced=not args.unpaced, goal=args.battle_goal)
                loop = Loop(emu, broadcaster, config, brain=brain, run_dir=run_dir)
                watcher = asyncio.create_task(_print_goals(loop))
                try:
                    await loop.run()
                finally:
                    watcher.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await watcher
                    try:
                        await loop.checkpoint()
                    except Exception as error:
                        # A failed save (a full disk, a vanished run directory) must not take
                        # the rest of the shutdown -- the stopped status, closing the brain --
                        # down with it. It does make the run exit non-zero, below.
                        print(f"jevplays run: the exit checkpoint failed: {error}", file=sys.stderr)
                        failures.append(error)
                    await broadcaster.publish(status_event("stopped"))
                    if brain is not None:
                        await brain.close()
        finally:
            server.cancel()
            # uvicorn re-raises the signal it captured once it has shut down; by then we are
            # already on our way out, so that second KeyboardInterrupt is nothing but noise.
            with contextlib.suppress(asyncio.CancelledError, KeyboardInterrupt):
                await server  # let uvicorn shut down before the process exits

    # A plain `kill` (SIGTERM) is how a supervisor stops a run. Point it at the SIGINT handler so
    # it becomes the KeyboardInterrupt below and the exit checkpoint in the finally still runs.
    with contextlib.suppress(ValueError):  # not the main thread (a test runner)
        signal.signal(signal.SIGTERM, signal.getsignal(signal.SIGINT))
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass
    except SystemExit as exc:
        # uvicorn's own startup failure (e.g. a bind error) calls sys.exit() from inside the
        # server task rather than raising an ordinary exception; it has already logged the
        # cause, so add only what it doesn't know: which port we asked for.
        if exc.code not in (0, None):
            print(f"jevplays run: could not start the dashboard on port {args.port}", file=sys.stderr)
            return 1
    return 1 if failures else 0


def cmd_replay(args: argparse.Namespace) -> int:
    from jevplays.dashboard.replay import replay
    from jevplays.dashboard.server import Broadcaster, create_app, serve
    from jevplays.runlog import RunDir

    try:
        run_dir = RunDir.open(args.run_dir)
    except FileNotFoundError as error:
        print(f"jevplays replay: {error}", file=sys.stderr)
        return 2

    async def main_async() -> None:
        broadcaster = Broadcaster()
        server = asyncio.create_task(serve(create_app(broadcaster), host=args.host, port=args.port))
        try:
            await asyncio.sleep(0.2)
            if server.done():
                server.result()
            print(f"dashboard: {dashboard_url(args.host, args.port)}", flush=True)
            print(f"replaying {run_dir.path} ({run_dir.count()} decisions)", flush=True)
            if args.wait > 0:
                print(f"waiting up to {args.wait:g}s for a browser to connect", flush=True)
            await replay(
                run_dir,
                broadcaster,
                delay=args.delay,
                limit=args.limit,
                wait_for_client=args.wait,
            )
            print("replay finished; the dashboard stays up until Ctrl-C", flush=True)
            await server  # keep serving
        finally:
            server.cancel()
            # uvicorn re-raises the signal it captured once it has shut down; by then we are
            # already on our way out, so that second KeyboardInterrupt is nothing but noise.
            with contextlib.suppress(asyncio.CancelledError, KeyboardInterrupt):
                await server  # let uvicorn shut down before the process exits

    # A plain `kill` (SIGTERM) is how a supervisor stops a replay. Point it at the SIGINT handler
    # so it becomes the KeyboardInterrupt below and shutdown still runs cleanly.
    with contextlib.suppress(ValueError):  # not the main thread (a test runner)
        signal.signal(signal.SIGTERM, signal.getsignal(signal.SIGINT))
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass
    return 0


def _lan_address() -> str:
    """This machine's address on the network it routes through, or loopback if it has none. The
    UDP socket is never sent on: connect() only picks the interface the route would use."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 1))  # TEST-NET-1, routed nowhere
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def dashboard_url(host: str, port: int) -> str:
    """The URL to print. `0.0.0.0` means every interface, which is not an address a browser can
    open, so name the address other devices would reach this machine by instead."""
    if host in ("0.0.0.0", "::", ""):
        host = _lan_address()
    return f"http://{host}:{port}"


def build_parser() -> argparse.ArgumentParser:
    # Imported here, not at module scope, so `import jevplays.cli` alone never touches the
    # brain/executor/pyboy stack (see test_imports.py); build_parser() only runs from main().
    from jevplays.loop import LoopConfig

    parser = argparse.ArgumentParser(prog="jevplays", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="boot the game, walk the intro, serve the dashboard")
    run.add_argument("--rom", type=Path, help="Pokémon Red/Blue ROM (default: $JEVPLAYS_ROM)")
    source = run.add_mutually_exclusive_group()
    source.add_argument("--state", type=Path, help="start from this save state instead of the intro")
    source.add_argument(
        "--resume", type=Path, metavar="RUN_DIR", help="continue a run from its newest checkpoint"
    )
    run.add_argument("--runs-dir", type=Path, default=Path("runs"), help="where new run directories go")
    run.add_argument("--no-log", action="store_true", help="keep no run directory (no log, no checkpoints)")
    run.add_argument("--port", type=int, default=8765)
    run.add_argument(
        "--host",
        default="127.0.0.1",
        help="interface the dashboard listens on; 0.0.0.0 serves it to the local network",
    )
    run.add_argument("--unpaced", action="store_true", help="run the emulator as fast as it can")
    run.add_argument("--no-brain", action="store_true", help="never call TypeSafe; let code decide instead")
    # --goal is the old spelling, kept working: it is the battle brain's free-text objective,
    # not the overworld goal (those come from executor/goals.py and are Jev's to pick).
    run.add_argument(
        "--battle-goal",
        "--goal",
        dest="battle_goal",
        default=LoopConfig().goal,
        help="the objective told to Jev with every battle question",
    )
    run.set_defaults(func=cmd_run)

    state = sub.add_parser("state", help="print the GameState parsed from a save state")
    state.add_argument("state", type=Path)
    state.add_argument("--rom", type=Path, help="Pokémon Red/Blue ROM (default: $JEVPLAYS_ROM)")
    state.set_defaults(func=cmd_state)

    replay = sub.add_parser(
        "replay", help="play a logged run back on the dashboard, no emulator or API key needed"
    )
    replay.add_argument("run_dir", type=Path)
    replay.add_argument("--port", type=int, default=8765)
    replay.add_argument(
        "--host",
        default="127.0.0.1",
        help="interface the dashboard listens on; 0.0.0.0 serves it to the local network",
    )
    replay.add_argument("--delay", type=float, default=1.0, help="seconds between decisions")
    replay.add_argument("--limit", type=int, default=None, help="stop after this many decisions")
    replay.add_argument(
        "--wait",
        type=float,
        default=30.0,
        metavar="SECONDS",
        help="hold the first decision until a browser connects, at most this long (0: start at once)",
    )
    replay.set_defaults(func=cmd_replay)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # --state with --no-log is legitimate (a throwaway run from a save state); --resume with it
    # is not: resuming means writing to the run directory --no-log says to do without. argparse
    # cannot express that with --state already in a mutually exclusive group, so check it here.
    if getattr(args, "resume", None) is not None and getattr(args, "no_log", False):
        parser.error("--no-log cannot be combined with --resume")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
