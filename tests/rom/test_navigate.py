from jevplays.emulator import ram
from jevplays.emulator.pyboy import Emulator
from jevplays.executor.autoplay import finish_battle
from jevplays.executor.navigate import Leg, Navigator, goto
from jevplays.state.snapshot import snapshot


def test_collision_window_has_the_expected_shape(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("overworld"))
        grid = emu.collision()
        assert len(grid) == 9 and all(len(row) == 10 for row in grid)
        assert all(cell in (0, 1) for row in grid for cell in row)


def test_goto_reaches_the_bedroom_stairs_and_warps_downstairs(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("overworld"))
        assert goto(emu, 7, 1)
        emu.tick(60)
        assert emu.mem[ram.wCurMap] == 37  # REDS_HOUSE_1F


def test_navigator_crosses_route_1_into_viridian(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("route1"))
        nav = Navigator()
        nav.plan(emu, snapshot(emu), [Leg(kind="edge", direction="north", dest_map=1)])
        for _ in range(400):
            r = nav.step(emu, snapshot(emu))
            if r == "interrupted":
                # a wild battle: play it out with the first move, as the state script does
                finish_battle(emu)
                continue
            if r in ("done", "stuck"):
                break
        assert r == "done" and emu.mem[ram.wCurMap] == 1
