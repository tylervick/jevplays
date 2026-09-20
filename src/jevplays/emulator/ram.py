"""Named WRAM addresses for Pokémon Red, plus decoders for the game's number formats.

Names are pokered's (https://github.com/pret/pokered, ram/wram.asm) so each can be looked up in
the disassembly. Every value was checked against the running game on 2026-09-20 and is pinned by
tests/rom/test_ram.py against a save state.
"""

from collections.abc import Iterable
from typing import Protocol

from jevplays.emulator.text import TERMINATOR, decode_name  # noqa: F401

# The game's own screen buffer: 20 columns x 18 rows of tile ids, copied to VRAM each frame.
# Every menu, dialog box, and battle message is written here first, so it is the one place to
# read on-screen text without scroll math.
wTileMap = 0xC3A0
TILEMAP_WIDTH = 20
TILEMAP_HEIGHT = 18
TILEMAP_SIZE = TILEMAP_WIDTH * TILEMAP_HEIGHT

# Menu state. wCurrentMenuItem is the cursor's index (0-based) and wMaxMenuItem the last index.
wTopMenuItemY = 0xCC24
wTopMenuItemX = 0xCC25
wCurrentMenuItem = 0xCC26
wMaxMenuItem = 0xCC28
wMenuWatchedKeys = 0xCC29

wJoyIgnore = 0xCD6B
# 1 while the START menu (and other overworld menus) has the font loaded into VRAM.
wFontLoaded = 0xCFC4

# 0 outside battle, 1 in a wild battle, 2 in a trainer battle.
wIsInBattle = 0xD057

wPlayerName = 0xD158
NAME_LENGTH = 11  # 10 characters plus the terminator

wPartyCount = 0xD163
wNumBagItems = 0xD31D
wBagItems = 0xD31E
wPlayerMoney = 0xD347  # 3 bytes, packed BCD, big-endian
wRivalName = 0xD34A
wObtainedBadges = 0xD356  # one bit per badge, Boulder Badge is bit 0
wCurMap = 0xD35E
wYCoord = 0xD361
wXCoord = 0xD362
wEventFlags = 0xD747


class Memory(Protocol):
    """What PyBoy's memory view and the test fake have in common."""

    def __getitem__(self, key: int | slice) -> int | list[int]: ...


def bcd_to_int(data: Iterable[int]) -> int:
    """Packed binary-coded decimal, two digits per byte, most significant byte first."""
    value = 0
    for b in data:
        value = value * 100 + (b >> 4) * 10 + (b & 0x0F)
    return value


def read_bytes(mem: Memory, addr: int, n: int) -> bytes:
    return bytes(mem[addr : addr + n])


def read_name(mem: Memory, addr: int) -> str:
    return decode_name(read_bytes(mem, addr, NAME_LENGTH))


def read_tilemap(mem: Memory) -> bytes:
    return read_bytes(mem, wTileMap, TILEMAP_SIZE)


# The two Pokémon in a battle. Ours is a copy of the party slot that is out; the enemy's is
# built when the battle starts. Both use the same in-battle record layout.
wEnemyMonNick = 0xCFDA
wEnemyMonSpecies = 0xCFE5
wEnemyMonHP = 0xCFE6  # u16
wEnemyMonStatus = 0xCFE9
wEnemyMonType1 = 0xCFEA
wEnemyMonType2 = 0xCFEB
wEnemyMonMoves = 0xCFED  # 4 bytes
wEnemyMonLevel = 0xCFF3
wEnemyMonMaxHP = 0xCFF4  # u16
wBattleMonNick = 0xD009
wBattleMonSpecies = 0xD014
wBattleMonHP = 0xD015  # u16
wBattleMonStatus = 0xD018
wBattleMonType1 = 0xD019
wBattleMonType2 = 0xD01A
wBattleMonMoves = 0xD01C  # 4 bytes
wBattleMonLevel = 0xD022
wBattleMonMaxHP = 0xD023  # u16
wBattleMonPP = 0xD02D  # 4 bytes
wTrainerClass = 0xD031

# Party records, 0x2C bytes each, six slots. Offsets within a record:
wPartyMons = 0xD16B
PARTY_MON_SIZE = 0x2C
MON_SPECIES = 0
MON_HP = 1  # u16
MON_STATUS = 4
MON_TYPE1 = 5
MON_TYPE2 = 6
MON_MOVES = 8  # 4 bytes
MON_PP = 29  # 4 bytes; low 6 bits are current PP, top 2 bits PP Ups used
MON_LEVEL = 33
MON_MAX_HP = 34  # u16
wPartyMonNicks = 0xD2B5  # NAME_LENGTH bytes each

BAG_END = 0xFF
"""Terminates the (item id, quantity) pairs at wBagItems."""


def read_u16(mem: Memory, addr: int) -> int:
    return (mem[addr] << 8) | mem[addr + 1]


def status_name(status: int) -> str:
    """The Gen 1 status byte: bits 0-2 sleep turns, 3 poison, 4 burn, 5 freeze, 6 paralysis."""
    if status & 0b0000_0111:
        return "asleep"
    if status & 0b0000_1000:
        return "poisoned"
    if status & 0b0001_0000:
        return "burned"
    if status & 0b0010_0000:
        return "frozen"
    if status & 0b0100_0000:
        return "paralyzed"
    return "none"


def pp_current(pp: int) -> int:
    return pp & 0b0011_1111
