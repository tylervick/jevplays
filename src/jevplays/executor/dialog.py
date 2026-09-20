"""Pressing through text, and answering yes/no boxes, by reading the screen buffer."""

from collections.abc import Callable

from jevplays.emulator.intro import ARROW_COL, ARROW_ROW, cursor_label
from jevplays.emulator.text import ARROW, NON_TEXT, row_text
from jevplays.state.modes import DIALOG_ROWS, yes_no_at
from jevplays.state.snapshot import rows_of

__all__ = ["answer_prompt", "cursor_label", "dialog_lines", "skip_dialog", "yes_no_open"]


def dialog_lines(rows: list[list[str]]) -> list[str]:
    lines = []
    for r in DIALOG_ROWS:
        line = row_text(c for c in rows[r] if c != ARROW).strip(" " + NON_TEXT)
        if line:
            lines.append(line)
    return lines


def yes_no_open(rows: list[list[str]]) -> bool:
    return yes_no_at(rows) is not None


def answer_prompt(emu, yes: bool) -> None:
    """With a YES/NO box open and the cursor on YES, pick one."""
    if not yes:
        emu.press("down")
    emu.press("a", settle=40)


def skip_dialog(
    emu,
    *,
    answer: Callable[[str], bool] | None = None,
    patience: int = 80,
    nudge_after: int = 15,
    stop_when: Callable[[list[list[str]]], bool] | None = None,
    max_iters: int = 600,
) -> bool:
    """Press A through dialog until it ends. `answer(text)` decides each YES/NO box from the
    dialog text on screen (default: YES). After `nudge_after` idle ticks with text still showing,
    press A anyway (some boxes end without the arrow). Returns True if `stop_when` fired."""
    idle = 0
    for _ in range(max_iters):
        rows = rows_of(emu.tilemap())
        if stop_when is not None and stop_when(rows):
            return True
        if yes_no_open(rows):
            yes = True if answer is None else answer(" ".join(dialog_lines(rows)))
            answer_prompt(emu, yes)
            idle = 0
            continue
        if rows[ARROW_ROW][ARROW_COL] == ARROW:
            emu.press("a", settle=30)
            idle = 0
            continue
        emu.tick(10)
        idle += 1
        if dialog_lines(rows) and idle >= nudge_after:
            emu.press("a", settle=30)
            idle = 0
            continue
        if idle > patience:
            return False
    return False
