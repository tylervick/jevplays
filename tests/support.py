"""Fakes shared by the unit tests. Nothing here imports pyboy."""

from jevplays.emulator.ram import (
    MON_HP,
    MON_LEVEL,
    MON_MAX_HP,
    MON_MOVES,
    MON_PP,
    MON_STATUS,
    MON_TYPE1,
    MON_TYPE2,
    TILEMAP_HEIGHT,
    TILEMAP_SIZE,
    TILEMAP_WIDTH,
    wTileMap,
    wXCoord,
    wYCoord,
)
from jevplays.emulator.text import NON_TEXT, encode


class FakeMemory:
    """64 KiB of zeros with PyBoy's memory indexing: an int gives a byte, a slice gives a list."""

    def __init__(self) -> None:
        self.data = bytearray(0x10000)

    def __getitem__(self, key: int | slice) -> int | list[int]:
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
        self.set_rows([])

    def set_rows(self, lines: list[str]) -> None:
        write_tilemap(self.mem, lines)

    def tilemap(self) -> bytes:
        return bytes(self.mem.data[wTileMap : wTileMap + TILEMAP_SIZE])

    def tick(self, frames: int = 1, *, render: bool = False) -> int:
        self.frames += frames
        return frames

    def collision(self) -> list[list[int]]:
        return [row[:] for row in self.grid]

    def press(self, button: str, *, hold: int = 8, settle: int = 8) -> int:
        self.presses.append(button)
        if button in self.step_effects:
            dx, dy = self.step_effects[button]
            self.mem[wXCoord] = self.mem[wXCoord] + dx
            self.mem[wYCoord] = self.mem[wYCoord] + dy
        return self.tick(hold + settle)

    def frame_jpeg(self, quality: int = 80) -> bytes:
        return b"\xff\xd8fake"


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
