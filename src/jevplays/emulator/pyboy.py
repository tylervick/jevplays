"""The one module that imports PyBoy.

Everything else sees an Emulator: ticks, button presses, memory, the screen buffer, and JPEG
frames. Headless by default (window="null"); emulation speed is unlimited so the loop, not the
emulator, decides pacing.
"""

from collections import deque
from io import BytesIO
from pathlib import Path

from pyboy import PyBoy

from jevplays.emulator.ram import TILEMAP_HEIGHT, TILEMAP_WIDTH, Memory, read_tilemap
from jevplays.emulator.text import decode_cells

BUTTONS = ("a", "b", "start", "select", "up", "down", "left", "right")


CAPTURE_BACKLOG = 240
"""Captured frames kept before the oldest are dropped: four seconds at 60Hz, far more than one
batch, so a drain that never comes cannot grow without bound."""


class Emulator:
    def __init__(self, rom: Path, *, window: str = "null") -> None:
        self._py = PyBoy(str(rom), window=window, sound_emulated=False)
        self._py.set_emulation_speed(0)
        self.capture_every = 0
        """Frames between captures while ticking, or 0 for no capture. The loop sets it for a
        run somebody is watching, so the page can be shown the frames a batch passed through
        rather than only the one it ended on (#31)."""
        self._captured: deque[bytes] = deque(maxlen=CAPTURE_BACKLOG)
        self._since_capture = 0
        """Frames ticked since the last capture, carried across calls (#75)."""

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

    def rom(self, bank: int, addr: int) -> int:
        return int(self._py.memory[bank, addr])

    def tick(self, frames: int = 1, *, render: bool = False) -> int:
        """Advance `frames` frames. Returns the frames spent so the loop can pace wall time.

        With `capture_every` set, a frame is rendered and kept every `capture_every` frames of the
        game, counted across calls: walking is ticked 8 and 4 frames at a time, and counting only
        within one call meant a tick shorter than the interval never captured, so a fast run
        showed no walking at all (#75). A capture never costs an emulated frame: the render
        replaces that frame's tick rather than adding one, so the count this returns stays the
        truth the pacing arithmetic depends on.
        """
        if self.capture_every <= 0:
            self._py.tick(frames, render, False)
            return frames
        done = 0
        while done < frames:
            due = max(1, self.capture_every - self._since_capture)  # the interval may have shrunk
            if frames - done < due:
                self._py.tick(frames - done, render, False)
                self._since_capture += frames - done
                break
            if due > 1:
                self._py.tick(due - 1, False, False)
            self._py.tick(1, True, False)
            self._captured.append(self._encode())
            self._since_capture = 0
            done += due
        return frames

    def take_frames(self) -> list[bytes]:
        """Everything captured since the last call, oldest first."""
        out = list(self._captured)
        self._captured.clear()
        return out

    def frame_count(self) -> int:
        return int(self._py.frame_count)

    def _encode(self, quality: int = 80) -> bytes:
        buf = BytesIO()
        self._py.screen.image.convert("RGB").save(buf, "JPEG", quality=quality)
        return buf.getvalue()

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
        return self._encode(quality)

    def save(self, path: Path) -> None:
        with open(path, "wb") as f:
            self._py.save_state(f)

    def load(self, path: Path) -> None:
        with open(path, "rb") as f:
            self._py.load_state(f)
        self.tick(1)

    def collision(self) -> list[list[int]]:
        """Walkable map of the visible screen as 9 rows x 10 columns of 16x16 blocks; the player
        stands at row 4, column 4. 1 is walkable. PyBoy's Gen 1 wrapper derives it from the
        tileset's collision table, so NPCs are not marked."""
        area = self._py.game_wrapper.game_area_collision()
        return [[int(area[r][c]) for c in range(0, 20, 2)] for r in range(0, 18, 2)]

    def close(self) -> None:
        self._py.stop(save=False)
