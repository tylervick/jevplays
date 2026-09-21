import pytest

from jevplays.emulator.pyboy import Emulator
from jevplays.state.modes import Mode
from jevplays.state.snapshot import Battle, snapshot


@pytest.mark.parametrize(
    "name, mode",
    [
        ("overworld", Mode.OVERWORLD),
        ("dialog", Mode.DIALOG),
        ("menu", Mode.MENU),
        ("prompt", Mode.PROMPT),
        ("battle_trainer", Mode.BATTLE_MENU),
        ("battle_wild", Mode.BATTLE_MENU),
        ("battle_wait", Mode.BATTLE_WAIT),
        ("route1", Mode.OVERWORLD),
        ("pallet", Mode.OVERWORLD),
        ("prompt_starter", Mode.PROMPT),
        ("viridian", Mode.OVERWORLD),
        ("viridian_center", Mode.OVERWORLD),
        ("mart_parcel", Mode.OVERWORLD),
        ("dex", Mode.OVERWORLD),
        ("mart_dex", Mode.OVERWORLD),
        ("viridian_oldman", Mode.OVERWORLD),
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
        assert state.menu_items == ("POKéMON", "ITEM", "RED", "SAVE", "OPTION", "EXIT")
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


def test_trainer_battle_state(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("battle_trainer"))
        state = snapshot(emu)
        assert state.battle == Battle(kind="trainer", trainer_class="RIVAL1")
        assert state.active.name == "CHARMANDER" and state.active.types == ("Fire",)
        assert [m.name for m in state.active.moves] == ["SCRATCH", "GROWL"]
        assert state.enemy.name == "SQUIRTLE" and state.enemy.level == 5
        assert state.party[0].nickname == "CHARMANDER"
        assert (
            18 <= state.active.max_hp <= 22
        )  # random DVs; the exact value varies between state regenerations


def test_wild_battle_state(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("battle_wild"))
        state = snapshot(emu)
        assert state.battle.kind == "wild"
        # Route 1's wild species depend on the RNG at the encounter frame; both are Normal types.
        assert state.enemy.name in ("RATTATA", "PIDGEY") and "Normal" in state.enemy.types
        assert state.active.name == "CHARMANDER" and state.active.hp == state.active.max_hp


def test_route1_state_carries_flags_and_size(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("route1"))
        state = snapshot(emu)
        assert state.map_size == (20, 36)
        assert "got_starter" in state.flags and "got_pokedex" not in state.flags
        assert all(0 <= s.x < 20 and 0 <= s.y < 36 for s in state.sprites)
