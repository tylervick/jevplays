"""Which kind of moment the game is in, read from its screen buffer and one RAM flag.

The loop (loop.py) acts on the Mode: a decision point (BATTLE_MENU, PROMPT, MENU, OVERWORLD)
is where Jev gets asked; DIALOG and BATTLE_WAIT get an A press; MOVE_LIST gets a B back to
the battle menu; TRANSITION gets a wait.

Detection order matters and is tested: the battle flag wins over anything drawn on screen,
because a battle can show menus and prompts of its own that milestone 2 handles as battle
state; a yes/no box beats a plain menu because both show a cursor; a cursor beats a dialog
box because a menu can sit over one; text in the bottom box means a dialog; anything else is
the overworld.
"""

from enum import StrEnum

from jevplays.emulator.text import CURSOR, SPACE, has_text, row_text


class Mode(StrEnum):
    OVERWORLD = "overworld"
    BATTLE_MENU = "battle_menu"
    BATTLE_WAIT = "battle_wait"
    MOVE_LIST = "move_list"
    DIALOG = "dialog"
    PROMPT = "prompt"
    MENU = "menu"
    TRANSITION = "transition"


DIALOG_ROWS = range(13, 17)
"""The text lines of the standard bottom dialog box (its border is rows 12 and 17)."""
BATTLE_MENU_ROW = 14
"""FIGHT is written on this row of the battle command box."""
MOVE_LIST_ROWS = (13, 14, 15, 16)
"""The four move slots on the FIGHT screen, top to bottom."""


def find_cursor(rows: list[list[str]]) -> tuple[int, int] | None:
    """(row, column) of the first ▶ on screen."""
    for r, cells in enumerate(rows):
        if CURSOR in cells:
            return r, cells.index(CURSOR)
    return None


def yes_no_at(rows: list[list[str]]) -> tuple[int, int] | None:
    """(row, column) of a YES/NO box's cursor column: YES on one row, NO two rows below it."""
    for r in range(len(rows) - 2):
        cells = rows[r]
        for c in range(len(cells) - 3):
            if cells[c] not in (CURSOR, " "):
                continue
            if row_text(cells[c + 1 : c + 4]) == "YES" and row_text(rows[r + 2][c + 1 : c + 3]) == "NO":
                return r, c
    return None


def is_blank(raw: bytes) -> bool:
    """True when nothing at all is drawn: every tile is the space tile or zero (a fade)."""
    return all(b in (0, SPACE) for b in raw)


def detect(rows: list[list[str]], *, in_battle: bool, blank: bool) -> Mode:
    if blank:
        return Mode.TRANSITION
    if yes_no_at(rows) is not None:
        # A YES/NO box outranks the battle flag: the nickname box after a catch and "use next
        # POKéMON?" open while the game still counts itself in battle, and pressing A through
        # them answers YES (the catch bug typed AAAAAAAAAA as a nickname).
        return Mode.PROMPT
    if in_battle:
        if "FIGHT" in row_text(rows[BATTLE_MENU_ROW]):
            return Mode.BATTLE_MENU
        if any(CURSOR in rows[r] for r in MOVE_LIST_ROWS):
            # The move list, open with nothing to finish choosing: A here would use whatever
            # move the cursor is on (#67).
            return Mode.MOVE_LIST
        return Mode.BATTLE_WAIT
    if find_cursor(rows) is not None:
        return Mode.MENU
    if any(has_text(rows[r]) for r in DIALOG_ROWS):
        return Mode.DIALOG
    return Mode.OVERWORLD
