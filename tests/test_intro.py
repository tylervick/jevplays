from jevplays.emulator.intro import cursor_label
from tests.support import rows_from


def test_cursor_label_reads_the_text_after_the_cursor():
    rows = rows_from(["···············", "·             ·", "·▶NEW GAME    ·", "· OPTION      ·"])
    assert cursor_label(rows) == "NEW GAME"


def test_cursor_label_is_none_without_a_cursor():
    assert cursor_label(rows_from(["·Hello there!·"])) is None
