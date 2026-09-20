import pytest

from jevplays.emulator.text import (
    ARROW,
    CURSOR,
    NON_TEXT,
    decode_cells,
    decode_name,
    encode,
    has_text,
    row_text,
)


def test_decode_cells_one_cell_per_tile_even_for_two_character_glyphs():
    # H e l l o <space> 's <map tile>
    cells = decode_cells([0x87, 0xA4, 0xAB, 0xAB, 0xAE, 0x7F, 0xBD, 0x10])
    assert cells == ["H", "e", "l", "l", "o", " ", "'s", NON_TEXT]


def test_decode_cells_marks_cursor_and_arrow():
    assert decode_cells([0xED, 0xEE]) == [CURSOR, ARROW]


def test_decode_cells_digits_and_punctuation():
    assert row_text(decode_cells([0xF6, 0xF9, 0xF6, 0xF0, 0xE8, 0xE7, 0xE6])) == "030¥.!?"


def test_decode_name_stops_at_terminator():
    assert decode_name([0x91, 0x84, 0x83, 0x50, 0x80, 0x80]) == "RED"


def test_decode_name_without_terminator_reads_everything():
    assert decode_name([0x81, 0x8B, 0x94, 0x84]) == "BLUE"


def test_encode_round_trips_single_character_glyphs():
    assert decode_cells(encode("NEW GAME")) == list("NEW GAME")
    assert encode("A") == [0x80]
    assert encode(" ") == [0x7F]


def test_encode_rejects_unknown_characters():
    with pytest.raises(ValueError):
        encode("~")


def test_has_text_ignores_blanks_map_tiles_cursor_and_arrow():
    assert not has_text([" ", NON_TEXT, CURSOR, ARROW])
    assert has_text([NON_TEXT, "S", "A", "V", "E"])
