"""`jevplays run` boots the game and serves the dashboard; `jevplays state` inspects a save."""

import argparse
import asyncio
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
        print(f"dashboard: http://127.0.0.1:{args.port}", flush=True)
        with Emulator(rom) as emu:
            if args.state:
                await broadcaster.publish(status_event("running", f"loading {args.state}"))
                emu.load(args.state)
            else:
                await broadcaster.publish(status_event("running", "walking the intro"))
                walk_intro(emu)
            await broadcaster.publish(status_event("running", "idle at the first decision point"))
            loop = Loop(emu, broadcaster, LoopConfig(paced=not args.unpaced))
            try:
                await loop.run()
            finally:
                await broadcaster.publish(status_event("stopped"))
                server.cancel()

    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass
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
