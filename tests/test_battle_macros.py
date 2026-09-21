import contextlib

import pytest

from jevplays.brain.decision import BattleAction
from jevplays.executor.battle import (
    MacroError,
    apply,
    select_command,
    select_item,
    select_move,
    switch_to,
    use_potion,
)
from tests.support import FakeEmulator

MENU = [""] * 14 + ["·       ·▶FIGHT PK·", "", "·       · ITEM RUN·"]
MENU_PKMN = [""] * 14 + ["·       · FIGHT▶PKMN", "", "·       · ITEM RUN·"]
MENU_RUN = [""] * 14 + ["·       · FIGHT PK·", "", "·       · ITEM▶RUN·"]
MENU_ITEM = [""] * 14 + ["·       · FIGHT PK·", "", "·       ·▶ITEM RUN·"]
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
MOVES_WITHOUT_CURSOR = [""] * 13 + [
    "·   · SCRATCH      ·",
    "·   · GROWL        ·",
    "·   · -            ·",
    "·   · -            ·",
]

# The battle item list, as the ROM draws it: four blank rows, then the three visible slots.
ITEM_LIST_ROWS = [""] * 4 + [
    "····▶POKé BALL    ·",
    "····         × 5  ·",
    "···· POTION       ·",
    "····         × 3  ·",
    "···· CANCEL       ·",
]
ITEM_LIST_ROWS_POTION = list(ITEM_LIST_ROWS)
ITEM_LIST_ROWS_POTION[4] = ITEM_LIST_ROWS[4][:4] + " " + ITEM_LIST_ROWS[4][5:]
ITEM_LIST_ROWS_POTION[6] = ITEM_LIST_ROWS[6][:4] + "▶" + ITEM_LIST_ROWS[6][5:]

# The party list, as it's drawn after PKMN or after choosing an item to use.
PARTY_LIST_ROWS = (
    [
        "   CHARMANDER·6     ",
        "▶   ········· 22/ 22",
        "   PIDGEY    ·2     ",
        "    ·········  1/ 14",
    ]
    + [""] * 10
    + ["·Choose a POKéMON. ·"]
)
PARTY_LIST_ROWS_SLOT1 = [
    PARTY_LIST_ROWS[0],
    " " + PARTY_LIST_ROWS[1][1:],
    PARTY_LIST_ROWS[2],
    "▶" + PARTY_LIST_ROWS[3][1:],
] + PARTY_LIST_ROWS[4:]
ITEM_PARTY_ROWS = PARTY_LIST_ROWS[:14] + ["·Use item on which ·", "", "·POKéMON?          ·"]
# The real screen shows the outline glyph (▷, not the ▶ cursor) on the party list's row 1 once
# the SWITCH/STATS/CANCEL sub-menu is open, so switch_to's "cursor is on SWITCH" check has to
# look at row 12 specifically rather than the first ▶ on screen.
_SWITCH_MENU_BASE = list(PARTY_LIST_ROWS[:12])
_SWITCH_MENU_BASE[1] = "▷" + _SWITCH_MENU_BASE[1][1:]
SWITCH_MENU_ROWS = _SWITCH_MENU_BASE + [
    "············▶SWITCH·",
    "",
    "·Choose a P· STATS ·",
    "",
    "·          · CANCEL·",
]
NO_EFFECT_ROWS = PARTY_LIST_ROWS[:14] + ["·It won't have any  ·", "", "·effect.           ·"]
FAINTED_ROWS = PARTY_LIST_ROWS[:14] + ["·There's no will    ·", "", "·to fight!        ▼·"]

# A four-item bag (only three slots show at once) so select_item has to scroll to reach the
# fourth. Cursor starts on POKé BALL; down moves it to POTION, then a second down scrolls the
# list so POTION/ANTIDOTE/ETHER are visible with the cursor landing on ETHER.
ITEM_SCROLL_ROWS_0 = [""] * 4 + [
    "····▶POKé BALL    ·",
    "",
    "···· POTION       ·",
    "",
    "···· ANTIDOTE     ·",
]
ITEM_SCROLL_ROWS_1 = [""] * 4 + [
    "···· POKé BALL    ·",
    "",
    "····▶POTION       ·",
    "",
    "···· ANTIDOTE     ·",
]
ITEM_SCROLL_ROWS_2 = [""] * 4 + [
    "···· POTION       ·",
    "",
    "···· ANTIDOTE     ·",
    "",
    "····▶ETHER        ·",
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


def test_select_item_walks_the_cursor_to_the_named_item_and_presses_a():
    # Cursor already on ITEM; A opens the list on POKé BALL, one down reaches POTION.
    emu = ScriptedEmulator([MENU_ITEM, ITEM_LIST_ROWS, ITEM_LIST_ROWS_POTION])
    select_item(emu, "POTION")
    assert emu.presses[-3:] == ["a", "down", "a"]  # A on ITEM, down to POTION, A


def test_select_item_backs_out_when_the_item_is_missing():
    emu = ScriptedEmulator([MENU_ITEM, ITEM_LIST_ROWS])
    with pytest.raises(MacroError):
        select_item(emu, "ANTIDOTE")
    assert emu.presses[-2:] == ["b", "b"]


def test_switch_to_picks_the_slot_and_confirms_switch():
    # Cursor already on PKMN; A opens the party list on slot 0, one down reaches slot 1.
    emu = ScriptedEmulator([MENU_PKMN, PARTY_LIST_ROWS, PARTY_LIST_ROWS_SLOT1, SWITCH_MENU_ROWS])
    switch_to(emu, 1)
    assert emu.presses[-4:] == ["a", "down", "a", "a"]  # PKMN, down to slot 1, slot, SWITCH


def test_use_potion_raises_when_it_has_no_effect():
    emu = ScriptedEmulator(
        [MENU_ITEM, ITEM_LIST_ROWS, ITEM_LIST_ROWS_POTION, ITEM_PARTY_ROWS, NO_EFFECT_ROWS]
    )
    with pytest.raises(MacroError, match="no effect"):
        use_potion(emu, 0)


def test_apply_dispatches_every_kind():
    cases = [
        (BattleAction(kind="catch"), [MENU, MENU_ITEM]),
        (BattleAction(kind="heal"), [MENU, MENU_ITEM]),
        (BattleAction(kind="switch", target="PIDGEY", slot=1), [MENU, MENU_PKMN]),
    ]
    for action, screens in cases:
        emu = ScriptedEmulator(screens)
        with contextlib.suppress(MacroError):
            apply(emu, action, active_slot=0)
        assert "a" in emu.presses


def test_select_move_without_a_cursor_raises_macro_error_not_stop_iteration():
    emu = ScriptedEmulator([MOVES_WITHOUT_CURSOR] * 2)
    with pytest.raises(MacroError, match="cursor"):
        select_move(emu, "SCRATCH")


def test_switch_to_raises_when_the_target_has_fainted():
    emu = ScriptedEmulator([MENU_PKMN, PARTY_LIST_ROWS, FAINTED_ROWS])
    with pytest.raises(MacroError, match="fainted"):
        switch_to(emu, 0)
    assert emu.presses[-2:] == ["b", "b"]


def test_select_item_scrolls_past_the_three_visible_slots():
    emu = ScriptedEmulator([MENU_ITEM, ITEM_SCROLL_ROWS_0, ITEM_SCROLL_ROWS_1, ITEM_SCROLL_ROWS_2])
    select_item(emu, "ETHER")
    assert emu.presses[-3:] == ["down", "down", "a"]
