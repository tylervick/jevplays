from jevplays.executor.dialog import answer_prompt, dialog_lines, skip_dialog, yes_no_open
from tests.support import FakeEmulator, rows_from

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

ARROW_BOX = [""] * 12 + [
    "····················",
    "·                  ·",
    "·Hello there!      ·",
    "·                  ·",
    "·Welcome to the   ▼·",
]
SILENT_BOX = [""] * 12 + [
    "····················",
    "·                  ·",
    "·Here, come with   ·",
    "·                  ·",
    "·me!               ·",
]
YES_NO = (
    ["·▶YES·", "·    ·", "· NO ·"]
    + [""] * 9
    + [
        "····················",
        "·                  ·",
        "·Give it a nickname·",
        "·                  ·",
        "·?                 ·",
    ]
)
BLANK = []


class ScriptedDialog(FakeEmulator):
    """Each press advances to the next screen; ticks do not."""

    def __init__(self, screens):
        super().__init__()
        self.step_effects = {}
        self.screens = list(screens)
        self.set_rows(self.screens.pop(0))

    def press(self, button, *, hold=8, settle=8):
        super().press(button, hold=hold, settle=settle)
        if self.screens:
            self.set_rows(self.screens.pop(0))
        return hold + settle


def test_dialog_lines_strip_borders_and_arrow():
    assert dialog_lines(DIALOG) == ["Hello there!", "Welcome to the"]


def test_yes_no_open():
    assert yes_no_open(PROMPT)
    assert not yes_no_open(DIALOG)


def test_arrow_gets_an_a_and_then_it_stops_when_the_screen_clears():
    emu = ScriptedDialog([ARROW_BOX, BLANK])
    assert skip_dialog(emu, patience=3) is False
    assert emu.presses == ["a"]


def test_prompt_is_answered_with_the_callback():
    seen = []

    def answer(text):
        seen.append(text)
        return "nickname" not in text.lower()

    emu = ScriptedDialog([YES_NO, BLANK, BLANK])
    skip_dialog(emu, answer=answer, patience=3)
    assert seen == ["Give it a nickname ?"]
    assert emu.presses == ["down", "a"]  # answered NO


def test_silent_box_gets_a_nudge_after_the_idle_threshold():
    emu = ScriptedDialog([SILENT_BOX, BLANK])
    skip_dialog(emu, nudge_after=4, patience=8)
    assert emu.presses == ["a"]
    assert emu.frames >= 40  # four idle ticks of ten frames before the nudge


def test_stop_when_ends_the_loop_before_any_press():
    emu = ScriptedDialog([ARROW_BOX])
    assert skip_dialog(emu, stop_when=lambda rows: True) is True
    assert emu.presses == []


def test_answer_prompt_yes_and_no():
    emu = FakeEmulator()
    emu.step_effects = {}
    answer_prompt(emu, True)
    answer_prompt(emu, False)
    assert emu.presses == ["a", "down", "a"]
