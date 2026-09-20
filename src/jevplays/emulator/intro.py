"""From power-on to the first step in Red's bedroom, driven by what is on screen.

The intro is a fixed script (title, NEW GAME, Oak's speech, two name menus, the shrink into the
bedroom), but its timing is not, so counting A presses is brittle. Instead each iteration looks
at the screen buffer: a NEW NAME menu gets "down, A" to pick the first preset name (RED, then
BLUE); the blinking "press A" arrow gets an A; once both names are chosen, a test step down that
actually moves the player means the overworld is live. Measured at 92 iterations and 0.2 s.
"""

from jevplays.emulator.ram import wYCoord
from jevplays.emulator.text import ARROW, CURSOR, NON_TEXT, row_text

ARROW_ROW, ARROW_COL = 16, 18
"""Where the ▼ arrow blinks while a dialog box waits for A."""


class IntroError(RuntimeError):
    pass


def cursor_label(rows: list[list[str]]) -> str | None:
    """The text to the right of the first ▶ on screen, or None when there is no cursor."""
    for cells in rows:
        if CURSOR in cells:
            c = cells.index(CURSOR)
            return row_text(cells[c + 1 :]).strip(" " + NON_TEXT)
    return None


def walk_intro(emu, *, max_steps: int = 600) -> int:
    """Press through the intro until the player can move. Returns the iterations it took."""
    emu.tick(120)
    for _ in range(400):
        if cursor_label(emu.rows()) == "NEW GAME":
            break
        emu.press("start", hold=4, settle=6)
    else:
        raise IntroError("the title screen never showed NEW GAME")
    emu.press("a", settle=60)

    names_chosen = 0
    for step in range(max_steps):
        rows = emu.rows()
        if cursor_label(rows) == "NEW NAME":
            emu.press("down")
            emu.press("a", settle=60)
            names_chosen += 1
            continue
        if rows[ARROW_ROW][ARROW_COL] == ARROW:
            emu.press("a", settle=30)
            continue
        if names_chosen == 2:
            y = emu.mem[wYCoord]
            emu.press("down", settle=16)
            if emu.mem[wYCoord] != y:
                return step
        emu.tick(30)
    raise IntroError(f"the intro did not reach the overworld within {max_steps} iterations")
