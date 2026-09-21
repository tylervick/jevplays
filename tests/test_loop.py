import asyncio

from jevplays.brain.errors import BrainUnavailable
from jevplays.emulator import ram
from jevplays.executor import maps
from jevplays.executor.goals import Goal, goal_by_id
from jevplays.executor.world import build_grid
from jevplays.loop import GOAL_RETRIES, Loop, LoopConfig
from jevplays.state.modes import Mode
from jevplays.state.snapshot import snapshot
from tests.support import FakeEmulator, install_map, overworld_state, write_mon

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


def test_macro_error_retries_once_then_tries_the_safe_default_then_pauses():
    """On MacroError, retry once (settle-B, re-snapshot, re-apply); if it fails again, try the
    safe default (the first usable move) once; if that also fails, back out and hold."""
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
    # select_command(FIGHT) presses "a" then select_move fails immediately with "b", three times
    # (the original attempt, the retry, and the safe-default attempt), plus the loop's own
    # settling "b" press after the retry and again after the safe default also fails.
    assert emu.presses == ["a", "b", "b", "a", "b", "a", "b", "b"]
    decisions = [e["decision"] for e in bc.events if e["type"] == "decision"]
    assert len(decisions) == 1  # no fallback re-publish; the loop holds instead
    statuses = [e for e in bc.events if e["type"] == "status"]
    assert statuses[-1]["status"] == "paused"
    assert loop._hold is not None


def test_a_macro_that_keeps_failing_holds_instead_of_re_asking():
    """Once the safe default also fails, the loop holds at that mode instead of asking the brain
    again on every subsequent iteration."""
    emu = battle_emu()

    def press(button, **kw):
        emu.presses.append(button)
        return emu.tick(kw.get("hold", 8) + kw.get("settle", 8))

    emu.press = press  # move list never appears, so every select_move fails
    bc = RecordingBroadcaster()
    brain = FakeBrain(response=RESPONSE)
    loop = Loop(emu, bc, LoopConfig(paced=False), brain=brain)
    asyncio.run(loop.run(max_iterations=4))

    assert brain.calls == 1
    statuses = [e for e in bc.events if e["type"] == "status"]
    assert statuses[-1]["status"] == "paused"
    decisions = [e for e in bc.events if e["type"] == "decision"]
    assert len(decisions) == 1  # no further decision events after the fallback re-publish


# --- milestone 3: goals, navigation, prompts, and menus -------------------------------------

OVERWORLD_MAP = ["." * 12] * 8
"""12x8 walkable tiles: room enough for get_starter's walk to (10, 1)."""


class QuestionBrain:
    """Answers by question id, so one fake serves the goal, prompt, and menu branches."""

    def __init__(self, **answers):
        self.answers = answers
        self.calls = 0
        self.asked: list[list[str]] = []

    async def ask(self, state, questions):
        self.calls += 1
        self.asked.append(sorted(questions))
        answered = {}
        for qid in questions:
            value = self.answers.get(qid)
            if value is None:
                continue
            if isinstance(value, dict):
                answered[qid] = {
                    "type": "choice",
                    "choice": max(value, key=value.get),
                    "probabilities": value,
                    "confidence": 0.5,
                }
            else:
                answered[qid] = {"type": "noul", "noul": value}
        return {"model": "jev-test", "usage": {"input_tokens": 7}, "answers": answered}, 5


def overworld_emu(map_id=0, x=2, y=5):
    emu = FakeEmulator()
    install_map(emu, OVERWORLD_MAP)
    emu.mem[ram.wCurMap] = map_id
    emu.mem[ram.wXCoord], emu.mem[ram.wYCoord] = x, y
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
    return emu


def test_an_idle_overworld_asks_for_a_goal_once_and_starts_walking():
    emu, bc = overworld_emu(), RecordingBroadcaster()
    brain = QuestionBrain(goal={"get_starter": 0.9}, needs_heal=0.1)
    loop = Loop(emu, bc, LoopConfig(paced=False), brain=brain)
    run(loop, 3)
    assert brain.calls == 1  # the goal is asked once, then the navigator just walks
    assert brain.asked[0] == ["goal", "needs_heal"]
    assert loop.goal is not None and loop.goal.id == "get_starter"
    assert loop.navigator.busy
    assert any(p in ("up", "down", "left", "right") for p in emu.presses)
    kinds = [d.kind for d in loop.decisions]
    assert kinds == ["goal"] and loop.decisions[0].action == "pursue get_starter"


def test_without_a_brain_the_first_available_goal_is_taken_and_recorded():
    emu, bc = overworld_emu(), RecordingBroadcaster()
    loop = Loop(emu, bc, LoopConfig(paced=False))
    run(loop, 2)
    assert loop.goal is not None and loop.goal.id == "get_starter"
    assert [d.kind for d in loop.decisions] == ["goal"]
    assert loop.decisions[0].fallback and "no brain" in loop.decisions[0].fallback_reason
    assert [e["type"] for e in bc.events if e["type"] == "decision"] == ["decision"]


PROMPT_ROWS = [""] * 6 + [
    "·············▶YES··",
    "···················",
    "············· NO···",
]
NICKNAME_ROWS = (
    PROMPT_ROWS
    + [""] * 4
    + [
        "····················",
        "·Do you want to give·",
        "·a NICKNAME to it?  ·",
    ]
)


def prompt_emu(rows=PROMPT_ROWS):
    emu = overworld_emu()
    emu.set_rows(rows)
    return emu


def test_a_prompt_asks_jev_and_presses_yes_or_no():
    for noul, expected in ((0.9, ["a"]), (0.1, ["down", "a"])):
        emu, bc = prompt_emu(), RecordingBroadcaster()
        brain = QuestionBrain(prompt=noul)
        loop = Loop(emu, bc, LoopConfig(paced=False), brain=brain)
        assert snapshot(emu).mode is Mode.PROMPT
        run(loop, 1)
        assert brain.calls == 1 and brain.asked[0] == ["prompt"]
        assert emu.presses == expected
        assert loop.decisions[-1].kind == "prompt"


def test_a_nickname_prompt_never_asks_jev_and_answers_no():
    emu, bc = prompt_emu(NICKNAME_ROWS), RecordingBroadcaster()
    brain = QuestionBrain(prompt=0.99)
    loop = Loop(emu, bc, LoopConfig(paced=False), brain=brain)
    assert "NICKNAME" in snapshot(emu).text
    run(loop, 1)
    assert brain.calls == 0
    assert emu.presses == ["down", "a"]
    assert loop.decisions[-1].kind == "prompt"
    assert "nickname" in loop.decisions[-1].fallback_reason


MENU_ROWS = [""] * 2 + ["··▶HEAL····", "···········", "·· CANCEL··"]
MENU_ROWS_MOVED = [""] * 2 + ["·· HEAL····", "···········", "··▶CANCEL··"]


def menu_emu():
    emu = overworld_emu()
    emu.mem[ram.wTopMenuItemY], emu.mem[ram.wTopMenuItemX] = 2, 2
    emu.mem[ram.wMaxMenuItem] = 1
    emu.set_rows(MENU_ROWS)
    original = emu.press

    def press(button, **kw):
        if button == "down":
            emu.set_rows(MENU_ROWS_MOVED)  # the cursor moves with the press, as the game's does
        return original(button, **kw)

    emu.press = press
    return emu


def test_a_menu_walks_the_cursor_to_jevs_choice_and_presses_a():
    emu, bc = menu_emu(), RecordingBroadcaster()
    brain = QuestionBrain(menu={"CANCEL": 0.8, "HEAL": 0.2}, close=0.1)
    loop = Loop(emu, bc, LoopConfig(paced=False), brain=brain)
    assert snapshot(emu).mode is Mode.MENU and snapshot(emu).menu_items == ("HEAL", "CANCEL")
    run(loop, 1)
    assert brain.calls == 1 and brain.asked[0] == ["close", "menu"]
    assert emu.presses == ["down", "a"]
    assert loop.decisions[-1].action == "select CANCEL"


def test_without_a_brain_a_menu_is_closed():
    emu, bc = menu_emu(), RecordingBroadcaster()
    loop = Loop(emu, bc, LoopConfig(paced=False))
    run(loop, 1)
    assert emu.presses == ["b"]
    assert loop.decisions[-1].action == "close the menu"


def test_a_stuck_navigator_blocks_the_goal_and_the_next_goal_is_asked_for():
    emu, bc = overworld_emu(map_id=12, x=5, y=4), RecordingBroadcaster()  # Route 1: grass nearby
    emu.step_effects = {}  # nothing the navigator presses ever moves the player
    brain = QuestionBrain(goal={"get_starter": 0.9}, needs_heal=0.1)
    loop = Loop(emu, bc, LoopConfig(paced=False), brain=brain)
    run(loop, 200)  # GOAL_RETRIES stuck-navigator rounds, at ~19 iterations each
    assert "get_starter" in loop.blocked_goals
    assert brain.calls >= 2  # asked again once the first goal was given up on
    blocked = [e for e in bc.events if e["type"] == "status" and "blocked" in e["message"]]
    assert blocked and "get_starter" in blocked[0]["message"]


# --- fix round 1: grass-aware wander, retries, and menu/macro safety nets --------------------

WANDER_ROWS = [
    "........",
    "........",
    "....~~..",
    "....~~..",
    "........",
    "........",
]
"""8x6 cells of road with a 2x2 patch of tall grass at (4, 2)-(5, 3)."""


def grass_emu(x=0, y=0):
    emu = overworld_emu(map_id=maps.ROUTE_1, x=x, y=y)
    install_map(emu, WANDER_ROWS)
    emu.mem[ram.wCurMap], emu.mem[ram.wXCoord], emu.mem[ram.wYCoord] = maps.ROUTE_1, x, y
    return emu


def test_wander_walks_to_the_grass_and_then_stays_in_it():
    emu, bc = grass_emu(), RecordingBroadcaster()
    loop = Loop(emu, bc, LoopConfig(paced=False))
    loop.goal = goal_by_id("train_nearby")  # legs are empty, so `wander` runs every turn
    run(loop, 12)
    grid = build_grid(emu)
    here = (emu.mem[ram.wXCoord], emu.mem[ram.wYCoord])
    assert grid.is_grass(*here), f"{here} is not grass"
    assert loop.blocked_goals == set()
    assert emu.presses  # it walked there a step at a time


def test_wander_gives_up_on_a_map_with_no_grass_at_all():
    emu, bc = overworld_emu(), RecordingBroadcaster()
    install_map(emu, OVERWORLD_MAP)  # every cell is road
    loop = Loop(emu, bc, LoopConfig(paced=False))
    loop.goal = goal_by_id("train_nearby")
    assert loop._wander() is False
    assert emu.presses == []


MART_PARCEL = "got_oaks_parcel"


def test_talk_oak_in_the_mart_presses_nothing_once_the_parcel_is_already_in_hand():
    emu, bc = overworld_emu(), RecordingBroadcaster()
    loop = Loop(emu, bc, LoopConfig(paced=False))
    state = overworld_state(map_id=maps.VIRIDIAN_MART, flags=(MART_PARCEL,))
    assert loop._apply_macro("talk_oak", state) is True
    assert emu.presses == []
    assert loop.blocked_goals == set()


def test_a_menu_item_that_is_never_reached_closes_the_menu_instead_of_pressing_a():
    emu, bc = overworld_emu(), RecordingBroadcaster()
    emu.mem[ram.wTopMenuItemY], emu.mem[ram.wTopMenuItemX] = 2, 2
    emu.mem[ram.wMaxMenuItem] = 1
    emu.set_rows(MENU_ROWS)  # the cursor never moves off HEAL, whatever gets pressed
    brain = QuestionBrain(menu={"CANCEL": 0.8, "HEAL": 0.2}, close=0.1)
    loop = Loop(emu, bc, LoopConfig(paced=False), brain=brain)
    run(loop, 1)
    assert emu.presses == ["down", "down", "b"] and "a" not in emu.presses
    assert loop.decisions[-1].action == "close the menu"
    assert "not reached" in loop.decisions[-1].fallback_reason


def test_a_goal_gets_three_tries_before_it_is_blocked_and_then_the_loop_pauses():
    emu, bc = overworld_emu(), RecordingBroadcaster()
    install_map(emu, OVERWORLD_MAP)
    emu.step_effects = {}  # nothing the navigator presses ever moves the player
    loop = Loop(emu, bc, LoopConfig(paced=False))
    run(loop, 300)
    # In Pallet Town with no flags and no grass, get_starter is the only goal on offer.
    assert loop.blocked_goals == {"get_starter"}
    statuses = [e["message"] for e in bc.events if e["type"] == "status"]
    assert [m for m in statuses if m.startswith("goal failed")] == [
        f"goal failed {n}/{GOAL_RETRIES}: get_starter (the navigator gave up)" for n in range(1, GOAL_RETRIES)
    ]
    paused = [e for e in bc.events if e["type"] == "status" and e["status"] == "paused"]
    assert len(paused) == 1 and paused[0]["message"] == "all goals blocked: get_starter"


def test_a_macro_that_raises_blocks_the_goal_instead_of_killing_the_run():
    emu, bc = overworld_emu(), RecordingBroadcaster()
    loop = Loop(emu, bc, LoopConfig(paced=False))
    loop.goal = Goal(
        id="bogus",
        description="A goal whose macro does not exist",
        available=lambda s: True,
        done=lambda s: False,
        legs=lambda s: [],
        after="no_such_macro",
    )
    asyncio.run(loop.advance(snapshot(emu)))
    assert loop.goal is None and loop._goal_failures == {"bogus": 1}
    message = [e["message"] for e in bc.events if e["type"] == "status"][-1]
    assert "no_such_macro raised ValueError" in message
