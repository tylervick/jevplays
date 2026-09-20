"""`jevplays run` boots the game and serves the dashboard; `jevplays state` inspects a save."""

import argparse
import asyncio
import contextlib
import json
import os
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
    # Imported after the ROM check so a run without a ROM (CI) never loads PyBoy and SDL.
    from jevplays.emulator.pyboy import Emulator
    from jevplays.state.snapshot import snapshot

    with Emulator(rom) as emu:
        emu.load(args.state)
        print(json.dumps(snapshot(emu).to_dict(), indent=2, ensure_ascii=False))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    rom = args.rom or _rom_from_env()
    if rom is None:
        print("no ROM: pass --rom or set JEVPLAYS_ROM", file=sys.stderr)
        return 2
    from jevplays.dashboard.events import status_event
    from jevplays.dashboard.server import Broadcaster, create_app, serve
    from jevplays.emulator.intro import walk_intro
    from jevplays.emulator.pyboy import Emulator
    from jevplays.loop import Loop, LoopConfig

    async def main_async() -> None:
        broadcaster = Broadcaster()
        server = asyncio.create_task(serve(create_app(broadcaster), port=args.port))
        try:
            with Emulator(rom) as emu:
                if args.state:
                    await broadcaster.publish(status_event("running", f"loading {args.state}"))
                    emu.load(args.state)
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
                print(f"dashboard: http://127.0.0.1:{args.port}", flush=True)
                await broadcaster.publish(status_event("running", "idle at the first decision point"))
                loop = Loop(emu, broadcaster, LoopConfig(paced=not args.unpaced))
                try:
                    await loop.run()
                finally:
                    await broadcaster.publish(status_event("stopped"))
        finally:
            server.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await server  # let uvicorn shut down before the process exits

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
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jevplays", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="boot the game, walk the intro, serve the dashboard")
    run.add_argument("--rom", type=Path, help="Pokémon Red/Blue ROM (default: $JEVPLAYS_ROM)")
    run.add_argument("--state", type=Path, help="start from this save state instead of the intro")
    run.add_argument("--port", type=int, default=8765)
    run.add_argument("--unpaced", action="store_true", help="run the emulator as fast as it can")
    run.set_defaults(func=cmd_run)

    state = sub.add_parser("state", help="print the GameState parsed from a save state")
    state.add_argument("state", type=Path)
    state.add_argument("--rom", type=Path, help="Pokémon Red/Blue ROM (default: $JEVPLAYS_ROM)")
    state.set_defaults(func=cmd_state)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
