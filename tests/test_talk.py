from jevplays.emulator import ram
from jevplays.executor.talk import adjacent_tile, find_sprite, talk_to
from jevplays.state.snapshot import Sprite, snapshot
from tests.support import FakeEmulator, install_map

ROOM = ["......", "......", "......", "......"]


def test_find_sprite_by_picture_and_slot():
    emu = FakeEmulator()
    emu.set_sprites([(1, 41, 3, 1), (5, 3, 5, 2)])
    state = snapshot(emu)
    assert find_sprite(state, picture=3) == Sprite(5, 3, 5, 2)
    assert find_sprite(state, slot=1) == Sprite(1, 41, 3, 1)
    assert find_sprite(state, picture=99) is None


def test_adjacent_tile_is_where_the_player_stands_to_face_the_sprite():
    oak = Sprite(5, 3, 5, 2)
    assert adjacent_tile(oak, "up") == (5, 3)
    assert adjacent_tile(oak, "left") == (6, 2)


def _standing_at(x: int, y: int) -> FakeEmulator:
    """Player already on (x, y), so goto_far's first step finds here == target and returns True
    without moving."""
    emu = FakeEmulator()
    install_map(emu, ROOM)
    emu.mem[ram.wCurMap] = 1
    emu.mem[ram.wXCoord] = x
    emu.mem[ram.wYCoord] = y
    return emu


def test_talk_to_returns_false_when_nothing_appears_on_screen():
    emu = _standing_at(1, 1)
    assert not talk_to(emu, 1, 1, "up")


def test_talk_to_returns_true_once_dialog_is_on_screen():
    # FakeEmulator's press() cannot make a screen react on its own, so the rows are set from a
    # patched press() exactly when "a" is pressed (same technique as
    # test_navigator.py::test_interruption_keeps_the_plan_for_later): setting the dialog rows up
    # front instead would make goto_far itself bail out, since Navigator.step treats any non-
    # overworld mode as an interruption even before the player has moved.
    emu = _standing_at(1, 1)
    original = emu.press

    def press(button, **kwargs):
        if button == "a":
            emu.set_rows(["", "", "", "", "", "", "", "", "", "", "", "", "", "Hi there!"])
        return original(button, **kwargs)

    emu.press = press
    assert talk_to(emu, 1, 1, "up", patience=0)
