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

wWalkCounter = 0xCFC5  # frames left in the current tile step; 0 when standing
wJoyIgnore = 0xCD6B
# 1 while the START menu (and other overworld menus) has the font loaded into VRAM.
wFontLoaded = 0xCFC4

# 0 outside battle, 1 in a wild battle, 2 in a trainer battle.
wIsInBattle = 0xD057

wPlayerMonNumber = 0xCC2F  # index of the party slot currently out in battle

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

# Sprites (NPCs, item balls, the player in slot 0). Slot i has its picture id at
# wSpriteStateData1 + 16 * i (0 = empty) and its map position in the second table:
# x = mem[wSpriteStateData2 + 16 * i + 5] - 4, y = mem[... + 4] - 4. Matches pokered's object_event coordinates.
wSpriteStateData1 = 0xC100
wSpriteStateData2 = 0xC200
SPRITE_SLOT_SIZE = 16
SPRITE_SLOTS = 15
SPRITE_COORD_OFFSET = 4

# The current map's block ids, with a 3-block border on every side, so a row is width + 6 blocks.
wOverworldMap = 0xC6E8
MAP_BORDER_BLOCKS = 3

wCurMapTileset = 0xD367
wCurMapHeight = 0xD368  # blocks
wCurMapWidth = 0xD369  # blocks
wMapConnections = 0xD370  # bit 3 north, 2 south, 1 west, 0 east
CONNECTION_BITS = {"north": 3, "south": 2, "west": 1, "east": 0}
CONNECTION_MAP_ADDRESSES = {"north": 0xD371, "south": 0xD37C, "west": 0xD387, "east": 0xD392}
wNumberOfWarps = 0xD3AE
wWarpEntries = 0xD3AF  # 4 bytes each: y, x, warp id, destination map
WARP_ENTRY_SIZE = 4
WARP_LAST_MAP = 0xFF  # destination "the map we came from"
wLastMap = 0xD365  # the map a WARP_LAST_MAP warp leads back to

# Tileset tables in ROM: blocks are 16 tile ids (4x4, row-major); the collision list is the
# walkable tile ids, 0xFF-terminated; the grass tile is walkable too when it is not 0xFF.
wTilesetBank = 0xD52B
wTilesetBlocksPtr = 0xD52C  # little-endian ROM address
wTilesetCollisionPtr = 0xD530
wGrassRate = 0xD887  # how often this map's grass starts a battle; 0 means no wild Pokémon live here
wGrassTile = 0xD535
TILE_PAIR_COLLISIONS_LAND = 0x0C7E
"""ROM bank 0: (tileset, tile, tile) triples, 0xFF-terminated. A step between those two tiles is
blocked though both are walkable: a cave's raised floor against its lower floor (Mt. Moon)."""
TILE_PAIR_ENTRY_SIZE = 3
TILE_PAIR_MAX_ENTRIES = 32  # the table holds 11; a bound against reading past it
COLLISION_END = 0xFF


class Memory(Protocol):
    """What PyBoy's memory view and the test fake have in common: an int key reads WRAM; a
    `(bank, addr)` tuple reads ROM."""

    def __getitem__(self, key: int | slice | tuple[int, int]) -> int | list[int]: ...


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
wPlayerDisabledMove = 0xD06D
"""pokered's `wPlayerDisabledMove`: high nibble the 1-based slot of our disabled move, low nibble
the turns DISABLE has left; 0 when none is. Checked against two checkpoints: 0x33 was EMBER (slot
3) and 0x13 was SCRATCH (slot 1), which the game confirmed with "The move is disabled!" when
SCRATCH was picked. A disabled move chosen at the menu is refused without a turn passing, so the
counter never runs down while it keeps being chosen (#140)."""

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


def read_u16le(mem: Memory, addr: int) -> int:
    return mem[addr] | (mem[addr + 1] << 8)


def flag_bit(mem: Memory, index: int) -> bool:
    return bool((mem[wEventFlags + index // 8] >> (index % 8)) & 1)


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


TOWN_MAP_BANK = 0x1C
TOWN_MAP_OUTDOOR = 0x5313
"""pokered's `ExternalMapEntries`: one entry per outdoor map (ids below `FIRST_INDOOR_MAP`), in
id order: a byte packing the map's town-map cell as (row << 4) | column, then a pointer to its
name. Read off the ROM (#136): Pallet Town is (2, 11), Cerulean City (10, 2)."""
TOWN_MAP_OUTDOOR_ENTRY_SIZE = 3
TOWN_MAP_INDOOR = 0x5382
"""pokered's `InternalMapEntries`, right after the outdoor table: ranges of indoor map ids in
ascending order, each a byte holding the first map id *past* the range, the packed cell, and a
name pointer. The game takes the first range whose end the map id is below; the last ends at
0xFF."""
TOWN_MAP_INDOOR_ENTRY_SIZE = 4
TOWN_MAP_INDOOR_END = 0xFF
TOWN_MAP_INDOOR_MAX_ENTRIES = 128  # the table holds 62; a bound against reading past it
FIRST_INDOOR_MAP = 37  # REDS_HOUSE_1F

MART_SCRIPT = 0xFE
"""The first byte of a Mart's inventory in the ROM (pokered's `script_mart`): then a count, that
many item ids, and 0xFF."""
MART_INVENTORIES: dict[int, int] = {42: 0x2442, 56: 0x2449, 67: 0x2453}
"""Map id -> the bank-0 address of that Mart's inventory, read off the ROM (#110): the Viridian Mart
(POKE BALL, ANTIDOTE, PARLYZ HEAL, BURN HEAL), the Pewter Mart (POKE BALL, POTION, ESCAPE ROPE,
ANTIDOTE, BURN HEAL, AWAKENING, PARLYZ HEAL) and the Cerulean Mart, the table's third entry (POKE
BALL, POTION, REPEL, ANTIDOTE, BURN HEAL, AWAKENING, PARLYZ HEAL), the shelves
`tests/rom/test_shop.py` checks. Marts further on are added when a run can reach them."""
