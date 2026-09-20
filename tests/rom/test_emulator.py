from io import BytesIO

from PIL import Image

from jevplays.emulator.pyboy import BUTTONS, Emulator
from jevplays.emulator.ram import TILEMAP_HEIGHT, TILEMAP_SIZE, TILEMAP_WIDTH, wCurMap


def test_boots_headless_and_reports_the_cartridge(rom):
    with Emulator(rom) as emu:
        assert emu.title == "POKEMON RED"
        assert emu.tick(10) == 10
        assert emu.mem[wCurMap] == 0  # nothing loaded yet at the title screen


def test_tilemap_and_rows_have_the_screen_shape(rom):
    with Emulator(rom) as emu:
        emu.tick(120)
        assert len(emu.tilemap()) == TILEMAP_SIZE
        rows = emu.rows()
        assert len(rows) == TILEMAP_HEIGHT
        assert all(len(r) == TILEMAP_WIDTH for r in rows)


def test_frame_is_a_jpeg(rom):
    with Emulator(rom) as emu:
        emu.tick(120)
        jpeg = emu.frame_jpeg()
        assert jpeg[:2] == b"\xff\xd8"
        assert Image.open(BytesIO(jpeg)).size == (160, 144)


def test_press_returns_frames_spent_and_rejects_unknown_buttons(rom):
    import pytest

    with Emulator(rom) as emu:
        assert emu.press("start", hold=4, settle=6) == 10
        assert "select" in BUTTONS
        with pytest.raises(ValueError):
            emu.press("x")


def test_save_and_load_round_trip(rom, tmp_path):
    with Emulator(rom) as emu:
        emu.tick(300)
        before = emu.tilemap()
        path = tmp_path / "t.state"
        emu.save(path)
        emu.tick(300)
        emu.load(path)
        assert emu.tilemap() == before
