import asyncio
from dataclasses import replace

from jevplays.brain.decision import PromptAction
from jevplays.brain.errors import BrainUnavailable
from jevplays.emulator import ram
from jevplays.executor import maps
from jevplays.executor.goals import Goal, available_goals, goal_by_id
from jevplays.executor.world import build_grid
from jevplays.loop import GOAL_BUDGET_S, GOAL_RETRIES, Loop, LoopConfig, local_decision
from jevplays.state.modes import Mode
from jevplays.state.snapshot import snapshot
from tests.support import OVERWORLD_LEAD, FakeEmulator, install_map, overworld_state, write_mon
from tests.test_battle_macros import (
    ITEM_LIST_ROWS,
    ITEM_LIST_ROWS_POTION,
    ITEM_PARTY_ROWS,
    MENU_ITEM,
    MENU_PKMN,
    PARTY_LIST_ROWS,
    PARTY_LIST_ROWS_SLOT1,
    SWITCH_MENU_ROWS,
    ScriptedEmulator,
)

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


def configure_battle_memory(emu, *, hp=19, max_hp=19, bag=(), party_extra=None):
    """Write the lead's party record, its in-battle record, the enemy, and an optional bag onto
    `emu.mem` -- everything `battle_state`/`battle_questions` read, independent of whatever the
    screen shows. `party_extra` is a second `write_mon` call's kwargs, for a bench slot
    (`bench_slots` needs a second, living party member to offer a switch)."""
    emu.mem[ram.wIsInBattle] = 1
    write_mon(
        emu.mem,
        ram.wPartyMons,
        ram.wPartyMonNicks,
        species=176,
        level=5,
        hp=hp,
        max_hp=max_hp,
        types=(20, 20),
        moves=(10, 45),
        pps=(35, 40),
        nickname="CHARMANDER",
    )
    party_count = 1
    if party_extra is not None:
        write_mon(
            emu.mem,
            ram.wPartyMons + ram.PARTY_MON_SIZE,
            ram.wPartyMonNicks + ram.NAME_LENGTH,
            **party_extra,
        )
        party_count = 2
    emu.mem[ram.wPartyCount] = party_count
    write_mon(
        emu.mem,
        ram.wBattleMonSpecies,
        ram.wBattleMonNick,
        species=176,
        level=5,
        hp=hp,
        max_hp=max_hp,
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
    for i, (item_id, quantity) in enumerate(bag):
        emu.mem[ram.wBagItems + 2 * i] = item_id
        emu.mem[ram.wBagItems + 2 * i + 1] = quantity
    emu.mem[ram.wNumBagItems] = len(bag)


def battle_emu(*, hp=19, max_hp=19, bag=(), party_extra=None):
    emu = FakeEmulator()
    emu.step_effects = {}
    configure_battle_memory(emu, hp=hp, max_hp=max_hp, bag=bag, party_extra=party_extra)
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


# --- milestone 4a: heal, catch, and switch decisions are carried out -------------------------

# The battle item list, missing POTION -- for the "macro raises" test, so the lead stays low on
# hp (a Potion is the right call) while the screen the loop actually walks cannot supply one, the
# same kind of desync `_retry_after_macro_error`'s docstring already describes.
ITEM_LIST_NO_POTION = [""] * 4 + [
    "····▶POKé BALL    ·",
    "····         × 5  ·",
    "···· CANCEL       ·",
]


def test_battle_heal_uses_a_potion_via_the_item_path():
    """heal=0.95 with the lead low on hp and a Potion in the bag: the loop presses ITEM (not
    FIGHT) and the recorded decision is "use a Potion"."""
    emu = battle_emu(hp=5, bag=[(20, 3)])  # item 20 is POTION; hp 5/19 buckets to "low"
    original = emu.press

    def press(button, **kw):
        r = original(button, **kw)
        if emu.presses == ["down"]:
            emu.set_rows(MENU_ITEM)  # cursor walked from FIGHT down to ITEM
        elif emu.presses == ["down", "a"]:
            emu.set_rows(ITEM_LIST_ROWS)  # ITEM opened the bag, cursor on POKé BALL
        elif emu.presses == ["down", "a", "down"]:
            emu.set_rows(ITEM_LIST_ROWS_POTION)  # scrolled one down to POTION
        elif emu.presses == ["down", "a", "down", "a"]:
            emu.set_rows(ITEM_PARTY_ROWS)  # POTION picked -> "Use item on which POKéMON?"
        return r

    emu.press = press
    bc = RecordingBroadcaster()
    brain = QuestionBrain(move={"SCRATCH": 0.6}, heal=0.95)
    loop = Loop(emu, bc, LoopConfig(paced=False), brain=brain)
    asyncio.run(loop.run(max_iterations=1))

    assert brain.calls == 1
    decisions = [e["decision"] for e in bc.events if e["type"] == "decision"]
    assert decisions[0]["action"] == "use a Potion"
    assert emu.presses == ["down", "a", "down", "a", "a"]  # ITEM path, then the target slot


def test_battle_switch_resolves_the_bench_label_to_a_party_slot():
    """A switch answer names a bench label (bench_slots' labels, not a party index); the loop
    looks it up and hands apply() a concrete slot, walking the PKMN path to get there."""
    emu = ScriptedEmulator([BATTLE_MENU, MENU_PKMN, PARTY_LIST_ROWS, PARTY_LIST_ROWS_SLOT1, SWITCH_MENU_ROWS])
    configure_battle_memory(
        emu,
        party_extra=dict(
            species=16,
            level=8,
            hp=14,
            max_hp=14,
            types=(0, 0),
            moves=(33,),
            pps=(35,),
            nickname="PIDGEY",
        ),
    )
    bc = RecordingBroadcaster()
    brain = QuestionBrain(move={"SCRATCH": 0.5}, switch=0.95, switch_to={"PIDGEY": 0.9})
    loop = Loop(emu, bc, LoopConfig(paced=False), brain=brain)
    asyncio.run(loop.run(max_iterations=1))

    assert brain.calls == 1
    assert emu.presses[:2] == ["right", "a"]  # the PKMN path, not FIGHT
    decision = loop.decisions[-1]
    assert decision.action_value.kind == "switch"
    assert decision.action_value.slot == 1  # PIDGEY's party index, resolved from its label


def test_battle_heal_macro_error_falls_back_to_the_safe_default_move():
    """The screen's item list has no POTION (it fell out of the bag between the snapshot and the
    press -- the same race `_retry_after_macro_error` is built for), so the macro raises twice
    and the loop lands on the safe default: the first usable move, SCRATCH."""
    emu = battle_emu(hp=5, bag=[(20, 3)])
    screen = "MENU"
    transitions = {
        ("MENU", "down"): ("MENU_ITEM", MENU_ITEM),
        ("MENU", "a"): ("MOVES", MOVES),
        ("MENU_ITEM", "a"): ("ITEM_LIST", ITEM_LIST_NO_POTION),
        ("ITEM_LIST", "down"): ("ITEM_LIST", ITEM_LIST_NO_POTION),
        ("ITEM_LIST", "b"): ("MENU_ITEM", MENU_ITEM),
        ("MENU_ITEM", "b"): ("MENU", BATTLE_MENU),
        # MENU_ITEM *is* the battle menu, with the cursor on ITEM rather than FIGHT, so the
        # macro's back-out stops there -- one B closes the list and the second would do nothing
        # on the real machine. Walking the cursor back up to FIGHT is select_command's job.
        ("MENU_ITEM", "up"): ("MENU", BATTLE_MENU),
    }
    original = emu.press

    def press(button, **kw):
        nonlocal screen
        r = original(button, **kw)
        step = transitions.get((screen, button))
        if step is not None:
            screen, rows = step
            emu.set_rows(rows)
        return r

    emu.press = press
    bc = RecordingBroadcaster()
    brain = QuestionBrain(move={"SCRATCH": 0.6}, heal=0.95)
    loop = Loop(emu, bc, LoopConfig(paced=False), brain=brain)
    asyncio.run(loop.run(max_iterations=1))

    assert brain.calls == 1
    decisions = [e["decision"] for e in bc.events if e["type"] == "decision"]
    assert len(decisions) == 1  # no fallback re-publish; the same decision's macro was retried
    statuses = [e for e in bc.events if e["type"] == "status"]
    assert statuses[-1]["status"] == "running"
    assert "macro failed" in statuses[-1]["message"]
    assert emu.presses[-2:] == ["a", "a"]  # FIGHT, then SCRATCH


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
    loop.goal_started_at = loop.clock()
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
    loop.goal_started_at = loop.clock()
    assert loop._wander(snapshot(emu)) is False
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
    loop.goal_started_at = loop.clock()
    asyncio.run(loop.advance(snapshot(emu)))
    assert loop.goal is None and loop._goal_failures == {"bogus": 1}
    message = [e["message"] for e in bc.events if e["type"] == "status"][-1]
    assert "no_such_macro raised ValueError" in message


# --- final fix wave: the goal budget, stale plans, and the way back out ----------------------


def test_an_absorbing_goal_is_dropped_after_its_budget_and_jev_is_asked_again():
    """`train_nearby` is never done and never fails, so without a budget the first time Jev
    picked it would be the last decision it ever made."""
    emu, bc = grass_emu(), RecordingBroadcaster()
    brain = QuestionBrain(goal={"train_nearby": 0.9}, needs_heal=0.1)
    loop = Loop(emu, bc, LoopConfig(paced=False), brain=brain)
    now = [1000.0]
    loop.clock = lambda: now[0]
    run(loop, 3)
    assert loop.goal is not None and loop.goal.id == "train_nearby" and brain.calls == 1
    now[0] += GOAL_BUDGET_S + 1
    run(loop, 3)
    assert brain.calls == 2  # the budget handed the decision back
    assert loop._goal_failures == {}  # spending a budget is not failing
    assert "goal budget spent: train_nearby" in [e["message"] for e in bc.events if e["type"] == "status"]


def test_a_map_change_under_a_plan_re_plans_without_charging_a_retry():
    # In Pallet Town get_starter's plan is a single walk leg, which is the kind that can tell a
    # teleport from an arrival: a walk never changes the map on purpose.
    emu, bc = overworld_emu(map_id=maps.PALLET_TOWN, x=5, y=5), RecordingBroadcaster()
    loop = Loop(emu, bc, LoopConfig(paced=False))
    run(loop, 1)  # picks a goal and plans its legs
    assert loop.navigator.busy and loop.navigator.current.kind == "walk"
    assert loop.navigator.plan_map == maps.PALLET_TOWN
    emu.mem[ram.wCurMap] = maps.VIRIDIAN_POKECENTER  # blacked out mid-walk
    run(loop, 1)
    assert loop.navigator.plan_map == maps.VIRIDIAN_POKECENTER  # re-planned where we really are
    assert loop._goal_failures == {}  # the goal did nothing wrong, so no retry is charged
    assert "re-planning after a map change" in [e["message"] for e in bc.events if e["type"] == "status"]


UNMAPPED_MAP = 200
"""Not in maps.NODE_NAMES, so node_of() calls it "map_200" and no route starts from it."""


def test_an_unmapped_map_walks_back_out_of_the_door_instead_of_blocking_the_goal():
    emu, bc = overworld_emu(map_id=UNMAPPED_MAP, x=1, y=1), RecordingBroadcaster()
    install_map(emu, ["...." for _ in range(4)], warps=[(3, 3, 0, ram.WARP_LAST_MAP)])
    emu.mem[ram.wCurMap] = UNMAPPED_MAP
    loop = Loop(emu, bc, LoopConfig(paced=False))
    run(loop, 1)
    assert loop.goal is not None and loop._goal_failures == {}  # not blocked
    leg = loop.navigator.current
    assert leg is not None and leg.kind == "warp" and leg.dest_map == ram.WARP_LAST_MAP
    assert "back outside" in [e["message"] for e in bc.events if e["type"] == "status"]


def test_nothing_available_says_so_rather_than_naming_no_goals():
    """Nothing blocked, nothing on offer either: the badge must not read "all goals blocked: "."""
    emu, bc = FakeEmulator(), RecordingBroadcaster()
    loop = Loop(emu, bc, LoopConfig(paced=False))
    veteran = replace(OVERWORLD_LEAD, level=12)
    done_with_everything = overworld_state(
        map_id=maps.PALLET_TOWN,  # not a grass map, so train_nearby is out too
        money=0,
        party=(veteran,),
        flags=("got_starter", "got_pokedex", "beat_brock"),
    )
    assert available_goals(done_with_everything) == []
    asyncio.run(loop._pick_goal(done_with_everything))
    asyncio.run(loop._pick_goal(done_with_everything))  # announced once, not on every iteration
    paused = [e for e in bc.events if e["type"] == "status" and e["status"] == "paused"]
    assert len(paused) == 1 and paused[0]["message"] == "no goal is available right now"
    assert loop._goal_failures == {}


# --- milestone 3b: the loop writes through the run dir ---------------------------------------


def test_every_decision_is_appended_to_the_run_log(tmp_path):
    from jevplays.runlog import RunDir

    run_dir = RunDir.create(tmp_path, rom=None, flags={})
    emu = prompt_emu()
    loop = Loop(emu, RecordingBroadcaster(), LoopConfig(paced=False), brain=None, run_dir=run_dir)
    run(loop, 1)
    assert run_dir.count() == 1
    assert next(run_dir.decisions())["kind"] == "prompt"
    assert loop.decision_count == 1


def test_a_checkpoint_is_written_every_checkpoint_every_decisions(tmp_path):
    from jevplays.runlog import CHECKPOINT_EVERY, RunDir

    run_dir = RunDir.create(tmp_path, rom=None, flags={})
    emu = prompt_emu()
    emu.step_effects = {}  # the fake never leaves the prompt, so every iteration decides again
    loop = Loop(emu, RecordingBroadcaster(), LoopConfig(paced=False), brain=None, run_dir=run_dir)
    run(loop, CHECKPOINT_EVERY * 2 + 1)
    assert sorted(p.name for p in run_dir.path.glob("checkpoint-*.state")) == [
        f"checkpoint-{CHECKPOINT_EVERY}.state",
        f"checkpoint-{CHECKPOINT_EVERY * 2}.state",
    ]


def test_numbering_continues_from_the_log_when_resumed(tmp_path):
    from jevplays.runlog import CHECKPOINT_EVERY, RunDir

    run_dir = RunDir.create(tmp_path, rom=None, flags={})
    for _ in range(CHECKPOINT_EVERY - 1):
        run_dir.append(local_decision("prompt", {}, PromptAction(yes=True), "seed"))
    emu = prompt_emu()
    loop = Loop(emu, RecordingBroadcaster(), LoopConfig(paced=False), brain=None, run_dir=run_dir)
    run(loop, 1)
    assert loop.decision_count == CHECKPOINT_EVERY
    assert (run_dir.path / f"checkpoint-{CHECKPOINT_EVERY}.state").is_file()


def test_the_first_model_id_lands_in_run_json(tmp_path):
    from jevplays.runlog import RunDir

    run_dir = RunDir.create(tmp_path, rom=None, flags={})
    emu = prompt_emu()
    brain = FakeBrain(
        response={
            "model": "jev-1.13.0",
            "usage": {"input_tokens": 3},
            "answers": {"prompt": {"type": "noul", "noul": 0.9}},
        }
    )
    loop = Loop(emu, RecordingBroadcaster(), LoopConfig(paced=False), brain=brain, run_dir=run_dir)
    run(loop, 1)
    assert run_dir.info()["model"] == "jev-1.13.0"


def test_checkpoint_on_demand_names_the_current_count_and_says_so(tmp_path):
    from jevplays.runlog import RunDir

    run_dir = RunDir.create(tmp_path, rom=None, flags={})
    bc = RecordingBroadcaster()
    loop = Loop(FakeEmulator(), bc, LoopConfig(paced=False), run_dir=run_dir)
    path = asyncio.run(loop.checkpoint())
    assert path.name == "checkpoint-0.state"
    assert any(e["type"] == "status" and e["message"] == "checkpoint 0" for e in bc.events)


def test_without_a_run_dir_nothing_is_written_and_checkpoint_is_a_no_op():
    loop = Loop(FakeEmulator(), RecordingBroadcaster(), LoopConfig(paced=False))
    assert asyncio.run(loop.checkpoint()) is None


# --- the scored faint prediction ---------------------------------------------------------------

FAINT_RESPONSE = {
    **RESPONSE,
    "answers": {**RESPONSE["answers"], "faint": {"type": "noul", "noul": 0.8}},
}


def faint_loop(tmp_path):
    """A battle at the menu, a brain that predicts a faint, and a run dir to resolve it into."""
    from jevplays.runlog import RunDir

    emu = battle_emu()
    presses = []
    original = emu.press

    def press(button, **kw):
        presses.append(button)
        r = original(button, **kw)
        if presses == ["a"]:
            emu.set_rows(MOVES)
        return r

    emu.press = press
    run_dir = RunDir.create(tmp_path, rom=None, flags={})
    loop = Loop(
        emu,
        RecordingBroadcaster(),
        LoopConfig(paced=False),
        brain=FakeBrain(response=FAINT_RESPONSE),
        run_dir=run_dir,
    )
    return emu, loop, run_dir


def test_a_faint_prediction_waits_for_the_game_to_answer_it(tmp_path):
    emu, loop, run_dir = faint_loop(tmp_path)
    run(loop, 1)
    assert run_dir.count() == 1
    assert list(run_dir.outcomes()) == []


def test_a_faint_prediction_is_resolved_against_the_party_at_the_next_menu(tmp_path):
    emu, loop, run_dir = faint_loop(tmp_path)
    run(loop, 1)
    configure_battle_memory(emu, hp=0)  # RATTATA knocked it out while the animation played
    emu.set_rows(BATTLE_MENU)
    run(loop, 1)
    resolved = list(run_dir.outcomes())
    assert [(o["decision_id"], o["predicted"], o["observed"]) for o in resolved] == [
        (loop.decisions[0].id, 0.8, True)
    ]


def test_a_prediction_is_resolved_once_and_not_again(tmp_path):
    emu, loop, run_dir = faint_loop(tmp_path)
    run(loop, 3)
    ids = [o["decision_id"] for o in run_dir.outcomes()]
    assert len(ids) == len(set(ids))


def test_without_a_run_dir_nothing_is_written_but_the_loop_still_runs(tmp_path):
    emu, loop, _ = faint_loop(tmp_path)
    loop.run_dir = None
    run(loop, 2)
    assert loop.decisions
