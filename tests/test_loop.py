import asyncio

import pytest

from jevplays.brain.decision import PromptAction
from jevplays.brain.errors import BrainUnavailable
from jevplays.emulator import ram
from jevplays.executor import maps
from jevplays.executor.goals import MILESTONES
from jevplays.executor.options import Option
from jevplays.executor.world import build_grid
from jevplays.loop import OPTION_BUDGET_S, Loop, LoopConfig, local_decision
from jevplays.state.events import EVENTS
from jevplays.state.modes import Mode
from jevplays.state.snapshot import snapshot
from tests.support import FakeEmulator, install_map, overworld_state, write_mon
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
from tests.test_options import town

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


# --- milestone 3: navigation, prompts, and menus ---------------------------------------------

OVERWORLD_MAP = ["." * 12] * 8
"""12x8 walkable tiles: room enough for get_starter's walk to (10, 1)."""


class QuestionBrain:
    """Answers by question id, so one fake serves the explore, prompt, and menu branches."""

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
            if isinstance(value, str):
                # The explore question is answered with an option id and nothing to weigh.
                answered[qid] = {
                    "type": "choice",
                    "choice": value,
                    "probabilities": {value: 1.0},
                    "confidence": 0.9,
                }
            elif isinstance(value, dict):
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


MAKE_ROOM_ROWS = (
    PROMPT_ROWS
    + [""] * 4
    + [
        "·Delete an older····",
        "·move to make room··",
        "·for RAGE?··········",
    ]
)
ABANDON_ROWS = (
    PROMPT_ROWS
    + [""] * 4
    + [
        "····················",
        "·Abandon learning···",
        "·RAGE?··············",
    ]
)


def test_the_move_learning_ring_is_answered_by_policy_and_never_reaches_jev():
    """#55. Gen 1 asks two questions in a ring: NO to "make room" leads to "Abandon learning X?",
    and NO to that leads straight back to "make room". No NO path leaves it, and Jev is stateless,
    so the 297th ask looks new -- one run spent 594 contiguous decisions there, 56% of itself.
    Policy answers both: keep the moveset, abandon the new move, two presses and out."""
    for (
        rows,
        expected,
    ) in ((MAKE_ROOM_ROWS, ["down", "a"]), (ABANDON_ROWS, ["a"])):
        emu, bc = prompt_emu(rows), RecordingBroadcaster()
        brain = QuestionBrain(prompt=0.99)
        loop = Loop(emu, bc, LoopConfig(paced=False), brain=brain)
        run(loop, 1)
        assert brain.calls == 0
        assert emu.presses == expected
        assert "fifth move" in loop.decisions[-1].fallback_reason


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
    start_option(loop, grass_option(), maps.ROUTE_1)  # no legs, so `wander` runs every turn
    run(loop, 12)
    grid = build_grid(emu)
    here = (emu.mem[ram.wXCoord], emu.mem[ram.wYCoord])
    assert grid.is_grass(*here), f"{here} is not grass"
    assert loop.memory.tried == set()
    assert emu.presses  # it walked there a step at a time


def test_wander_gives_up_on_a_map_with_no_grass_at_all():
    emu, bc = overworld_emu(), RecordingBroadcaster()
    install_map(emu, OVERWORLD_MAP)  # every cell is road
    loop = Loop(emu, bc, LoopConfig(paced=False))
    assert loop._wander(snapshot(emu)) is False
    assert emu.presses == []


MART_PARCEL = "got_oaks_parcel"


def test_talk_oak_in_the_mart_presses_nothing_once_the_parcel_is_already_in_hand():
    emu, bc = overworld_emu(), RecordingBroadcaster()
    loop = Loop(emu, bc, LoopConfig(paced=False))
    state = overworld_state(map_id=maps.VIRIDIAN_MART, flags=(MART_PARCEL,))
    assert loop._apply_macro("talk_oak", state) is True
    assert emu.presses == []


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


# --- milestone 4b: Jev explores the options the map affords -----------------------------------

UNMAPPED_MAP = 200
"""Not in maps.NODE_NAMES, so node_of() calls it "map_200", no route starts from it, and the
milestone option is left out: what is left is exactly the options generated from the map."""


def set_flag(emu, name: str) -> None:
    """Set one story flag in the fake's memory, the way `state.events.flags_set` reads it."""
    n = EVENTS[name]
    emu.mem[ram.wEventFlags + n // 8] = emu.mem[ram.wEventFlags + n // 8] | (1 << (n % 8))


def explore_emu(map_id=UNMAPPED_MAP, **kw):
    """The option fixture map (`tests.test_options.town`: two connections, two doors, a nurse
    behind a counter, a youngster, and a patch of grass) with a party and a map id of its own."""
    emu, _state, _memory = town(**kw)
    emu.mem[ram.wCurMap] = map_id
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


def grass_option():
    return Option(
        id="grass",
        kind="grass",
        text="train in the tall grass here",
        memory="new",
        legs=(),
        after="wander",
    )


def start_option(loop, option, map_id, arrived_on=None):
    """Put the loop where `_choose_option` would have left it: this option taken on, its legs
    (of which an absorbing option has none) already finished. `arrived_on` is the map the legs
    ended on, which is `map_id` for an option that acts where it stands."""
    loop.option = option
    loop.option_started_at = loop.clock()
    loop._option_map = map_id
    loop._arrived_map = map_id if arrived_on is None else arrived_on
    loop._arrived = True


def macro_less(option_id="milestone", kind="milestone"):
    return Option(
        id=option_id, kind=kind, text="work on the milestone: somewhere", memory="new", legs=(), after=None
    )


def test_an_arrived_option_whose_map_changed_under_it_is_dropped():
    """#50. A blackout during the grass option moves the run to Pallet Town, which has grass
    tiles but no encounter table -- so `wander` steps around a town where no battle can start
    until OPTION_BUDGET_S (90 seconds of *wall clock*) runs out. `_walk` already drops an option
    the map changed under, but only while the navigator is busy; one that has arrived and is
    running its macro never looked again."""
    emu, bc = explore_emu(map_id=maps.ROUTE_1), RecordingBroadcaster()
    loop = Loop(emu, bc, LoopConfig(paced=False))
    start_option(loop, grass_option(), maps.ROUTE_1)
    emu.mem[ram.wCurMap] = maps.PALLET_TOWN  # blacked out mid-wander
    asyncio.run(loop._overworld_turn(snapshot(emu)))
    assert loop.option is None
    assert loop.memory.tried == set()  # it was displaced, not tried and found wanting


def test_an_option_that_walked_us_to_another_map_is_not_dropped_as_displaced():
    """An exit or a door arrives somewhere else on purpose -- that is the whole of it. The check
    is against the map the legs ended on, not the map the option was generated on."""
    emu, bc = explore_emu(map_id=maps.ROUTE_1), RecordingBroadcaster()
    loop = Loop(emu, bc, LoopConfig(paced=False))
    door = Option(id="door_41", kind="door", text="enter somewhere", memory="new", legs=(), after=None)
    start_option(loop, door, maps.PALLET_TOWN, arrived_on=maps.ROUTE_1)
    asyncio.run(loop._overworld_turn(snapshot(emu)))
    assert [e["message"] for e in bc.events if e.get("type") == "status" and "done" in str(e.get("message"))]


def test_an_option_that_does_nothing_at_all_is_remembered_as_tried():
    """#53's backstop. An option with no macro that finishes on the map it started on moved
    nothing and did nothing. Without a memory stamp it comes back `(new)` and can be chosen
    again forever -- which is how one probe made 654 identical decisions in 86 seconds."""
    emu, bc = explore_emu(), RecordingBroadcaster()
    loop = Loop(emu, bc, LoopConfig(paced=False))
    here = emu.mem[ram.wCurMap]
    start_option(loop, macro_less(), here)
    asyncio.run(loop._run_macro(snapshot(emu)))
    assert (here, "milestone") in loop.memory.tried


def test_a_door_that_carried_us_somewhere_is_not_remembered_as_tried():
    """Exits and doors are macro-less too, and arriving is the whole of them. Marking one
    `tried` would tell Jev that leaving worked out badly when it worked exactly as asked."""
    emu, bc = explore_emu(), RecordingBroadcaster()
    loop = Loop(emu, bc, LoopConfig(paced=False))
    started_on = emu.mem[ram.wCurMap] + 1  # the door was taken from the map next door
    start_option(loop, macro_less(option_id="door_41", kind="door"), started_on)
    asyncio.run(loop._run_macro(snapshot(emu)))
    assert loop.memory.tried == set()


def test_an_idle_overworld_asks_once_and_walks_the_option_jev_picked():
    emu, bc = explore_emu(), RecordingBroadcaster()
    brain = QuestionBrain(explore="exit_north", needs_heal=0.1)
    loop = Loop(emu, bc, LoopConfig(paced=False), brain=brain)
    run(loop, 3)
    assert brain.calls == 1  # asked once, then the navigator just walks
    assert brain.asked[0] == ["explore", "needs_heal"]
    assert loop.option is not None and loop.option.id == "exit_north"
    assert [d.kind for d in loop.decisions] == ["explore"]
    decision = loop.decisions[0]
    assert decision.action_value.kind == "exit" and decision.action == "explore: go north to Route 2"
    assert decision.state_summary["options"]["exit_north"] == "go north to Route 2 (new)"
    assert any(p in ("up", "down", "left", "right") for p in emu.presses)


def test_without_a_brain_the_milestone_is_taken_first_and_recorded():
    emu, bc = explore_emu(map_id=maps.PALLET_TOWN), RecordingBroadcaster()
    loop = Loop(emu, bc, LoopConfig(paced=False))
    run(loop, 1)
    assert loop.option is not None and loop.option.kind == "milestone"
    assert [d.kind for d in loop.decisions] == ["explore"]
    assert loop.decisions[0].fallback and "no brain" in loop.decisions[0].fallback_reason
    assert [e["type"] for e in bc.events if e["type"] == "decision"] == ["decision"]


def talking_emu(**kw):
    """`explore_emu`, with an A press that opens dialog and a second that closes it again --
    what `talk_to` waits for before it calls the sprite talked to."""
    emu = explore_emu(**kw)
    original = emu.press

    def press(button, **kw):
        r = original(button, **kw)
        if button == "a":
            emu.set_rows([] if snapshot(emu).mode is Mode.DIALOG else DIALOG)
        return r

    emu.press = press
    return emu


def test_an_npc_option_walks_up_talks_and_is_remembered_as_talked_to():
    emu, bc = talking_emu(), RecordingBroadcaster()
    brain = QuestionBrain(explore="npc_4", needs_heal=0.1)
    loop = Loop(emu, bc, LoopConfig(paced=False), brain=brain)
    run(loop, 20)
    assert (UNMAPPED_MAP, 4) in loop.memory.talked
    assert "a" in emu.presses  # it did not just walk there
    messages = [e["message"] for e in bc.events if e["type"] == "status"]
    assert any(m == "npc_4: talk_4" for m in messages)


def test_a_stuck_navigator_marks_the_option_tried_and_the_next_ask_says_so():
    emu, bc = explore_emu(), RecordingBroadcaster()
    emu.step_effects = {}  # nothing the navigator presses ever moves the player
    brain = QuestionBrain(explore="exit_north", needs_heal=0.1)
    loop = Loop(emu, bc, LoopConfig(paced=False), brain=brain)
    run(loop, 40)
    assert (UNMAPPED_MAP, "exit_north") in loop.memory.tried
    assert brain.calls >= 2  # asked again once the option was given up on
    tried = [e["message"] for e in bc.events if e["type"] == "status" and e["message"].startswith("tried:")]
    assert tried and "go north to Route 2" in tried[0] and "the navigator gave up" in tried[0]
    assert loop.decisions[-1].state_summary["options"]["exit_north"] == "go north to Route 2 (tried)"


def test_an_option_that_outstays_its_budget_is_dropped_and_marked_tried():
    """The grass is never done and never fails, so without a budget the first time Jev picked it
    would be the last decision it ever made."""
    emu, bc = explore_emu(), RecordingBroadcaster()
    brain = QuestionBrain(explore="grass", needs_heal=0.1)
    loop = Loop(emu, bc, LoopConfig(paced=False), brain=brain)
    now = [1000.0]
    loop.clock = lambda: now[0]
    run(loop, 3)
    assert loop.option is not None and loop.option.id == "grass" and brain.calls == 1
    now[0] += OPTION_BUDGET_S + 1
    run(loop, 2)
    assert brain.calls == 2  # the budget handed the decision back
    assert (UNMAPPED_MAP, "grass") in loop.memory.tried
    messages = [e["message"] for e in bc.events if e["type"] == "status"]
    assert any(m.startswith("tried: train in the tall grass here;") for m in messages)


def test_the_budget_starts_when_the_legs_finish_so_a_long_walk_is_never_cancelled():
    """The budget is for the macro phase, not the walk. Paced, Route 1 to the Viridian Mart takes
    151 s, so a budget that spanned the legs would cancel that option on the turn it arrived --
    before its macro ran, and writing a `tried` that says nothing true about the option. (The
    firing half is `test_an_option_that_outstays_its_budget_is_dropped_and_marked_tried`: the
    grass has no legs, so its budget is the macro phase from the start.)"""
    emu, bc = talking_emu(), RecordingBroadcaster()
    brain = QuestionBrain(explore="npc_4", needs_heal=0.1)
    loop = Loop(emu, bc, LoopConfig(paced=False), brain=brain)
    now = [1000.0]
    loop.clock = lambda: now[0]
    run(loop, 1)  # asks, and plans the walk to the sprite's neighbour
    assert loop.navigator.busy
    now[0] += OPTION_BUDGET_S * 10  # a very long walk indeed
    run(loop, 20)
    assert (UNMAPPED_MAP, 4) in loop.memory.talked  # the macro ran on arrival
    assert loop.memory.tried == set()  # and nothing was blamed for the walk taking a while


def test_a_counter_npc_is_not_remembered_as_talked_to(monkeypatch):
    """A nurse and a shop clerk are worth going back to, so neither is marked `talked already`:
    that word tells Jev there is no point doing it again."""
    from jevplays.executor import shop as shop_module

    monkeypatch.setattr(shop_module, "heal_at_nurse", lambda emu: True)
    emu, bc = explore_emu(), RecordingBroadcaster()
    loop = Loop(emu, bc, LoopConfig(paced=False))
    start_option(
        loop,
        Option(
            id="npc_3",
            kind="npc",
            text="talk to the nurse behind the counter",
            memory="new",
            legs=(),
            after="heal",
            target=(2, 1),
            face="left",
        ),
        UNMAPPED_MAP,
    )
    asyncio.run(loop.advance(snapshot(emu)))
    assert loop.memory.talked == set() and loop.memory.tried == set()
    assert loop.option is None  # it worked; the option is simply let go of


def test_a_map_with_nothing_to_do_says_so_once_rather_than_every_iteration():
    emu, bc = FakeEmulator(), RecordingBroadcaster()
    install_map(emu, ["##", "##"])  # one block of wall: no exits, no doors, no grass, no sprites
    emu.mem[ram.wCurMap] = UNMAPPED_MAP  # and no milestone option, since no route starts here
    loop = Loop(emu, bc, LoopConfig(paced=False))
    run(loop, 3)
    paused = [e for e in bc.events if e["type"] == "status" and e["status"] == "paused"]
    assert len(paused) == 1 and paused[0]["message"] == "nothing to do from here"
    assert loop.decisions == [] and emu.presses == []


def test_the_last_milestone_being_done_finishes_the_run():
    emu, bc = explore_emu(map_id=maps.PALLET_TOWN), RecordingBroadcaster()
    for flag in ("got_starter", "got_pokedex", "beat_brock"):
        set_flag(emu, flag)
    emu.mem[ram.wObtainedBadges] = 1  # the badge bit, not just the flag, is what finishes (#40)
    loop = Loop(emu, bc, LoopConfig(paced=False))
    asyncio.run(loop.run())  # no iteration cap: the run ends of its own accord
    assert loop.finished and loop.milestone is None
    finished = [e for e in bc.events if e["type"] == "status" and e["status"] == "finished"]
    assert len(finished) == 1 and finished[0]["message"] == "Boulder Badge"
    assert loop.decisions == []  # nothing left to explore towards


def test_a_milestone_reached_mid_run_is_announced_and_the_next_one_taken_up():
    emu, bc = explore_emu(map_id=maps.PALLET_TOWN), RecordingBroadcaster()
    loop = Loop(emu, bc, LoopConfig(paced=False))
    run(loop, 1)
    assert loop.milestone.id == "get_starter"
    set_flag(emu, "got_starter")
    run(loop, 1)
    assert loop.milestone.id == "get_pokedex"
    assert "milestone done: get_starter" in [e["message"] for e in bc.events if e["type"] == "status"]


def test_a_macro_that_raises_marks_the_option_tried_instead_of_killing_the_run():
    emu, bc = explore_emu(), RecordingBroadcaster()
    loop = Loop(emu, bc, LoopConfig(paced=False))
    start_option(
        loop,
        Option(
            id="npc_9",
            kind="npc",
            text="talk to someone to the north",
            memory="new",
            legs=(),
            after="no_such_macro",
            target=(1, 1),
            face="up",
        ),
        UNMAPPED_MAP,
    )
    asyncio.run(loop.advance(snapshot(emu)))
    assert loop.option is None
    assert loop.memory.tried == {(UNMAPPED_MAP, "npc_9")}
    message = [e["message"] for e in bc.events if e["type"] == "status"][-1]
    assert "no_such_macro raised ValueError" in message


def test_an_option_that_carried_the_run_to_another_map_is_not_marked_tried_back_home():
    """`tried` means the option changed nothing (spec section 3). A milestone option whose legs
    walked the run out of Pallet Town and whose macro then failed in the lab changed plenty:
    marking it against Pallet Town would tell Jev, next time it stands there, that working on the
    milestone from there leads nowhere. The failure is still published either way."""
    emu, bc = explore_emu(map_id=maps.OAKS_LAB), RecordingBroadcaster()
    loop = Loop(emu, bc, LoopConfig(paced=False))
    start_option(
        loop,
        Option(
            id="milestone",
            kind="milestone",
            text="work on the milestone: Get a starter",
            memory="new",
            legs=(),
            after="no_such_macro",
        ),
        maps.PALLET_TOWN,  # where the option was generated, before its legs moved us
        arrived_on=maps.OAKS_LAB,  # ... and where they left us
    )
    asyncio.run(loop.advance(snapshot(emu)))
    assert loop.option is None and loop.memory.tried == set()
    messages = [e["message"] for e in bc.events if e["type"] == "status"]
    assert any(m.startswith("tried: work on the milestone") for m in messages)

    # The grass never leaves the map it was offered on, so its budget running out is exactly the
    # "nothing came of it" the word is for, and it is marked.
    now = [1000.0]
    loop.clock = lambda: now[0]
    start_option(loop, grass_option(), maps.OAKS_LAB)
    now[0] += OPTION_BUDGET_S + 1
    asyncio.run(loop.advance(snapshot(emu)))
    assert loop.memory.tried == {(maps.OAKS_LAB, "grass")}


def test_an_unmapped_map_offers_the_way_back_out_and_a_brainless_loop_takes_it():
    """No route starts from a map the graph does not know, so the milestone option is left out
    and the door back the way we came in is the only thing here worth doing."""
    emu, bc = (
        explore_emu(sprites=(), connections={}, warps=[(3, 3, 0, ram.WARP_LAST_MAP)]),
        (RecordingBroadcaster()),
    )
    loop = Loop(emu, bc, LoopConfig(paced=False))
    loop.memory.note_tried(UNMAPPED_MAP, "grass")
    run(loop, 1)
    assert loop.option is not None and loop.option.id == f"door_{ram.WARP_LAST_MAP}"
    assert loop.option.text == "go back outside"
    leg = loop.navigator.current
    assert leg is not None and leg.kind == "warp" and leg.dest_map == ram.WARP_LAST_MAP


def test_a_crossing_the_run_walked_is_added_to_its_map_graph():
    """#35. The graph is built from crossings actually made, so the run can plan its way back
    from a map nobody typed into `maps.LINKS`. The reverse link is recorded too: without it the
    way home would need a second walk to learn, which is the whole point of keeping it."""
    emu, bc = (
        explore_emu(sprites=(), connections={}, warps=[(3, 3, 0, ram.WARP_LAST_MAP)]),
        RecordingBroadcaster(),
    )
    loop = Loop(emu, bc, LoopConfig(paced=False))
    loop.memory.note_tried(UNMAPPED_MAP, "grass")
    run(loop, 1)  # takes the door back outside and plans its warp leg
    assert loop.navigator.current.kind == "warp"
    emu.mem[ram.wCurMap] = maps.PALLET_TOWN  # the warp lands us there
    run(loop, 1)
    here = f"map_{UNMAPPED_MAP}"
    assert [(x.kind, x.dest_node) for x in loop.memory.links[here]] == [("warp", "pallet_town")]
    assert ("warp", here) in [(x.kind, x.dest_node) for x in loop.memory.links["pallet_town"]]


def test_a_blackout_mid_walk_teaches_the_graph_nothing():
    """A leg that came back `lost` never crossed anything -- the map changed under it. Recording
    that as a link would invent a road from wherever we were to wherever the blackout put us."""
    emu, bc = explore_emu(map_id=maps.PALLET_TOWN), RecordingBroadcaster()
    loop = Loop(emu, bc, LoopConfig(paced=False))
    run(loop, 1)
    emu.mem[ram.wCurMap] = maps.VIRIDIAN_POKECENTER  # blacked out mid-walk
    run(loop, 1)
    assert loop.memory.links == {}


def test_a_map_change_under_a_plan_drops_the_option_and_asks_again():
    """The route was for a map we are not on any more, and so was the option list it came from:
    the next turn generates fresh options rather than charging this one with anything."""
    emu, bc = explore_emu(map_id=maps.PALLET_TOWN), RecordingBroadcaster()
    loop = Loop(emu, bc, LoopConfig(paced=False))
    run(loop, 1)  # picks an option and plans its legs
    assert loop.navigator.busy and loop.navigator.current.kind == "walk"
    emu.mem[ram.wCurMap] = maps.VIRIDIAN_POKECENTER  # blacked out mid-walk
    run(loop, 1)
    assert loop.option is None and loop.memory.tried == set()
    assert "re-planning after a map change" in [e["message"] for e in bc.events if e["type"] == "status"]


def test_every_map_the_run_stands_on_is_remembered():
    emu = explore_emu(map_id=maps.PALLET_TOWN)
    loop = Loop(emu, RecordingBroadcaster(), LoopConfig(paced=False))
    run(loop, 1)
    assert loop.memory.visited_maps == {maps.PALLET_TOWN}
    emu.mem[ram.wCurMap] = maps.VIRIDIAN_CITY
    run(loop, 1)
    assert loop.memory.visited_maps == {maps.PALLET_TOWN, maps.VIRIDIAN_CITY}


def test_the_memory_is_written_to_the_run_dir_as_it_changes(tmp_path):
    from jevplays.runlog import RunDir

    run_dir = RunDir.create(tmp_path, rom=None, flags={})
    emu = explore_emu(map_id=maps.PALLET_TOWN)
    loop = Loop(emu, RecordingBroadcaster(), LoopConfig(paced=False), run_dir=run_dir)
    run(loop, 1)
    assert run_dir.load_memory()["visited_maps"] == [maps.PALLET_TOWN]


def test_a_resumed_loop_starts_from_the_memory_it_is_handed():
    from jevplays.executor.options import Memory

    emu, bc = explore_emu(), RecordingBroadcaster()
    memory = Memory.from_dict({"tried": [[UNMAPPED_MAP, "exit_north"]]})
    loop = Loop(emu, bc, LoopConfig(paced=False), memory=memory)
    run(loop, 1)
    assert loop.decisions[0].state_summary["options"]["exit_north"].endswith("(tried)")
    assert loop.option is not None and loop.option.id != "exit_north"  # a tried option is not first


def test_the_battle_question_carries_the_milestone_the_run_is_working_towards():
    emu = battle_emu()
    loop = Loop(
        emu,
        RecordingBroadcaster(),
        LoopConfig(paced=False, goal="Win every battle and explore"),
        brain=QuestionBrain(move={"SCRATCH": 1.0}),
    )
    loop.milestone = MILESTONES[-1]
    asyncio.run(loop.advance(snapshot(emu)))
    assert loop.decisions[0].state_summary["goal"] == (
        "Challenge Brock at the Pewter Gym and earn the Boulder Badge. "
        "Build a party of three and keep them healthy."
    )


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


def test_with_no_goal_picked_the_battle_question_carries_the_flag():
    emu = battle_emu()
    loop = Loop(
        emu,
        RecordingBroadcaster(),
        LoopConfig(paced=False, goal="Win every battle and explore"),
        brain=QuestionBrain(move={"SCRATCH": 1.0}),
    )
    asyncio.run(loop.advance(snapshot(emu)))
    assert loop.decisions[0].state_summary["goal"] == "Win every battle and explore"


# --- smooth playback (#31) ----------------------------------------------------------------


class CapturingEmulator(FakeEmulator):
    """A fake that hands back frames captured mid-tick, the way the real emulator does once the
    loop asks it to capture."""

    def __init__(self, captured):
        super().__init__()
        self.capture_every = 0
        self._captured = list(captured)
        self.jpegs = 0

    def take_frames(self):
        out, self._captured = self._captured, []
        return out

    def frame_jpeg(self, quality: int = 80) -> bytes:
        self.jpegs += 1
        return b"live"


def test_speed_shortens_the_wall_clock_a_paced_run_spends_on_its_frames():
    """A paced run plays at the game's own 60fps, which takes about two hours to reach Brock --
    right for watching a moment, wrong for a demo left running for people to drop in on. `speed`
    multiplies the clock the sleep is computed against, and only that: the same frames are
    emulated and the same decisions are made, they just arrive sooner."""
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    def paced_loop(speed):
        emu = CapturingEmulator([b"f1", b"f2"])
        return Loop(emu, RecordingBroadcaster(), LoopConfig(paced=True, idle_frames=60, fps=15, speed=speed))

    import jevplays.loop as loop_module

    real_sleep = loop_module.asyncio.sleep
    loop_module.asyncio.sleep = fake_sleep
    try:
        slept.clear()
        run(paced_loop(1.0), 1)
        at_one = sum(slept)
        slept.clear()
        run(paced_loop(4.0), 1)
        at_four = sum(slept)
    finally:
        loop_module.asyncio.sleep = real_sleep

    assert at_one > 0
    assert at_four == pytest.approx(at_one / 4, rel=0.2)


def test_speed_is_ignored_by_an_unpaced_run():
    """Unpaced has no clock to stretch: it never sleeps against emulated time, whatever `speed`
    says, because it is already going as fast as the emulator will."""
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    import jevplays.loop as loop_module

    real_sleep = loop_module.asyncio.sleep
    loop_module.asyncio.sleep = fake_sleep
    try:
        loop = Loop(
            CapturingEmulator([b"f1"]),
            RecordingBroadcaster(),
            LoopConfig(paced=False, idle_frames=60, speed=9.0),
        )
        run(loop, 1)
    finally:
        loop_module.asyncio.sleep = real_sleep
    assert [s for s in slept if s > 0] == []


def test_a_paced_iteration_plays_every_frame_it_captured():
    """One frame per batch is what made the page lurch: the batch is emulated in milliseconds and
    the rest of the step is spent asleep. The captured frames are played out across that sleep."""
    emu = CapturingEmulator([b"f1", b"f2", b"f3", b"f4"])
    bc = RecordingBroadcaster()
    loop = Loop(emu, bc, LoopConfig(paced=True, idle_frames=6, fps=15))
    run(loop, 1)
    frames = [e["jpeg"] for e in bc.events if e["type"] == "frame"]
    assert frames == ["ZjE=", "ZjI=", "ZjM=", "ZjQ="]  # base64 of f1..f4, in order


def test_an_unpaced_iteration_shows_the_live_screen_and_never_a_stale_one():
    """Unpaced runs do not capture, so there is no window to play anything across and the screen
    is grabbed live as before. Should a backlog exist anyway, none of it reaches the page: a
    viewer wants the screen as it is, not as it was several steps ago."""
    emu = CapturingEmulator([b"f1", b"f2", b"f3"])
    bc = RecordingBroadcaster()
    loop = Loop(emu, bc, LoopConfig(paced=False, idle_frames=6, fps=1000))
    run(loop, 1)
    frames = [e["jpeg"] for e in bc.events if e["type"] == "frame"]
    assert frames == ["bGl2ZQ=="]  # base64 of "live"
    assert emu.take_frames() == []  # the backlog was drained, not left to grow


def test_the_loop_asks_a_paced_emulator_to_capture_and_leaves_an_unpaced_one_alone():
    """Capturing costs an extra emulated frame and a JPEG every few frames; an unpaced run is
    measuring, not being watched, and should not pay for it."""
    watched = CapturingEmulator([])
    Loop(watched, RecordingBroadcaster(), LoopConfig(paced=True, fps=15))
    assert watched.capture_every == 4  # 60 / 15
    measuring = CapturingEmulator([])
    Loop(measuring, RecordingBroadcaster(), LoopConfig(paced=False, fps=15))
    assert measuring.capture_every == 0


def test_pacing_follows_the_frames_the_game_really_spent():
    """`_walk` returns NAV_STEP_FRAMES whatever the navigator actually emulated, so the returned
    counts are an estimate, not a clock. Pacing a run by them makes the game drift -- it sleeps
    for time the game never spent -- so the emulator's own frame count is the authority."""
    emu = CapturingEmulator([])
    loop = Loop(emu, RecordingBroadcaster(), LoopConfig(paced=True, idle_frames=6, fps=15))
    before = emu.frame_count()
    run(loop, 3)
    assert emu.frame_count() > before
    assert loop.game_frames == emu.frame_count() - before


def test_a_prediction_stays_open_after_the_battle_ends(tmp_path):
    """#51: the end of a battle is not us choosing again. Scoring here filed an answer while the
    lead was still walking around at 1 HP, and the encounter that knocked it out came after."""
    emu, loop, run_dir = faint_loop(tmp_path)
    run(loop, 1)
    configure_battle_memory(emu, hp=1)
    emu.mem[ram.wIsInBattle] = 0  # the battle is over; we walk out of it at 1 HP
    emu.set_rows(DIALOG)
    run(loop, 1)
    assert list(run_dir.outcomes()) == []


def test_a_faint_in_the_next_encounter_answers_the_prediction_that_was_open(tmp_path):
    """#51 end to end: survive at 1 HP, leave the battle, and be knocked out by the next
    encounter before a menu is ever reached. No question was asked about that encounter, so the
    faint answers the last prediction made -- which asked exactly this."""
    emu, loop, run_dir = faint_loop(tmp_path)
    run(loop, 1)
    configure_battle_memory(emu, hp=1)
    emu.mem[ram.wIsInBattle] = 0
    emu.set_rows(DIALOG)
    run(loop, 1)
    configure_battle_memory(emu, hp=0)  # the next encounter knocks it out, no menu in between
    emu.set_rows(DIALOG)
    run(loop, 1)
    configure_battle_memory(emu, hp=19)  # blacked out, healed, and choosing again
    emu.set_rows(BATTLE_MENU)
    run(loop, 1)
    assert [o["observed"] for o in run_dir.outcomes()] == [True]


def test_a_finished_run_answers_its_last_prediction(tmp_path):
    """A finished run never reaches another battle menu. Without this the last turn of every run
    goes unscored, which is data the resolve-at-battle-end rule used to keep."""
    from jevplays.calibration import Pending
    from jevplays.runlog import RunDir

    emu, bc = explore_emu(map_id=maps.PALLET_TOWN), RecordingBroadcaster()
    for flag in ("got_starter", "got_pokedex", "beat_brock"):
        set_flag(emu, flag)
    emu.mem[ram.wObtainedBadges] = 1
    run_dir = RunDir.create(tmp_path, rom=None, flags={})
    loop = Loop(emu, bc, LoopConfig(paced=False), run_dir=run_dir)
    loop._pending = Pending(decision_id="d1", slot=0, predicted=0.8)
    asyncio.run(loop.run())
    assert loop.finished
    assert [(o["decision_id"], o["observed"]) for o in run_dir.outcomes()] == [("d1", False)]


def test_the_loop_latches_a_faint_before_the_heal_can_hide_it(tmp_path):
    """#36: the lead faints, the blackout heals the party, and the next decision point reads a
    healthy Pokémon. The loop has to notice the zero while it is on screen."""
    emu, loop, run_dir = faint_loop(tmp_path)
    run(loop, 1)
    configure_battle_memory(emu, hp=0)  # "CHARMANDER fainted!"
    emu.set_rows(DIALOG)
    run(loop, 1)
    assert list(run_dir.outcomes()) == []  # nothing to resolve against yet
    configure_battle_memory(emu, hp=19)  # scurried to a Pokémon Center, back to full
    emu.set_rows(BATTLE_MENU)
    run(loop, 1)
    assert [o["observed"] for o in run_dir.outcomes()] == [True]


def test_the_clerk_option_restocks_and_a_full_bag_is_not_a_failure(monkeypatch):
    """The clerk macro buys what the bag still wants (balls, then Potions); with nothing wanted
    it does nothing and still counts as done, and a shelf that yields nothing counts as tried."""
    from jevplays.executor import shop as shop_module

    calls: list[str] = []
    monkeypatch.setattr(
        shop_module, "restock", lambda emu, state: calls.append("restock") or {"POKE BALL": 2}
    )
    monkeypatch.setattr(shop_module, "shopping_list", lambda state: [("POKE BALL", 2)])
    emu, bc = explore_emu(), RecordingBroadcaster()
    loop = Loop(emu, bc, LoopConfig(paced=False))
    assert loop._apply_macro("shop", snapshot(emu)) is True and calls == ["restock"]

    monkeypatch.setattr(shop_module, "shopping_list", lambda state: [])
    calls.clear()
    assert loop._apply_macro("shop", snapshot(emu)) is True and calls == []

    monkeypatch.setattr(shop_module, "shopping_list", lambda state: [("POTION", 3)])
    monkeypatch.setattr(shop_module, "restock", lambda emu, state: {"POTION": 0})
    assert loop._apply_macro("shop", snapshot(emu)) is False


# --- a demo nobody is watching, and a demo that has spent its day ---------------------------


class ViewedBroadcaster(RecordingBroadcaster):
    """A broadcaster the test decides the audience of. `wait_for_viewer` is where a paused run
    blocks, so it is also where the test lets time pass."""

    def __init__(self, idle: list[float], on_wait=None) -> None:
        super().__init__()
        self.idle = list(idle)
        """Seconds unwatched, one per call to idle_for; the last value repeats."""
        self.on_wait = on_wait

    def idle_for(self) -> float:
        return self.idle.pop(0) if len(self.idle) > 1 else self.idle[0]

    async def wait_for_viewer(self) -> None:
        self.events.append({"type": "waited"})
        self.idle = [0.0]
        if self.on_wait is not None:
            self.on_wait()


def test_a_run_nobody_has_watched_for_a_while_pauses_until_someone_does():
    """Every decision is TypeSafe quota, and a public link means most of the day nobody is on the
    page. Past `pause_after` seconds unwatched, the loop says so and stops -- no frames, no
    decisions, no emulation -- until a tab opens."""
    bc = ViewedBroadcaster(idle=[61.0])
    loop = Loop(FakeEmulator(), bc, LoopConfig(paced=False, idle_frames=7, pause_after=60))
    run(loop, 1)
    kinds = [e.get("status", e["type"]) for e in bc.events]
    assert kinds[:3] == ["unwatched", "waited", "running"]
    assert "state" in kinds[3:]  # the step it held back runs once someone is watching


def test_a_run_watched_recently_enough_or_with_no_pause_configured_never_pauses():
    bc = ViewedBroadcaster(idle=[59.0])
    run(Loop(FakeEmulator(), bc, LoopConfig(paced=False, idle_frames=7, pause_after=60)), 2)
    assert all(e["type"] != "waited" for e in bc.events)
    bc = ViewedBroadcaster(idle=[1e9])
    run(Loop(FakeEmulator(), bc, LoopConfig(paced=False, idle_frames=7)), 2)
    assert all(e["type"] != "waited" for e in bc.events)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_a_paused_run_picks_up_its_pace_where_it_left_off_instead_of_catching_up(monkeypatch):
    """The pacer schedules each step against the time the run started. Three hours unwatched
    would put every later step three hours overdue, and the run would play flat out -- a burst
    of decisions the moment someone opens the link -- until it caught up. The pause is not game
    time, so the schedule moves forward by it."""
    import jevplays.loop as loop_module

    clock = FakeClock()
    slept_after_resume: list[float] = []
    resumed = False

    async def fake_sleep(seconds):
        if resumed:
            slept_after_resume.append(seconds)
        clock.now += max(0.0, seconds)

    def three_hours_pass():
        nonlocal resumed
        clock.now += 3 * 3600
        resumed = True

    monkeypatch.setattr(loop_module, "monotonic", clock)
    monkeypatch.setattr(loop_module.asyncio, "sleep", fake_sleep)
    bc = ViewedBroadcaster(idle=[0.0, 999.0], on_wait=three_hours_pass)
    emu = CapturingEmulator([])
    loop = Loop(emu, bc, LoopConfig(paced=True, idle_frames=60, fps=15, pause_after=60))
    loop.clock = clock

    async def one_second_of_game(state):
        return emu.tick(60)

    loop.advance = one_second_of_game
    run(loop, 2)
    # One step of 60 frames at the game's own clock is a second of sleep, pause or no pause.
    assert sum(slept_after_resume) == pytest.approx(1.0, abs=0.05)


def test_a_pause_does_not_eat_the_budget_of_the_option_being_carried_out(monkeypatch):
    """An option has OPTION_BUDGET_S of wall clock before it is dropped as `tried`. Time spent
    paused is time nobody played, so it is not charged to the option."""
    clock = FakeClock()
    bc = ViewedBroadcaster(idle=[999.0], on_wait=lambda: setattr(clock, "now", clock.now + 3 * 3600))
    loop = Loop(FakeEmulator(), bc, LoopConfig(paced=False, idle_frames=7, pause_after=60))
    loop.clock = clock
    loop.option = Option(id="exit_north", kind="exit", text="go north", memory="new", legs=(), after=None)
    loop.option_started_at = clock.now - 10
    charged: list[float] = []

    async def advance(state):
        charged.append(clock.now - loop.option_started_at)
        return 7

    loop.advance = advance
    run(loop, 1)
    assert charged == [pytest.approx(10)]


def test_a_run_that_reaches_max_decisions_rests_and_keeps_the_page_up():
    """The demo's daily ceiling is carried by the process that spends it, so a supervisor that
    dies cannot leave a run spending past it. At the limit the loop makes no more decisions and
    says why on the page, and waits -- the dashboard stays up for anyone who opens the link."""
    bc = RecordingBroadcaster()
    loop = Loop(FakeEmulator(), bc, LoopConfig(paced=False, idle_frames=7, max_decisions=2))
    loop.decisions += [local_decision("prompt", {}, PromptAction("yes"), "test")] * 2

    async def scenario():
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(loop.run(max_iterations=5), 0.2)

    asyncio.run(scenario())
    statuses = [e for e in bc.events if e["type"] == "status"]
    assert [e["status"] for e in statuses] == ["resting"]
    assert "budget" in statuses[0]["message"]
    assert all(e["type"] == "status" for e in bc.events)  # nothing else ran


def test_max_decisions_counts_this_session_not_a_resumed_log():
    bc = RecordingBroadcaster()
    loop = Loop(FakeEmulator(), bc, LoopConfig(paced=False, idle_frames=7, max_decisions=1))
    loop._logged_before = 500  # a resumed run's history was spent on earlier days
    # Resting never returns, so a loop that wrongly rests shows up as a timeout, not a hang.
    asyncio.run(asyncio.wait_for(loop.run(max_iterations=1), 1))
    assert all(e.get("status") != "resting" for e in bc.events)


def test_a_faster_run_captures_less_often_so_the_page_still_gets_fps_frames_a_second():
    """`fps` is what a viewer's page receives per second of wall clock. At six times the game's
    clock, capturing every fourth game frame sent 90 a second -- about 720 KiB/s to every tab, all
    of it from a home upload once the link is public. The capture interval scales with speed."""
    six = CapturingEmulator([])
    Loop(six, RecordingBroadcaster(), LoopConfig(paced=True, fps=15, speed=6.0))
    assert six.capture_every == 24  # 60 * 6 / 15
    one = CapturingEmulator([])
    Loop(one, RecordingBroadcaster(), LoopConfig(paced=True, fps=15, speed=1.0))
    assert one.capture_every == 4
