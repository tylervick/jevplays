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
