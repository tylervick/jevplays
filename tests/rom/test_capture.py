"""Frame capture: the emulator hands back the frames a batch passed through (#31)."""

from jevplays.emulator.pyboy import Emulator


def test_a_batch_yields_a_frame_every_capture_every_frames(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("route1"))
        emu.capture_every = 4
        assert emu.tick(40) == 40
        frames = emu.take_frames()
        assert len(frames) == 10
        assert all(f.startswith(b"\xff\xd8\xff") for f in frames)  # JPEG magic
        assert emu.take_frames() == []


def test_capturing_does_not_add_frames_to_the_game(rom, state_path):
    """A captured frame must not cost an emulated one: pacing counts the frames a batch says it
    spent, so a capture that ticked an extra frame would run the game fast and drift the clock."""
    with Emulator(rom) as emu:
        emu.load(state_path("route1"))
        plain = emu.frame_count()
        emu.tick(60)
        without = emu.frame_count() - plain

        emu.capture_every = 4
        before = emu.frame_count()
        emu.tick(60)
        assert emu.frame_count() - before == without


def test_capture_is_off_by_default(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("route1"))
        emu.tick(30)
        assert emu.take_frames() == []


def test_short_ticks_add_up_to_a_capture_instead_of_never_reaching_one(rom, state_path):
    """#75: walking is an 8-frame press then 4-frame waits (`navigate.step`). With captures
    counted inside each tick, a tick shorter than `capture_every` never captured -- at 6x, where
    the interval is 24, the page never saw the player walk, only the doors at the end."""
    with Emulator(rom) as emu:
        emu.load(state_path("route1"))
        emu.capture_every = 24
        before = emu.frame_count()
        for _ in range(12):
            emu.tick(8)
        assert emu.frame_count() - before == 96  # still no extra emulated frames
        assert len(emu.take_frames()) == 4


def test_a_batch_that_is_not_a_multiple_of_the_interval_carries_its_remainder(rom, state_path):
    """A 30-frame tick at an interval of 24 captured twice (24, then the 6 left over), so the page
    got more frames than `fps` asked for. Across two such ticks the game passed 60 frames: two
    captures, not four."""
    with Emulator(rom) as emu:
        emu.load(state_path("route1"))
        emu.capture_every = 24
        emu.tick(30)
        emu.tick(30)
        assert len(emu.take_frames()) == 2
