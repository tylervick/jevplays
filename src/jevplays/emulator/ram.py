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
