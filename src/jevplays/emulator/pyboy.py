"""The one module that imports PyBoy.

Everything else sees an Emulator: ticks, button presses, memory, the screen buffer, and JPEG
frames. Headless by default (window="null"); emulation speed is unlimited so the loop, not the
emulator, decides pacing.
"""

from io import BytesIO
from pathlib import Path

from pyboy import PyBoy

from jevplays.emulator.ram import TILEMAP_HEIGHT, TILEMAP_WIDTH, Memory, read_tilemap
from jevplays.emulator.text import decode_cells

BUTTONS = ("a", "b", "start", "select", "up", "down", "left", "right")


class Emulator:
    def __init__(self, rom: Path, *, window: str = "null") -> None:
        self._py = PyBoy(str(rom), window=window, sound_emulated=False)
        self._py.set_emulation_speed(0)

    def __enter__(self) -> "Emulator":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def title(self) -> str:
        return self._py.cartridge_title

    @property
    def mem(self) -> Memory:
        return self._py.memory

    def tick(self, frames: int = 1, *, render: bool = False) -> int:
        """Advance `frames` frames. Returns the frames spent so the loop can pace wall time."""
        self._py.tick(frames, render, False)
        return frames

    def press(self, button: str, *, hold: int = 8, settle: int = 8) -> int:
        """Hold a button for `hold` frames, then let the game settle for `settle` more."""
        if button not in BUTTONS:
            raise ValueError(f"unknown button {button!r}; expected one of {BUTTONS}")
        self._py.button(button, hold)
        return self.tick(hold + settle)

    def tilemap(self) -> bytes:
        return read_tilemap(self.mem)

    def rows(self) -> list[list[str]]:
        raw = self.tilemap()
        return [decode_cells(raw[r * TILEMAP_WIDTH : (r + 1) * TILEMAP_WIDTH]) for r in range(TILEMAP_HEIGHT)]

    def frame_jpeg(self, quality: int = 80) -> bytes:
        """Render one frame and return it as JPEG bytes (160x144)."""
        self._py.tick(1, True, False)
        buf = BytesIO()
        self._py.screen.image.convert("RGB").save(buf, "JPEG", quality=quality)
        return buf.getvalue()

    def save(self, path: Path) -> None:
        with open(path, "wb") as f:
            self._py.save_state(f)

    def load(self, path: Path) -> None:
        with open(path, "rb") as f:
            self._py.load_state(f)
        self.tick(1)

    def close(self) -> None:
        self._py.stop(save=False)
