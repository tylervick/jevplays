"""Play a battle with the first move, for scripts and tests that need to get past a fight
without the brain."""

from jevplays.emulator import ram
from jevplays.state.snapshot import rows_of


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
