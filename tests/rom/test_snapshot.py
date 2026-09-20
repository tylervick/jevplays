import pytest

from jevplays.emulator.pyboy import Emulator
from jevplays.state.modes import Mode
from jevplays.state.snapshot import snapshot


@pytest.mark.parametrize(
    "name, mode",
    [
        ("overworld", Mode.OVERWORLD),
        ("dialog", Mode.DIALOG),
        ("menu", Mode.MENU),
        ("prompt", Mode.PROMPT),
    ],
)
def test_each_saved_state_is_detected_as_its_mode(rom, state_path, name, mode):
    with Emulator(rom) as emu:
        emu.load(state_path(name))
        assert snapshot(emu).mode is mode


def test_overworld_state_details(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("overworld"))
        state = snapshot(emu)
        assert state.map == "Red's House 2F"
        assert state.player_name == "RED"
        assert state.money == 3000
        assert state.party_count == 0
        assert state.badges == 0


def test_menu_state_lists_the_start_menu(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("menu"))
        state = snapshot(emu)
        assert "SAVE" in state.menu_items
        assert state.cursor == 0


def test_dialog_state_carries_oaks_greeting(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("dialog"))
        assert "Hello there!" in snapshot(emu).text


def test_prompt_state_offers_yes_no(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("prompt"))
        state = snapshot(emu)
        assert state.menu_items == ("YES", "NO")
        assert "SAVE the game?" in state.text
