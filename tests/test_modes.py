from jevplays.state.modes import Mode, detect, find_cursor, is_blank, yes_no_at
from tests.support import rows_from, tilemap_bytes

OVERWORLD = rows_from([])  # map tiles everywhere, nothing drawn on top

START_MENU = rows_from(
    [
        "····················",
        "···········        ·",
        "···········▶POKéMON·",
        "···········        ·",
        "··········· ITEM   ·",
        "···········        ·",
        "··········· RED    ·",
        "···········        ·",
        "··········· SAVE   ·",
        "···········        ·",
        "··········· OPTION ·",
        "···········        ·",
        "··········· EXIT   ·",
    ]
)

DIALOG_WAITING = rows_from(
    [
        "                    ",
        "                    ",
        "                    ",
        "                    ",
        "      ·······       ",
        "      ·······       ",
        "      ·······       ",
        "      ·······       ",
        "      ·······       ",
        "      ·······       ",
        "      ·······       ",
        "                    ",
        "····················",
        "·                  ·",
        "·Hello there!      ·",
        "·                  ·",
        "·Welcome to the   ▼·",
        "····················",
    ]
)

SAVE_PROMPT = rows_from(
    [
        "····················",
        "·····              ·",
        "·····PLAYER RED    ·",
        "·····              ·",
        "·····BADGES       0·",
        "·····              ·",
        "·····POKéDEX      0·",
        "······             ·",
        "·▶YES·IME      0·00·",
        "·    ···············",
        "· NO ······ OPTION ·",
        "···········        ·",
        "····················",
        "·                  ·",
        "·Would you like to ·",
        "·                  ·",
        "·SAVE the game?    ·",
        "····················",
    ]
)

BATTLE_MENU = rows_from(
    [""] * 12
    + [
        "····················",
        "·        ··········",
        "·        ·▶FIGHT PK·",
        "·        ··········",
        "·        · ITEM RUN·",
        "····················",
    ]
)

BATTLE_TEXT = rows_from(
    [""] * 12
    + [
        "····················",
        "·                  ·",
        "·Wild PIDGEY       ·",
        "·                  ·",
        "·appeared!        ▼·",
        "····················",
    ]
)


def test_overworld_when_nothing_is_drawn_over_the_map():
    assert detect(OVERWORLD, in_battle=False, blank=False) is Mode.OVERWORLD


def test_menu_when_a_cursor_is_on_screen():
    assert detect(START_MENU, in_battle=False, blank=False) is Mode.MENU
    assert find_cursor(START_MENU) == (2, 11)


def test_dialog_when_text_fills_the_bottom_box():
    assert detect(DIALOG_WAITING, in_battle=False, blank=False) is Mode.DIALOG


def test_prompt_when_yes_no_box_is_open():
    assert yes_no_at(SAVE_PROMPT) == (8, 1)
    assert detect(SAVE_PROMPT, in_battle=False, blank=False) is Mode.PROMPT


def test_prompt_with_cursor_on_no():
    rows = [list(r) for r in SAVE_PROMPT]
    rows[8][1], rows[10][1] = " ", "▶"
    assert yes_no_at(rows) == (8, 1)
    assert detect(rows, in_battle=False, blank=False) is Mode.PROMPT


def test_battle_menu_and_battle_wait():
    assert detect(BATTLE_MENU, in_battle=True, blank=False) is Mode.BATTLE_MENU
    assert detect(BATTLE_TEXT, in_battle=True, blank=False) is Mode.BATTLE_WAIT


def test_battle_flag_wins_over_screen_contents():
    assert detect(START_MENU, in_battle=True, blank=False) is Mode.BATTLE_WAIT


def test_transition_when_the_buffer_is_blank():
    assert detect(OVERWORLD, in_battle=False, blank=True) is Mode.TRANSITION


def test_is_blank_only_for_spaces_and_zeros():
    assert is_blank(bytes([0x7F] * 360))
    assert is_blank(bytes(360))
    assert not is_blank(tilemap_bytes([]))  # map tiles are not blank
    assert not is_blank(tilemap_bytes(["·▶NEW GAME"]))


def test_a_yes_no_box_during_a_battle_is_a_prompt_not_battle_text():
    """The nickname box after a catch opens while the game still counts itself in battle."""
    assert detect(SAVE_PROMPT, in_battle=True, blank=False) is Mode.PROMPT


# The FIGHT screen as the ROM draws it at the start of a battle, recorded while tracing #67.
MOVE_LIST = rows_from(
    [""] * 12
    + [
        "····················",
        "·   ·▶SCRATCH      ·",
        "·   · GROWL        ·",
        "·   · EMBER        ·",
        "·   · LEER         ·",
        "····················",
    ]
)

NO_PP = rows_from(
    [""] * 12
    + [
        "····················",
        "·                  ·",
        "·No PP left for    ·",
        "·                  ·",
        "·this move!       ▼·",
        "····················",
    ]
)


def test_the_move_list_is_its_own_screen_not_battle_text():
    """#67: an A press meant for battle text landed as the battle menu was drawn, chose FIGHT, and
    opened this list. Read as BATTLE_WAIT, it got another A, which used whatever move the cursor
    was on -- a move Jev never chose -- and, on a move with no PP left, "No PP left for this move!"
    and back to this list with the cursor where it was, forever."""
    assert detect(MOVE_LIST, in_battle=True, blank=False) is Mode.MOVE_LIST


def test_the_no_pp_message_is_still_battle_text_to_press_through():
    assert detect(NO_PP, in_battle=True, blank=False) is Mode.BATTLE_WAIT


def test_a_move_list_outside_a_battle_is_not_one():
    assert detect(MOVE_LIST, in_battle=False, blank=False) is Mode.MENU
