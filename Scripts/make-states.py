#!/usr/bin/env -S uv run
"""Write the save states tests/rom/ load, one per Mode the harness detects.

    uv run Scripts/make-states.py [--out states/] [--only NAME]

Needs JEVPLAYS_ROM. Each state is a snapshot of the game a few frames into a known screen:

    overworld.state       Red's bedroom, player free to move
    dialog.state          Oak's "Hello there!" with the ▼ arrow waiting for A
    menu.state            the START menu open in the bedroom
    prompt.state          the SAVE yes/no question ("Would you like to SAVE the game?")
    route1.state          Route 1, overworld, Charmander in party
    battle_trainer.state  the rival battle, FIGHT menu open
    battle_wait.state     mid-turn text after choosing SCRATCH
    battle_wild.state     a wild battle, FIGHT menu open

Save states are gitignored: they are copies of the game's memory.
"""

import argparse
import os
import sys
from pathlib import Path

from jevplays.emulator import ram
from jevplays.emulator.intro import ARROW_COL, ARROW_ROW, cursor_label, walk_intro
from jevplays.emulator.pyboy import Emulator
from jevplays.emulator.text import ARROW
from jevplays.executor.dialog import skip_dialog
from jevplays.executor.navigate import goto, step
from jevplays.state.modes import yes_no_at
from jevplays.state.snapshot import rows_of

MILESTONE_1_STATES = ("overworld", "dialog", "menu", "prompt")
BATTLE_STATES = ("route1", "battle_trainer", "battle_wait", "battle_wild")


def wait_for(emu: Emulator, condition, *, frames: int = 600, every: int = 5) -> None:
    for _ in range(0, frames, every):
        if condition(emu.rows()):
            return
        emu.tick(every)
    raise SystemExit("timed out waiting for the screen to settle")


def fight_menu_open(emu) -> bool:
    rows = rows_of(emu.tilemap())
    return "FIGHT" in "".join(rows[14]) and rows[16][18] != "▼"


def wait_for_fight_menu(emu, frames: int = 3000) -> None:
    for _ in range(0, frames, 10):
        if emu.mem[ram.wIsInBattle] == 0 or fight_menu_open(emu):
            return
        rows = rows_of(emu.tilemap())
        if rows[16][18] == "▼" or any("".join(r).strip("· ") for r in rows[13:17]):
            emu.press("a", settle=30)
        else:
            emu.tick(10)
    raise SystemExit("the FIGHT menu never opened")


def play_one_turn(emu) -> None:
    """At the FIGHT menu: FIGHT, then the first move."""
    emu.press("a", settle=40)
    emu.press("a", settle=20)


def finish_battle(emu, max_turns: int = 40) -> None:
    for _ in range(max_turns):
        if emu.mem[ram.wIsInBattle] == 0:
            return
        wait_for_fight_menu(emu)
        if emu.mem[ram.wIsInBattle] == 0:
            return
        play_one_turn(emu)
        emu.tick(30)
    raise SystemExit("the battle did not end")


def starter_answer(text: str) -> bool:
    return "nickname" not in text.lower()


def make_battle_states(rom: Path, out: Path) -> None:
    with Emulator(rom) as emu:
        emu.load(out / "overworld.state")
        assert goto(emu, 7, 1), "bedroom stairs"
        emu.tick(60)
        assert goto(emu, 3, 7), "front door mat"
        step(emu, "down", settle=30)
        emu.tick(60)
        assert emu.mem[ram.wCurMap] == 0, "Pallet Town"
        assert goto(emu, 10, 1), "route 1 edge"
        emu.tick(90)
        skip_dialog(
            emu,
            patience=150,
            stop_when=lambda rows: (
                emu.mem[ram.wCurMap] == 40 and not any("".join(r).strip("· ") for r in rows[13:17])
            ),
        )
        emu.tick(120)
        skip_dialog(emu, patience=60)
        assert emu.mem[ram.wCurMap] == 40, "Oak's lab"
        assert goto(emu, 6, 4), "below Charmander's ball"
        emu.press("up", hold=4, settle=12)
        emu.press("a", settle=60)
        skip_dialog(
            emu,
            answer=starter_answer,
            patience=40,
            stop_when=lambda rows: emu.mem[ram.wPartyCount] == 1,
        )
        skip_dialog(emu, answer=starter_answer, patience=40)
        assert emu.mem[ram.wPartyCount] == 1, "took Charmander"
        goto(emu, 4, 11)  # the rival interrupts before the door is reached
        skip_dialog(emu, patience=60, stop_when=lambda rows: emu.mem[ram.wIsInBattle] != 0)
        wait_for_fight_menu(emu)
        assert emu.mem[ram.wIsInBattle] == 2, "trainer battle"
        emu.save(out / "battle_trainer.state")
        play_one_turn(emu)
        emu.tick(30)
        emu.save(out / "battle_wait.state")
        finish_battle(emu)
        skip_dialog(emu, answer=lambda text: False, patience=60)
        assert goto(emu, 4, 11), "lab door"
        step(emu, "down", settle=30)
        emu.tick(30)
        step(emu, "left")
        step(emu, "left")
        assert goto(emu, 10, 2) and goto(emu, 10, 1), "pallet north"
        step(emu, "up", settle=30)
        step(emu, "up", settle=30)
        emu.tick(60)
        assert emu.mem[ram.wCurMap] == 12, "Route 1"
        emu.save(out / "route1.state")
        pattern = ["up", "up", "left", "up", "right", "up", "left", "up", "right", "up"]
        for i in range(300):
            if emu.mem[ram.wIsInBattle] == 1:
                break
            direction = pattern[i % len(pattern)]
            if not step(emu, direction, settle=12):
                step(emu, "right" if direction == "left" else "left", settle=12)
        else:
            raise SystemExit("no wild encounter on Route 1")
        wait_for_fight_menu(emu)
        emu.save(out / "battle_wild.state")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=Path(os.environ.get("JEVPLAYS_STATES", "states")))
    parser.add_argument("--only", choices=MILESTONE_1_STATES + BATTLE_STATES, default=None)
    args = parser.parse_args(argv)
    rom = os.environ.get("JEVPLAYS_ROM")
    if not rom:
        print("JEVPLAYS_ROM is not set", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)

    run_milestone_1 = args.only is None or args.only in MILESTONE_1_STATES
    run_battles = args.only is None or args.only in BATTLE_STATES

    if run_milestone_1:
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

        for name in MILESTONE_1_STATES:
            print(f"wrote {args.out / name}.state")

    if run_battles:
        make_battle_states(Path(rom), args.out)
        for name in BATTLE_STATES:
            print(f"wrote {args.out / name}.state")

    return 0


if __name__ == "__main__":
    sys.exit(main())
