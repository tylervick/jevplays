from jevplays.executor.talk import adjacent_tile, find_sprite
from jevplays.state.snapshot import Sprite, snapshot
from tests.support import FakeEmulator


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
