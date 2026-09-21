#!/usr/bin/env -S uv run
"""Record real TypeSafe responses for the saved states, for the unit tests to replay.

    mise exec -- uv run Scripts/record-fixtures.py [--only NAME ...]

Needs JEVPLAYS_ROM, the save states `Scripts/make-states.py` writes, and TYPESAFE_API_KEY.
Writes tests/fixtures/responses/<name>.json. Re-run when the questions change or when a field
Jev sees changes; commit the result. One fixture per decision point:

    battle_trainer  the rival battle's FIGHT menu
    battle_wild     a wild battle's FIGHT menu
    battle_catch    a wild battle with balls in the bag and the enemy nearly down
    battle_heal     the same battle with the lead hurt and Potions in the bag
    battle_switch   a wild battle with a hurt lead and a second Pokémon on the bench
    goal_route1     which goal to pursue, standing on Route 1 with the parcel undelivered
    goal_hurt       the same, with the lead below half HP so healing is on the table
    explore_viridian  which generated option to pick, standing near the old man in Viridian City
    prompt_starter  the "Do you want CHARMANDER?" YES/NO box
    menu_start      the START menu in Red's bedroom

The fixture holds the state Jev was shown, the questions it was asked, and its raw response --
never an API key, and never anything the state summaries do not already carry.
"""

import argparse
import asyncio
import inspect
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

from jevplays.brain.battle import battle_questions, battle_state
from jevplays.brain.client import Brain
from jevplays.brain.explore import explore_questions, explore_state
from jevplays.brain.goal import goal_questions, goal_state
from jevplays.brain.prompt import menu_questions, menu_state, prompt_questions, prompt_state
from jevplays.emulator import ram
from jevplays.emulator.pyboy import Emulator
from jevplays.executor.goals import active_milestone, available_goals, battle_goal, goal_by_id
from jevplays.executor.options import Memory, generate
from jevplays.state.snapshot import GameState, snapshot

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "responses"
GOAL = battle_goal(goal_by_id("train_nearby"), fallback="Win every battle and explore")
"""The objective recorded with the battle fixtures. Composed the way the loop composes it (an
active goal plus the standing clause) rather than written out here, so a change to either one
shows up in the fixtures instead of drifting away from what a run actually sends."""

HURT_HP = 3
"""What the lead's HP is set to for `goal_hurt`. No saved state has a lead below half health --
the walk that makes them heals or ends before it gets that far -- so the one decision point that
only exists when the party is hurt is built by writing the HP into the party record directly.
That is the same memory `snapshot` reads, so what Jev sees is a state the game could be in."""


def hurt_the_lead(emu: Emulator) -> None:
    """Knock the first party slot down to `HURT_HP` (wPartyMon1HP, a big-endian u16)."""
    addr = ram.wPartyMons + ram.MON_HP
    emu.mem[addr] = HURT_HP >> 8
    emu.mem[addr + 1] = HURT_HP & 0xFF


ALMOST_CAUGHT_HP = 2
"""What the enemy's HP is set to for `battle_catch`: low enough that a ball is worth a turn.
Same doctoring as `HURT_HP`, on the record `snapshot` reads for the enemy."""


def hurt_the_active(emu: Emulator) -> None:
    """`hurt_the_lead`, plus the in-battle copy at wBattleMonHP.

    The game copies the active party record into wBattleMon... when a Pokémon comes out, and
    that copy is what `snapshot` reports as `active` during a battle -- while the game's own
    item code reads the party record back. A battle fixture has to move both, or Jev is shown a
    hurt Pokémon the game would refuse to heal.
    """
    hurt_the_lead(emu)
    emu.mem[ram.wBattleMonHP] = HURT_HP >> 8
    emu.mem[ram.wBattleMonHP + 1] = HURT_HP & 0xFF


def weaken_the_enemy(emu: Emulator) -> None:
    """Put the wild Pokémon on `ALMOST_CAUGHT_HP` (wEnemyMonHP, a big-endian u16)."""
    emu.mem[ram.wEnemyMonHP] = ALMOST_CAUGHT_HP >> 8
    emu.mem[ram.wEnemyMonHP + 1] = ALMOST_CAUGHT_HP & 0xFF


def battle_ask(state: GameState) -> tuple[dict, dict]:
    sj = battle_state(state, goal=GOAL)
    return sj, battle_questions(sj)


def goal_ask(state: GameState) -> tuple[dict, dict]:
    sj = goal_state(state, available_goals(state))
    return sj, goal_questions(sj)


def explore_ask(emu, state: GameState) -> tuple[dict, dict]:
    milestone = active_milestone(state)
    options = generate(emu, state, Memory.empty(), milestone)
    sj = explore_state(state, options, milestone)
    return sj, explore_questions(sj)


def starter_prompt_ask(state: GameState) -> tuple[dict, dict]:
    sj = prompt_state(state, goal_by_id("get_starter").description)
    return sj, prompt_questions(sj)


def start_menu_ask(state: GameState) -> tuple[dict, dict]:
    sj = menu_state(state, goal_by_id("get_starter").description)
    return sj, menu_questions(sj)


Ask = Callable[..., tuple[dict, dict]]
"""`ask(state)` for most decision points; `ask(emu, state)` for one that needs live RAM
(`explore_ask`, which calls `executor.options.generate`) -- `record` tells them apart by how
many parameters `ask` takes."""
Tweak = Callable[[Emulator], None] | None

FIXTURES: dict[str, tuple[str, Ask, Tweak]] = {
    "battle_trainer": ("battle_trainer", battle_ask, None),
    "battle_wild": ("battle_wild", battle_ask, None),
    "battle_catch": ("battle_items", battle_ask, weaken_the_enemy),
    "battle_heal": ("battle_items", battle_ask, hurt_the_active),
    "battle_switch": ("battle_two", battle_ask, hurt_the_active),
    "goal_route1": ("route1", goal_ask, None),
    "goal_hurt": ("route1", goal_ask, hurt_the_lead),
    "explore_viridian": ("viridian_oldman", explore_ask, None),
    "prompt_starter": ("prompt_starter", starter_prompt_ask, None),
    "menu_start": ("menu", start_menu_ask, None),
}
"""fixture name -> (save state to load, what to ask about it, how to doctor the state first)."""


def summarize(response: dict) -> str:
    parts = []
    for qid, answer in response["answers"].items():
        if answer["type"] == "choice":
            probs = ", ".join(f"{k} {v:.2f}" for k, v in sorted(answer["probabilities"].items()))
            parts.append(f"{qid}={answer['choice']} ({probs}) confidence {answer['confidence']:.2f}")
        else:
            parts.append(f"{qid}={answer['noul']:.2f}")
    return "; ".join(parts)


async def record(rom: Path, states: Path, names: list[str]) -> None:
    brain = Brain()
    try:
        for name in names:
            state_name, ask, tweak = FIXTURES[name]
            with Emulator(rom) as emu:
                emu.load(states / f"{state_name}.state")
                if tweak is not None:
                    tweak(emu)
                state = snapshot(emu)
                needs_emu = len(inspect.signature(ask).parameters) == 2
                sj, qs = ask(emu, state) if needs_emu else ask(state)
            response, ms = await brain.ask(sj, qs)
            OUT.mkdir(parents=True, exist_ok=True)
            (OUT / f"{name}.json").write_text(
                json.dumps(
                    {
                        "state": state.to_dict(),
                        "state_json": sj,
                        "questions": qs,
                        "response": response,
                        "latency_ms": ms,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            print(f"{name}: {summarize(response)} in {ms} ms")
    finally:
        await brain.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--only",
        action="append",
        choices=sorted(FIXTURES),
        default=None,
        help="record just this fixture; repeatable. Default: all of them.",
    )
    args = parser.parse_args(argv)
    rom = os.environ.get("JEVPLAYS_ROM")
    if not rom or not os.environ.get("TYPESAFE_API_KEY"):
        print("need JEVPLAYS_ROM and TYPESAFE_API_KEY", file=sys.stderr)
        return 2
    names = args.only or list(FIXTURES)
    asyncio.run(record(Path(rom), Path(os.environ.get("JEVPLAYS_STATES", "states")), names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
