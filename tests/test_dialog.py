from jevplays.executor.dialog import dialog_lines, yes_no_open
from tests.support import rows_from

DIALOG = rows_from(
    [""] * 12
    + [
        "····················",
        "·                  ·",
        "·Hello there!      ·",
        "·                  ·",
        "·Welcome to the   ▼·",
    ]
)
PROMPT = rows_from(["·▶YES·", "·    ·", "· NO ·"])


def test_dialog_lines_strip_borders_and_arrow():
    assert dialog_lines(DIALOG) == ["Hello there!", "Welcome to the"]


def test_yes_no_open():
    assert yes_no_open(PROMPT)
    assert not yes_no_open(DIALOG)
