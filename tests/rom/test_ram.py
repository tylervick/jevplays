"""Pins every address ram.py names against the running game, one save state at a time."""

from jevplays.emulator import ram
from jevplays.emulator.pyboy import Emulator


def test_overworld_addresses(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("overworld"))
        m = emu.mem
        assert m[ram.wCurMap] == 38
        assert m[ram.wXCoord] == 3 and m[ram.wYCoord] == 7
        assert m[ram.wIsInBattle] == 0
        assert m[ram.wPartyCount] == 0
        assert m[ram.wNumBagItems] == 0
        assert m[ram.wObtainedBadges] == 0
        assert ram.bcd_to_int(ram.read_bytes(m, ram.wPlayerMoney, 3)) == 3000
        assert ram.read_name(m, ram.wPlayerName) == "RED"
        assert ram.read_name(m, ram.wRivalName) == "BLUE"
        assert m[ram.wFontLoaded] == 0


def test_menu_addresses(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("menu"))
        m = emu.mem
        assert m[ram.wFontLoaded] == 1
        assert m[ram.wCurrentMenuItem] == 0
        assert m[ram.wMaxMenuItem] >= 4  # POKéMON, ITEM, RED, SAVE, OPTION, EXIT
        assert m[ram.wTopMenuItemX] == 11


def test_prompt_addresses(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("prompt"))
        m = emu.mem
        assert m[ram.wMaxMenuItem] == 1  # YES / NO
        assert m[ram.wTopMenuItemY] == 8
        assert m[ram.wTopMenuItemX] == 1


def test_tilemap_holds_the_screen(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("dialog"))
        # The ▼ arrow blinks (about 16 frames on, 16 off), so give it up to a second to show.
        for _ in range(30):
            if ram.read_tilemap(emu.mem)[16 * ram.TILEMAP_WIDTH + 18] == 0xEE:
                break
            emu.tick(2)
        else:
            raise AssertionError("the ▼ arrow never appeared at row 16, column 18")


def test_trainer_battle_addresses(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("battle_trainer"))
        m = emu.mem
        assert m[ram.wIsInBattle] == 2
        assert m[ram.wTrainerClass] == 25  # RIVAL1
        assert m[ram.wBattleMonSpecies] == 176 and m[ram.wEnemyMonSpecies] == 177
        assert ram.read_u16(m, ram.wBattleMonHP) == ram.read_u16(m, ram.wBattleMonMaxHP) == 20
        assert ram.read_u16(m, ram.wEnemyMonMaxHP) == 20 and m[ram.wEnemyMonLevel] == 5
        assert (m[ram.wBattleMonType1], m[ram.wEnemyMonType1]) == (20, 21)  # Fire, Water
        assert ram.read_bytes(m, ram.wBattleMonMoves, 4) == bytes([10, 45, 0, 0])
        assert ram.read_bytes(m, ram.wBattleMonPP, 4) == bytes([35, 40, 0, 0])
        assert ram.read_name(m, ram.wEnemyMonNick) == "SQUIRTLE"
        slot = ram.wPartyMons
        assert m[slot + ram.MON_SPECIES] == 176 and m[slot + ram.MON_LEVEL] == 5
        assert ram.read_u16(m, slot + ram.MON_MAX_HP) == 20
        assert ram.read_name(m, ram.wPartyMonNicks) == "CHARMANDER"


def test_wild_battle_addresses(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("battle_wild"))
        m = emu.mem
        assert m[ram.wIsInBattle] == 1
        assert m[ram.wEnemyMonSpecies] == 36
        assert (m[ram.wEnemyMonType1], m[ram.wEnemyMonType2]) == (0, 2)
        assert m[ram.wNumBagItems] == 0
