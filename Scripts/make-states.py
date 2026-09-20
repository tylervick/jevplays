#!/usr/bin/env -S uv run
"""Write the save states tests/rom/ load, one per Mode the harness detects.

    uv run Scripts/make-states.py [--out states/]

Needs JEVPLAYS_ROM. Each state is a snapshot of the game a few frames into a known screen:

    overworld.state   Red's bedroom, player free to move
    dialog.state      Oak's "Hello there!" with the ▼ arrow waiting for A
    menu.state        the START menu open in the bedroom
    prompt.state      the SAVE yes/no question ("Would you like to SAVE the game?")

Save states are gitignored: they are copies of the game's memory.
"""

import argparse
import os
import sys
from pathlib import Path

from jevplays.emulator.intro import ARROW_COL, ARROW_ROW, cursor_label, walk_intro
from jevplays.emulator.pyboy import Emulator
from jevplays.emulator.text import ARROW
from jevplays.state.modes import yes_no_at


def wait_for(emu: Emulator, condition, *, frames: int = 600, every: int = 5) -> None:
    for _ in range(0, frames, every):
        if condition(emu.rows()):
            return
        emu.tick(every)
    raise SystemExit("timed out waiting for the screen to settle")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=Path(os.environ.get("JEVPLAYS_STATES", "states")))
    args = parser.parse_args(argv)
    rom = os.environ.get("JEVPLAYS_ROM")
    if not rom:
        print("JEVPLAYS_ROM is not set", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)

    with Emulator(Path(rom)) as emu:
        emu.tick(120)
        for _ in range(400):
            if cursor_label(emu.rows()) == "NEW GAME":
                break
            emu.press("start", hold=4, settle=6)
        emu.press("a", settle=60)
        wait_for(emu, lambda rows: rows[ARROW_ROW][ARROW_COL] == ARROW)
        emu.save(args.out / "dialog.state")

    with Emulator(Path(rom)) as emu:
        walk_intro(emu)
        emu.tick(30)
        emu.save(args.out / "overworld.state")

        emu.press("start", settle=30)
        wait_for(emu, lambda rows: cursor_label(rows) == "POKéMON")
        emu.save(args.out / "menu.state")

        for _ in range(3):
            emu.press("down")
        emu.press("a", settle=60)
        # cursor_label would read "YES·IME…" here because the box overlaps the trainer card,
        # so use the same YES/NO detector snapshot() relies on.
        wait_for(emu, lambda rows: yes_no_at(rows) is not None)
        emu.save(args.out / "prompt.state")

    for name in ("dialog", "overworld", "menu", "prompt"):
        print(f"wrote {args.out / name}.state")
    return 0


if __name__ == "__main__":
    sys.exit(main())
