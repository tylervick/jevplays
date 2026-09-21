"""Button macros for the battle screens. Every A is preceded by reading the cursor's label."""

from jevplays.brain.decision import BattleAction
from jevplays.emulator.text import CURSOR, NON_TEXT, row_text
from jevplays.executor.dialog import cursor_label, wait_for
from jevplays.state.snapshot import rows_of

COMMANDS = {"FIGHT": (0, 0), "PKMN": (0, 1), "ITEM": (1, 0), "RUN": (1, 1)}
"""(row, column) of each command in the 2x2 battle menu. The PKMN command is drawn as the two
glyph tiles PK and MN, which decode to "PK" and "MN" and join as "PKMN"."""

MOVE_ROWS = (13, 14, 15, 16)
"""The four move slots on the FIGHT screen, top to bottom."""

ITEM_ROWS = (4, 6, 8)
"""The visible item slots in the bag list. The list scrolls after three entries; select_item
walks the cursor with `down` and re-reads rather than indexing this tuple, bounded to 20 presses."""

PARTY_ROWS = (1, 3, 5, 7, 9, 11)
"""The HP row of each party slot: slot i's name is on row 2*i, its HP (and the cursor) on
row 2*i + 1."""

SWITCH_ROW = 12
"""The SWITCH option in the sub-menu that opens after choosing a party slot from PKMN."""


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


def _text(rows: list[list[str]]) -> str:
    return " ".join(row_text(r) for r in rows)


def select_move(emu, name: str) -> None:
    rows = rows_of(emu.tilemap())
    slots = [_move_row_label(rows[r]) for r in MOVE_ROWS]
    if name not in slots:
        emu.press("b", settle=20)
        raise MacroError(f"move {name!r} is not in the list")
    i = slots.index(name)
    c = next((k for k, r in enumerate(MOVE_ROWS) if CURSOR in rows[r]), None)
    if c is None:
        emu.press("b", settle=20)
        raise MacroError("cursor not found in the move list")
    button = "down" if i > c else "up"
    for _ in range(abs(i - c)):
        emu.press(button, settle=16)
    if _label(emu) != name:
        emu.press("b", settle=20)
        raise MacroError(f"move {name!r} is not in the list")
    emu.press("a", settle=20)


def run_away(emu) -> None:
    select_command(emu, "RUN")


def select_item(emu, name: str) -> None:
    """Open ITEM and walk the cursor down to the entry whose label starts with `name`, then
    press A. Bounded to 20 presses (the list scrolls after three visible slots); backs out with
    two B presses and raises MacroError when the item is never found."""
    select_command(emu, "ITEM")
    for _ in range(20):
        current = _label(emu)
        if current is not None and current.startswith(name):
            emu.press("a", settle=40)
            return
        emu.press("down", settle=16)
    emu.press("b", settle=20)
    emu.press("b", settle=20)
    raise MacroError(f"item {name!r} is not in the list")


def throw_ball(emu) -> None:
    select_item(emu, "POKé BALL")


def use_potion(emu, slot: int) -> None:
    select_item(emu, "POTION")
    if not wait_for(emu, lambda rows: "Use item on which" in _text(rows), frames=300):
        raise MacroError("the item target screen never opened")
    rows = rows_of(emu.tilemap())
    c = next((k for k, r in enumerate(PARTY_ROWS) if CURSOR in rows[r]), None)
    if c is None:
        raise MacroError("cursor not found in the party list")
    button = "down" if slot > c else "up"
    for _ in range(abs(slot - c)):
        emu.press(button, settle=16)
    emu.press("a", settle=40)
    rows = rows_of(emu.tilemap())
    if "won't have any" in _text(rows):
        emu.press("b", settle=20)
        emu.press("b", settle=20)
        raise MacroError("the Potion had no effect")


def switch_to(emu, slot: int) -> None:
    select_command(emu, "PKMN")
    if not wait_for(emu, lambda rows: "Choose a POKéMON" in _text(rows), frames=300):
        raise MacroError("the party list never opened")
    rows = rows_of(emu.tilemap())
    c = next((k for k, r in enumerate(PARTY_ROWS) if CURSOR in rows[r]), None)
    if c is None:
        raise MacroError("cursor not found in the party list")
    button = "down" if slot > c else "up"
    for _ in range(abs(slot - c)):
        emu.press(button, settle=16)
    emu.press("a", settle=40)
    rows = rows_of(emu.tilemap())
    if "no will" in _text(rows):
        emu.press("b", settle=20)
        emu.press("b", settle=20)
        raise MacroError(f"{slot} has fainted")
    if CURSOR not in rows[SWITCH_ROW]:
        raise MacroError(f"unexpected menu after choosing party slot {slot}")
    emu.press("a", settle=40)


def apply(emu, action: BattleAction, *, active_slot: int = 0) -> None:
    if action.kind == "move":
        select_command(emu, "FIGHT")
        select_move(emu, action.move)
    elif action.kind == "run":
        run_away(emu)
    elif action.kind == "heal":
        use_potion(emu, active_slot)
    elif action.kind == "catch":
        throw_ball(emu)
    elif action.kind == "switch":
        if action.slot is None:
            raise MacroError("switch requires a slot")
        switch_to(emu, action.slot)
    else:
        raise MacroError("unsupported")
