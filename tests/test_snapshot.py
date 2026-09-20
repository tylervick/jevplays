from jevplays.emulator import ram
from jevplays.emulator.text import encode
from jevplays.state.modes import Mode
from jevplays.state.snapshot import GameState, dialog_text, menu_items, snapshot
from tests.support import FakeEmulator, rows_from


def bedroom(emu: FakeEmulator) -> None:
    emu.mem[ram.wCurMap] = 38
    emu.mem[ram.wXCoord] = 3
    emu.mem[ram.wYCoord] = 7
    emu.mem[ram.wPlayerName : ram.wPlayerName + 4] = encode("RED") + [ram.TERMINATOR]
    emu.mem[ram.wPlayerMoney : ram.wPlayerMoney + 3] = [0x00, 0x30, 0x00]
    emu.mem[ram.wObtainedBadges] = 0b00000101
    emu.mem[ram.wNumBagItems] = 2


def test_snapshot_in_the_overworld():
    emu = FakeEmulator()
    bedroom(emu)
    state = snapshot(emu)
    assert isinstance(state, GameState)
    assert state.mode is Mode.OVERWORLD
    assert state.map_id == 38 and state.map == "Red's House 2F"
    assert state.tile == (3, 7)
    assert state.player_name == "RED"
    assert state.money == 3000
    assert state.badges == 2
    assert state.bag_count == 2
    assert state.party_count == 0
    assert state.in_battle is False
    assert state.text == ""
    assert state.menu_items == ()
    assert state.cursor is None


def test_snapshot_reads_menu_items_and_cursor():
    emu = FakeEmulator()
    bedroom(emu)
    emu.set_rows(
        [
            "····················",
            "···········        ·",
            "···········▶POKéMON·",
            "···········        ·",
            "··········· ITEM   ·",
            "···········        ·",
            "··········· RED    ·",
            "···········        ·",
            "··········· SAVE   ·",
            "···········        ·",
            "··········· OPTION ·",
            "···········        ·",
            "··········· EXIT   ·",
        ]
    )
    emu.mem[ram.wCurrentMenuItem] = 3
    state = snapshot(emu)
    assert state.mode is Mode.MENU
    assert state.menu_items == ("POKéMON", "ITEM", "RED", "SAVE", "OPTION", "EXIT")
    assert state.cursor == 3


def test_snapshot_reads_dialog_text_without_the_arrow():
    emu = FakeEmulator()
    bedroom(emu)
    emu.set_rows(
        [""] * 12
        + [
            "····················",
            "·                  ·",
            "·Hello there!      ·",
            "·                  ·",
            "·Welcome to the   ▼·",
            "····················",
        ]
    )
    state = snapshot(emu)
    assert state.mode is Mode.DIALOG
    assert state.text == "Hello there! Welcome to the"


def test_prompt_items_are_yes_and_no():
    rows = rows_from(["·▶YES·", "·    ·", "· NO ·"])
    assert menu_items(rows, Mode.PROMPT) == ("YES", "NO")


def test_dialog_text_joins_only_the_text_rows():
    rows = rows_from([""] * 13 + ["·First, what is    ·", "·                  ·", "·your name?        ·"])
    assert dialog_text(rows) == "First, what is your name?"


def test_to_dict_is_json_ready():
    emu = FakeEmulator()
    bedroom(emu)
    d = snapshot(emu).to_dict()
    assert d["mode"] == "overworld"
    assert d["tile"] == [3, 7]
    assert d["menu_items"] == []
