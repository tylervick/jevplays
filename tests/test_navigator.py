from jevplays.emulator import ram
from jevplays.executor.navigate import STUCK_STEPS, Leg, Navigator
from jevplays.state.snapshot import snapshot
from tests.support import FakeEmulator, install_map

ROWS = ["......", "......", "..##..", "..##..", "......", "......"]


def walker():
    emu = FakeEmulator()
    install_map(emu, ROWS, warps=[(5, 0, 0, 99)], connections={"north": 7})
    emu.mem[ram.wCurMap] = 1
    emu.mem[ram.wXCoord] = 0
    emu.mem[ram.wYCoord] = 5
    return emu


def test_walk_leg_reaches_the_tile_one_step_per_call():
    emu = walker()
    nav = Navigator()
    nav.plan(emu, snapshot(emu), [Leg(kind="walk", target=(5, 5), label="corner")])
    results = []
    for _ in range(10):
        results.append(nav.step(emu, snapshot(emu)))
        if results[-1] == "done":
            break
    assert results[-1] == "done" and results.count("moving") == 4
    assert (emu.mem[ram.wXCoord], emu.mem[ram.wYCoord]) == (5, 5)
    assert not nav.busy


def test_sprite_in_the_way_is_routed_around():
    emu = walker()
    emu.set_sprites([(1, 61, 1, 5)])  # item ball on the direct path
    nav = Navigator()
    nav.plan(emu, snapshot(emu), [Leg(kind="walk", target=(2, 5))])
    for _ in range(10):
        if nav.step(emu, snapshot(emu)) == "done":
            break
    assert (emu.mem[ram.wXCoord], emu.mem[ram.wYCoord]) == (2, 5)
    assert "up" in emu.presses  # went around


def test_failed_steps_mark_the_cell_and_a_stuck_leg_gives_up():
    emu = walker()
    emu.step_effects = {}  # nothing ever moves
    nav = Navigator()
    nav.plan(emu, snapshot(emu), [Leg(kind="walk", target=(1, 5))])
    results = [nav.step(emu, snapshot(emu)) for _ in range(30)]
    assert "stuck" in results
    assert not nav.busy


def test_interruption_keeps_the_plan_for_later():
    emu = walker()
    nav = Navigator()
    nav.plan(emu, snapshot(emu), [Leg(kind="walk", target=(3, 5))])
    original = emu.press

    def press(button, **kw):
        emu.mem[ram.wIsInBattle] = 1  # a wild battle starts on the first step
        return original(button, **kw)

    emu.press = press
    assert nav.step(emu, snapshot(emu)) == "interrupted"
    assert nav.busy and nav.current.target == (3, 5)


def test_sprite_on_the_goal_tile_waits_instead_of_failing_the_leg():
    emu = walker()
    emu.set_sprites([(1, 61, 1, 5)])  # standing right on the walk leg's target
    nav = Navigator()
    nav.plan(emu, snapshot(emu), [Leg(kind="walk", target=(1, 5), label="blocked corner")])
    leg = nav.current
    for _ in range(STUCK_STEPS):
        assert nav.step(emu, snapshot(emu)) == "moving"
    assert not emu.presses
    assert nav.current is leg
    assert nav.failed_legs == 0
    emu.set_sprites([])
    for _ in range(10):
        result = nav.step(emu, snapshot(emu))
        if result == "done":
            break
    assert result == "done"
    assert (emu.mem[ram.wXCoord], emu.mem[ram.wYCoord]) == (1, 5)


def test_edge_leg_walks_to_the_north_edge_and_crosses():
    emu = walker()
    nav = Navigator()
    nav.plan(emu, snapshot(emu), [Leg(kind="edge", direction="north", dest_map=7)])
    for _ in range(20):
        r = nav.step(emu, snapshot(emu))
        if r in ("done", "stuck"):
            break
        if emu.mem[ram.wYCoord] == 0 and emu.presses[-1] == "up":
            emu.mem[ram.wCurMap] = 7  # the fake crosses when it steps off the edge
    assert r == "done" and emu.mem[ram.wCurMap] == 7
