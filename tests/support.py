"""Fakes shared by the unit tests. Nothing here imports pyboy."""

from pathlib import Path

from jevplays.emulator.ram import (
    COLLISION_END,
    CONNECTION_BITS,
    CONNECTION_MAP_ADDRESSES,
    MAP_BORDER_BLOCKS,
    MON_HP,
    MON_LEVEL,
    MON_MAX_HP,
    MON_MOVES,
    MON_PP,
    MON_STATUS,
    MON_TYPE1,
    MON_TYPE2,
    SPRITE_COORD_OFFSET,
    SPRITE_SLOT_SIZE,
    TILEMAP_HEIGHT,
    TILEMAP_SIZE,
    TILEMAP_WIDTH,
    wCurMapHeight,
    wCurMapWidth,
    wGrassTile,
    wMapConnections,
    wNumberOfWarps,
    wOverworldMap,
    wSpriteStateData1,
    wSpriteStateData2,
    wTileMap,
    wTilesetBank,
    wTilesetBlocksPtr,
    wTilesetCollisionPtr,
    wWarpEntries,
    wXCoord,
    wYCoord,
)
from jevplays.emulator.text import NON_TEXT, encode
from jevplays.executor.maps import PALLET_TOWN
from jevplays.state.modes import Mode
from jevplays.state.snapshot import GameState, Mon, Move

OVERWORLD_LEAD = Mon(
    name="CHARMANDER",
    nickname="CHARMANDER",
    level=5,
    types=("Fire",),
    hp=19,
    max_hp=19,
    status="none",
    moves=(Move("SCRATCH", "Normal", 40, 35, 35),),
)


def overworld_state(
    map_id=PALLET_TOWN, x=5, y=6, flags=(), party=(OVERWORLD_LEAD,), bag=(), money=3000, sprites=()
) -> GameState:
    """A minimal overworld GameState for tests that don't need the emulator, e.g. goal tables
    and the goal/prompt/menu brain. `party` defaults to a single level-5 CHARMANDER."""
    return GameState(
        mode=Mode.OVERWORLD,
        map_id=map_id,
        map="x",
        tile=(x, y),
        player_name="RED",
        party_count=len(party),
        badges=0,
        money=money,
        bag_count=len(bag),
        bag=tuple(bag),
        in_battle=False,
        text="",
        menu_items=(),
        cursor=None,
        party=tuple(party),
        active=None,
        active_slot=None,
        enemy=None,
        battle=None,
        flags=frozenset(flags),
        sprites=tuple(sprites),
        map_size=(20, 18),
    )


class FakeMemory:
    """64 KiB of zeros with PyBoy's memory indexing: an int gives a byte, a slice gives a list."""

    def __init__(self) -> None:
        self.data = bytearray(0x10000)
        self.rom: dict[tuple[int, int], int] = {}

    def __getitem__(self, key: int | slice | tuple[int, int]) -> int | list[int]:
        if isinstance(key, tuple):
            return self.rom.get(key, 0)
        if isinstance(key, slice):
            return list(self.data[key])
        return self.data[key]

    def __setitem__(self, key: int | slice, value: int | bytes | list[int]) -> None:
        if isinstance(key, slice):
            self.data[key] = bytes(value)
        else:
            self.data[key] = value


MAP_TILE = 0x10
"""A tile id that is map graphics, not font: what "·" in a fixture row becomes."""

GRASS_TILE = 0x52
"""The tall-grass tile id `install_map` writes for a "~" block (Route 1's real one)."""


def tilemap_bytes(lines: list[str]) -> bytes:
    """Encode fixture rows into a wTileMap buffer. "·" is a map tile; short rows are padded with it."""
    out = bytearray()
    for r in range(TILEMAP_HEIGHT):
        line = lines[r] if r < len(lines) else ""
        for c in range(TILEMAP_WIDTH):
            ch = line[c] if c < len(line) else NON_TEXT
            out.append(MAP_TILE if ch == NON_TEXT else encode(ch)[0])
    assert len(out) == TILEMAP_SIZE
    return bytes(out)


def write_tilemap(mem: FakeMemory, lines: list[str]) -> None:
    mem[wTileMap : wTileMap + TILEMAP_SIZE] = tilemap_bytes(lines)


def rows_from(lines: list[str]) -> list[list[str]]:
    """Fixture rows as the cell lists detect() and snapshot() work on."""
    padded = [(line + NON_TEXT * TILEMAP_WIDTH)[:TILEMAP_WIDTH] for line in lines]
    padded += [NON_TEXT * TILEMAP_WIDTH] * (TILEMAP_HEIGHT - len(padded))
    return [list(line) for line in padded]


class FakeEmulator:
    """Enough of Emulator for snapshot() and Loop: memory, a screen buffer, and recorded input."""

    def __init__(self) -> None:
        self.mem = FakeMemory()
        self.presses: list[str] = []
        self.frames = 0
        self.grid = [[1] * 10 for _ in range(9)]
        self.step_effects = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
        self.saves = 0
        self.set_rows([])

    def set_rows(self, lines: list[str]) -> None:
        write_tilemap(self.mem, lines)

    def set_sprites(self, specs: list[tuple[int, int, int, int]]) -> None:
        """Write sprite table entries. specs: [(slot, picture, x, y), ...]."""
        # Zero both sprite tables for slots 1..15
        for slot in range(1, 16):
            addr1 = wSpriteStateData1 + SPRITE_SLOT_SIZE * slot
            addr2 = wSpriteStateData2 + SPRITE_SLOT_SIZE * slot
            for i in range(SPRITE_SLOT_SIZE):
                self.mem[addr1 + i] = 0
                self.mem[addr2 + i] = 0
        # Write the specified sprites
        for slot, picture, x, y in specs:
            self.mem[wSpriteStateData1 + SPRITE_SLOT_SIZE * slot] = picture
            base = wSpriteStateData2 + SPRITE_SLOT_SIZE * slot
            self.mem[base + 4] = y + SPRITE_COORD_OFFSET
            self.mem[base + 5] = x + SPRITE_COORD_OFFSET

    def tilemap(self) -> bytes:
        return bytes(self.mem.data[wTileMap : wTileMap + TILEMAP_SIZE])

    def tick(self, frames: int = 1, *, render: bool = False) -> int:
        self.frames += frames
        return frames

    def frame_count(self) -> int:
        return self.frames

    def collision(self) -> list[list[int]]:
        return [row[:] for row in self.grid]

    def rom(self, bank: int, addr: int) -> int:
        return self.mem[bank, addr]

    def press(self, button: str, *, hold: int = 8, settle: int = 8) -> int:
        self.presses.append(button)
        if button in self.step_effects:
            dx, dy = self.step_effects[button]
            self.mem[wXCoord] = self.mem[wXCoord] + dx
            self.mem[wYCoord] = self.mem[wYCoord] + dy
        return self.tick(hold + settle)

    def frame_jpeg(self, quality: int = 80) -> bytes:
        return b"\xff\xd8fake"

    def save(self, path) -> None:
        """Stand-in for Emulator.save: distinct bytes per call so checkpoints can be told apart."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"FAKE-STATE:" + str(self.saves).encode())
        self.saves += 1


def write_mon(
    mem,
    base,
    nick_addr,
    *,
    species,
    level,
    hp,
    max_hp,
    types,
    moves,
    pps,
    status=0,
    nickname=None,
    layout="party",
):
    """Write a Pokémon record. layout "party" uses the 0x2C party offsets; "battle" uses the
    in-battle record offsets relative to its species byte (HP at +1, status +4, types +5/+6,
    moves +8, level +14, max HP +15, PP +25) — see ram.py for why the two differ."""
    from jevplays.emulator.text import TERMINATOR

    if layout == "party":
        off = dict(
            hp=MON_HP,
            status=MON_STATUS,
            t1=MON_TYPE1,
            t2=MON_TYPE2,
            moves=MON_MOVES,
            pp=MON_PP,
            level=MON_LEVEL,
            max_hp=MON_MAX_HP,
        )
    else:
        off = dict(hp=1, status=4, t1=5, t2=6, moves=8, pp=25, level=14, max_hp=15)
    mem[base] = species
    mem[base + off["hp"]] = hp >> 8
    mem[base + off["hp"] + 1] = hp & 0xFF
    mem[base + off["status"]] = status
    mem[base + off["t1"]] = types[0]
    mem[base + off["t2"]] = types[1] if len(types) > 1 else types[0]
    for i in range(4):
        mem[base + off["moves"] + i] = moves[i] if i < len(moves) else 0
        mem[base + off["pp"] + i] = pps[i] if i < len(pps) else 0
    mem[base + off["level"]] = level
    mem[base + off["max_hp"]] = max_hp >> 8
    mem[base + off["max_hp"] + 1] = max_hp & 0xFF
    name = encode(nickname or "MON") + [TERMINATOR]
    mem[nick_addr : nick_addr + len(name)] = name


def install_map(emu, rows, warps=(), connections=None, tileset=(25, 0x4000, 0x5000)):
    """A synthetic map for the fake: '.' walkable, '#' wall, '~' tall grass; three blocks in the
    fake ROM. A fixture cell is one grid cell (one 2x2-tile quadrant), so a block is 2x2 fixture
    characters and all four must agree for it to be walkable or grass.

    `tileset` is (bank, blocks_addr, collision_addr). The collision list is written under
    `(0, collision_addr)` when `collision_addr < 0x4000` and under `(bank, collision_addr)`
    otherwise, mirroring how the real game stores it: the fixed home bank for low addresses,
    the tileset's own switchable bank for addresses in the banked window.
    """
    bank, blocks_addr, collision_addr = tileset
    collision_bank = 0 if collision_addr < 0x4000 else bank
    m = emu.mem
    m[wTilesetBank] = bank
    m[wTilesetBlocksPtr] = blocks_addr & 0xFF
    m[wTilesetBlocksPtr + 1] = blocks_addr >> 8
    m[wTilesetCollisionPtr] = collision_addr & 0xFF
    m[wTilesetCollisionPtr + 1] = collision_addr >> 8
    m[wGrassTile] = GRASS_TILE
    for i in range(16):
        m.rom[(bank, blocks_addr + i)] = 1  # block 0: every tile is 1 (walkable)
        m.rom[(bank, blocks_addr + 16 + i)] = 2  # block 1: every tile is 2 (wall)
        m.rom[(bank, blocks_addr + 32 + i)] = GRASS_TILE  # block 2: every tile is tall grass
    m.rom[(collision_bank, collision_addr)] = 1
    m.rom[(collision_bank, collision_addr + 1)] = COLLISION_END
    height, width = len(rows) // 2, len(rows[0]) // 2
    m[wCurMapWidth], m[wCurMapHeight] = width, height
    stride = width + 2 * MAP_BORDER_BLOCKS
    for by in range(-MAP_BORDER_BLOCKS, height + MAP_BORDER_BLOCKS):
        for bx in range(-MAP_BORDER_BLOCKS, width + MAP_BORDER_BLOCKS):
            inside = 0 <= bx < width and 0 <= by < height
            # a block is walkable (or grass) only when all four of its cells agree; anything else,
            # and everything outside the map, is wall
            quad = {rows[by * 2 + qy][bx * 2 + qx] for qy in range(2) for qx in range(2)} if inside else {"#"}
            block = 0 if quad == {"."} else 2 if quad == {"~"} else 1
            m[wOverworldMap + (by + MAP_BORDER_BLOCKS) * stride + (bx + MAP_BORDER_BLOCKS)] = block
    m[wNumberOfWarps] = len(warps)
    for i, (x, y, wid, dest) in enumerate(warps):
        m[wWarpEntries + 4 * i : wWarpEntries + 4 * i + 4] = [y, x, wid, dest]
    flags = 0
    for d, mid in (connections or {}).items():
        flags |= 1 << CONNECTION_BITS[d]
        m[CONNECTION_MAP_ADDRESSES[d]] = mid
    m[wMapConnections] = flags
