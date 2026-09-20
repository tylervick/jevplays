"""Gen 1 text: the font tile ids the game writes into its screen buffer, and how to read them.

Pokémon Red draws every piece of text by writing font tile ids into wTileMap (see ram.py), a
20x18 byte buffer copied to VRAM each frame. The ids come from the game's character map
(pokered's charmap.asm): 0x80..0x99 are A..Z, 0xA0..0xB9 a..z, 0xF6..0xFF the digits, 0x7F the
space tile, and a handful are punctuation, the menu cursor (▶, 0xED) and the "press A" arrow
(▼, 0xEE). Ids below 0x7F are map graphics, not text, so they decode to NON_TEXT.

Some ids stand for more than one character ("'s" is one tile). Rows are therefore decoded to a
list of cells, one per tile, so column indexes stay true to the screen; row_text joins them.
"""

from collections.abc import Iterable

CHARMAP: dict[int, str] = {
    0x7F: " ",
    0x80: "A",
    0x81: "B",
    0x82: "C",
    0x83: "D",
    0x84: "E",
    0x85: "F",
    0x86: "G",
    0x87: "H",
    0x88: "I",
    0x89: "J",
    0x8A: "K",
    0x8B: "L",
    0x8C: "M",
    0x8D: "N",
    0x8E: "O",
    0x8F: "P",
    0x90: "Q",
    0x91: "R",
    0x92: "S",
    0x93: "T",
    0x94: "U",
    0x95: "V",
    0x96: "W",
    0x97: "X",
    0x98: "Y",
    0x99: "Z",
    0x9A: "(",
    0x9B: ")",
    0x9C: ":",
    0x9D: ";",
    0x9E: "[",
    0x9F: "]",
    0xA0: "a",
    0xA1: "b",
    0xA2: "c",
    0xA3: "d",
    0xA4: "e",
    0xA5: "f",
    0xA6: "g",
    0xA7: "h",
    0xA8: "i",
    0xA9: "j",
    0xAA: "k",
    0xAB: "l",
    0xAC: "m",
    0xAD: "n",
    0xAE: "o",
    0xAF: "p",
    0xB0: "q",
    0xB1: "r",
    0xB2: "s",
    0xB3: "t",
    0xB4: "u",
    0xB5: "v",
    0xB6: "w",
    0xB7: "x",
    0xB8: "y",
    0xB9: "z",
    0xBA: "é",
    0xBB: "'d",
    0xBC: "'l",
    0xBD: "'s",
    0xBE: "'t",
    0xBF: "'v",
    0xE0: "'",
    0xE1: "PK",
    0xE2: "MN",
    0xE3: "-",
    0xE4: "'r",
    0xE5: "'m",
    0xE6: "?",
    0xE7: "!",
    0xE8: ".",
    0xEC: "▷",
    0xED: "▶",
    0xEE: "▼",
    0xEF: "♂",
    0xF0: "¥",
    0xF1: "×",
    0xF2: ".",
    0xF3: "/",
    0xF4: ",",
    0xF5: "♀",
    0xF6: "0",
    0xF7: "1",
    0xF8: "2",
    0xF9: "3",
    0xFA: "4",
    0xFB: "5",
    0xFC: "6",
    0xFD: "7",
    0xFE: "8",
    0xFF: "9",
}
"""Font tile id to text. 0xE1/0xE2 are the two halves of the POKéMON logo glyph."""

TERMINATOR = 0x50
"""Ends a name or string in RAM ("@" in the disassembly)."""
SPACE = 0x7F
CURSOR = "▶"
ARROW = "▼"
NON_TEXT = "·"
"""What a non-font tile (map graphics, box borders) decodes to."""
UNKNOWN = "?"

_REVERSE = {text: tile for tile, text in CHARMAP.items() if len(text) == 1}
_REVERSE["."] = 0xE8  # 0xF2 is the second "." glyph; encode the common one


def decode_cells(data: Iterable[int]) -> list[str]:
    """One cell per tile id. Font tiles become their text; anything else becomes NON_TEXT."""
    return [" " if b == SPACE else CHARMAP.get(b, UNKNOWN) if b >= 0x80 else NON_TEXT for b in data]


def decode_name(data: Iterable[int]) -> str:
    """Read a terminated string such as a player name. Stops at TERMINATOR if present."""
    out: list[str] = []
    for b in data:
        if b == TERMINATOR:
            break
        out.append(" " if b == SPACE else CHARMAP.get(b, UNKNOWN))
    return "".join(out)


def encode(text: str) -> list[int]:
    """Text to tile ids, for tests and fixtures. Only single-character glyphs are supported."""
    try:
        return [_REVERSE[ch] for ch in text]
    except KeyError as exc:
        raise ValueError(f"no Gen 1 tile for {exc.args[0]!r}") from None


def row_text(cells: Iterable[str]) -> str:
    return "".join(cells)


def has_text(cells: Iterable[str]) -> bool:
    """True when the cells hold something a person would read: not blanks, borders, or markers."""
    return any(c not in (" ", NON_TEXT, CURSOR, ARROW) for c in cells)
