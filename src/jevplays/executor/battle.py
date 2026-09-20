"""Button macros for the battle screens. Every A is preceded by reading the cursor's label."""

from jevplays.brain.decision import BattleAction
from jevplays.emulator.text import CURSOR, NON_TEXT, row_text
from jevplays.executor.dialog import cursor_label
from jevplays.state.snapshot import rows_of

COMMANDS = {"FIGHT": (0, 0), "PKMN": (0, 1), "ITEM": (1, 0), "RUN": (1, 1)}
"""(row, column) of each command in the 2x2 battle menu. The PKMN command is drawn as the two
glyph tiles PK and MN, which decode to "PK" and "MN" and join as "PKMN"."""

MOVE_ROWS = (13, 14, 15, 16)
"""The four move slots on the FIGHT screen, top to bottom."""


class MacroError(RuntimeError):
    pass


def _label(emu) -> str | None:
    return cursor_label(rows_of(emu.tilemap()))


def select_command(emu, label: str) -> None:
    if label not in COMMANDS:
        raise MacroError(f"unknown battle command {label!r}")
    target_row, target_col = COMMANDS[label]
    for _ in range(6):
        current = _label(emu)
        if current is not None and current.startswith(label):
            emu.press("a", settle=40)
            return
        here = next((pos for name, pos in COMMANDS.items() if current and current.startswith(name)), None)
        if here is None:
            raise MacroError(f"not at the battle menu; cursor reads {current!r}")
        row, col = here
        if col != target_col:
            emu.press("right" if target_col > col else "left", settle=16)
        elif row != target_row:
            emu.press("down" if target_row > row else "up", settle=16)
    raise MacroError(f"could not reach {label!r}")


def _move_row_label(row: list[str]) -> str:
    return row_text(row).strip(" " + NON_TEXT + CURSOR)


def select_move(emu, name: str) -> None:
    rows = rows_of(emu.tilemap())
    slots = [_move_row_label(rows[r]) for r in MOVE_ROWS]
    if name not in slots:
        emu.press("b", settle=20)
        raise MacroError(f"move {name!r} is not in the list")
    i = slots.index(name)
    c = next(k for k, r in enumerate(MOVE_ROWS) if CURSOR in rows[r])
    button = "down" if i > c else "up"
    for _ in range(abs(i - c)):
        emu.press(button, settle=16)
    if _label(emu) != name:
        emu.press("b", settle=20)
        raise MacroError(f"move {name!r} is not in the list")
    emu.press("a", settle=20)


def run_away(emu) -> None:
    select_command(emu, "RUN")


def apply(emu, action: BattleAction) -> None:
    if action.kind == "move":
        select_command(emu, "FIGHT")
        select_move(emu, action.move)
    elif action.kind == "run":
        run_away(emu)
    else:
        raise MacroError("unsupported")
