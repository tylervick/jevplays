"""Fakes shared by the unit tests. Nothing here imports pyboy."""

from jevplays.emulator.ram import TILEMAP_HEIGHT, TILEMAP_SIZE, TILEMAP_WIDTH, wTileMap, wXCoord, wYCoord
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
