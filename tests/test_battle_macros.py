import pytest

from jevplays.brain.decision import BattleAction
from jevplays.executor.battle import MacroError, apply, select_command, select_move
from tests.support import FakeEmulator

MENU = [""] * 14 + ["·       ·▶FIGHT PK·", "", "·       · ITEM RUN·"]
MENU_PKMN = [""] * 14 + ["·       · FIGHT▶PKMN", "", "·       · ITEM RUN·"]
MENU_RUN = [""] * 14 + ["·       · FIGHT PK·", "", "·       · ITEM▶RUN·"]
MOVES = [""] * 13 + [
    "·   ·▶SCRATCH      ·",
    "·   · GROWL        ·",
    "·   · -            ·",
    "·   · -            ·",
]
MOVES_GROWL = [""] * 13 + [
    "·   · SCRATCH      ·",
    "·   ·▶GROWL        ·",
    "·   · -            ·",
    "·   · -            ·",
]


class ScriptedEmulator(FakeEmulator):
    """Each press advances a script of screens so macros can be tested without a ROM."""

    def __init__(self, screens):
        super().__init__()
        self.step_effects = {}
        self.screens = list(screens)
        self.set_rows(self.screens.pop(0))

    def press(self, button, *, hold=8, settle=8):
        super().press(button, hold=hold, settle=settle)
        if self.screens:
            self.set_rows(self.screens.pop(0))
        return hold + settle


def test_select_command_moves_the_cursor_then_presses_a():
    emu = ScriptedEmulator([MENU, MENU_PKMN, MENU_RUN, MENU_RUN])  # right -> PKMN, down -> RUN, then A
    select_command(emu, "RUN")
    assert emu.presses == ["right", "down", "a"]


def test_select_move_scrolls_to_the_named_move():
    emu = ScriptedEmulator([MOVES, MOVES_GROWL, MOVES_GROWL])
    select_move(emu, "GROWL")
    assert emu.presses == ["down", "a"]


def test_select_move_fails_closed_when_the_move_is_missing():
    emu = ScriptedEmulator([MOVES] * 8)
    with pytest.raises(MacroError):
        select_move(emu, "EMBER")
    assert emu.presses[-1] == "b"


def test_moves_on_growl_select_scratch():
    """When the cursor starts below the target move, select_move presses up, not down."""
    emu = ScriptedEmulator([MOVES_GROWL, MOVES, MOVES])
    select_move(emu, "SCRATCH")
    assert emu.presses == ["up", "a"]


def test_apply_move_goes_through_fight():
    emu = ScriptedEmulator([MENU, MOVES, MOVES, MOVES])
    apply(emu, BattleAction(kind="move", move="SCRATCH"))
    assert emu.presses == ["a", "a"]


def test_apply_rejects_unsupported_kinds():
    emu = ScriptedEmulator([MENU])
    with pytest.raises(MacroError):
        apply(emu, BattleAction(kind="switch", target="PIDGEY"))
