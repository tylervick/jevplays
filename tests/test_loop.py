import asyncio

from jevplays.brain.client import BrainUnavailable
from jevplays.emulator import ram
from jevplays.loop import Loop, LoopConfig
from jevplays.state.modes import Mode
from jevplays.state.snapshot import snapshot
from tests.support import FakeEmulator, write_mon

DIALOG = [""] * 12 + [
    "····················",
    "·                  ·",
    "·Hello there!      ·",
    "·                  ·",
    "·Welcome to the   ▼·",
]


class RecordingBroadcaster:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish(self, event: dict) -> None:
        self.events.append(event)


def run(loop: Loop, iterations: int) -> None:
    asyncio.run(loop.run(max_iterations=iterations))


def test_publishes_state_then_frame_on_the_first_iteration():
    emu, bc = FakeEmulator(), RecordingBroadcaster()
    run(Loop(emu, bc, LoopConfig(paced=False)), 1)
    assert [e["type"] for e in bc.events][:2] == ["state", "frame"]


def test_state_is_published_only_when_it_changes():
    emu, bc = FakeEmulator(), RecordingBroadcaster()
    run(Loop(emu, bc, LoopConfig(paced=False, fps=1000)), 3)
    assert sum(e["type"] == "state" for e in bc.events) == 1


def test_frames_are_rate_limited():
    emu, bc = FakeEmulator(), RecordingBroadcaster()
    run(Loop(emu, bc, LoopConfig(paced=False, fps=0.001)), 5)  # one frame per 1000 s
    assert sum(e["type"] == "frame" for e in bc.events) == 1


def test_dialog_gets_an_a_press_and_overworld_idles():
    emu = FakeEmulator()
    loop = Loop(emu, RecordingBroadcaster(), LoopConfig(paced=False, idle_frames=7))
    emu.set_rows(DIALOG)
    assert snapshot(emu).mode is Mode.DIALOG
    asyncio.run(loop.advance(snapshot(emu)))
    assert emu.presses == ["a"]
    emu.set_rows([])
    before = emu.frames
    assert asyncio.run(loop.advance(snapshot(emu))) == 7
    assert emu.frames == before + 7
    assert emu.presses == ["a"]


BATTLE_MENU = [""] * 14 + ["·       ·▶FIGHT PK·", "", "·       · ITEM RUN·"]
MOVES = [""] * 13 + [
    "·   ·▶SCRATCH      ·",
    "·   · GROWL        ·",
    "·   · -            ·",
    "·   · -            ·",
]


class FakeBrain:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = 0

    async def ask(self, state, questions):
        self.calls += 1
        if self.error:
            raise self.error
        return self.response, 12


def battle_emu():
    emu = FakeEmulator()
    emu.step_effects = {}
    emu.mem[ram.wIsInBattle] = 1
    write_mon(
        emu.mem,
        ram.wPartyMons,
        ram.wPartyMonNicks,
        species=176,
        level=5,
        hp=19,
        max_hp=19,
        types=(20, 20),
        moves=(10, 45),
        pps=(35, 40),
        nickname="CHARMANDER",
    )
    emu.mem[ram.wPartyCount] = 1
    write_mon(
        emu.mem,
        ram.wBattleMonSpecies,
        ram.wBattleMonNick,
        species=176,
        level=5,
        hp=19,
        max_hp=19,
        types=(20, 20),
        moves=(10, 45),
        pps=(35, 40),
        nickname="CHARMANDER",
        layout="battle",
    )
    write_mon(
        emu.mem,
        ram.wEnemyMonSpecies,
        ram.wEnemyMonNick,
        species=165,
        level=3,
        hp=14,
        max_hp=14,
        types=(0, 0),
        moves=(33,),
        pps=(35,),
        nickname="RATTATA",
        layout="battle",
    )
    emu.set_rows(BATTLE_MENU)
    return emu


RESPONSE = {
    "model": "jev-1.13.0",
    "usage": {"input_tokens": 500, "output_tokens": 10},
    "answers": {
        "move": {
            "type": "choice",
            "choice": "SCRATCH",
            "probabilities": {"SCRATCH": 0.8, "GROWL": 0.2},
            "confidence": 0.6,
        },
        "run": {"type": "noul", "noul": 0.1},
    },
}


def test_battle_menu_asks_the_brain_publishes_the_decision_and_presses_the_move():
    emu = battle_emu()
    presses = []
    original = emu.press

    def press(button, **kw):
        presses.append(button)
        r = original(button, **kw)
        if presses == ["a"]:
            emu.set_rows(MOVES)  # FIGHT opened the move list
        return r

    emu.press = press
    bc = RecordingBroadcaster()
    brain = FakeBrain(response=RESPONSE)
    loop = Loop(emu, bc, LoopConfig(paced=False), brain=brain)
    asyncio.run(loop.run(max_iterations=1))
    assert brain.calls == 1
    assert [e["type"] for e in bc.events][:3] == ["state", "frame", "decision"]
    assert bc.events[2]["decision"]["action"] == "use SCRATCH"
    assert presses == ["a", "a"]
    assert loop.decisions[0].answers["run"]["applied"] is False


def test_api_failure_pauses_with_status_and_presses_nothing():
    emu = battle_emu()
    bc = RecordingBroadcaster()
    loop = Loop(
        emu, bc, LoopConfig(paced=False, backoff_max=0.01), brain=FakeBrain(error=BrainUnavailable("503"))
    )
    asyncio.run(loop.run(max_iterations=2))
    statuses = [e for e in bc.events if e["type"] == "status"]
    assert statuses and statuses[0]["status"] == "waiting_for_api" and "503" in statuses[0]["message"]
    assert emu.presses == []


def test_without_a_brain_the_battle_menu_idles():
    emu = battle_emu()
    loop = Loop(emu, RecordingBroadcaster(), LoopConfig(paced=False, idle_frames=9))
    asyncio.run(loop.run(max_iterations=1))
    assert emu.presses == [] and emu.frames >= 9


def test_macro_error_retries_once_then_falls_back_and_presses_b():
    """A controller ruling beyond the brief: on MacroError, retry select_move once (settle-B,
    re-snapshot, re-apply); if it fails again, mark the decision's fallback and re-publish it."""
    emu = battle_emu()

    def press(button, **kw):
        emu.presses.append(button)
        return emu.tick(kw.get("hold", 8) + kw.get("settle", 8))

    emu.press = press  # move list never appears, so select_move always fails and presses "b"
    bc = RecordingBroadcaster()
    brain = FakeBrain(response=RESPONSE)
    loop = Loop(emu, bc, LoopConfig(paced=False), brain=brain)
    asyncio.run(loop.run(max_iterations=1))

    assert brain.calls == 1
    # select_command(FIGHT) presses "a", then select_move fails 4x "down" + a "b" -- twice
    # (once per apply attempt), plus the loop's own settling "b" press after the second failure.
    assert emu.presses.count("b") == 3
    decisions = [e["decision"] for e in bc.events if e["type"] == "decision"]
    assert len(decisions) == 2
    assert decisions[-1]["fallback"] is True
    assert "twice" in decisions[-1]["fallback_reason"]
