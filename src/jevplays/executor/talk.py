"""Walk up to a sprite, face it, press A, and read through what it says."""

from jevplays.executor.dialog import skip_dialog
from jevplays.executor.navigate import goto_far
from jevplays.state.snapshot import GameState, Sprite

FACING_OFFSET = {"up": (0, 1), "down": (0, -1), "left": (1, 0), "right": (-1, 0)}
"""Where the player stands relative to the sprite for each facing direction."""


def find_sprite(state: GameState, picture: int | None = None, slot: int | None = None) -> Sprite | None:
    for s in state.sprites:
        if (picture is None or s.picture == picture) and (slot is None or s.slot == slot):
            return s
    return None


def adjacent_tile(sprite: Sprite, face: str) -> tuple[int, int]:
    dx, dy = FACING_OFFSET[face]
    return sprite.x + dx, sprite.y + dy


def talk_to(emu, x: int, y: int, face: str, *, answer=None, patience: int = 60) -> bool:
    if not goto_far(emu, x, y):
        return False
    emu.press(face, hold=4, settle=12)
    emu.press("a", settle=60)
    return skip_dialog(emu, answer=answer, patience=patience) or True
