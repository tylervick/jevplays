#!/usr/bin/env -S uv run
"""Record real TypeSafe responses for the battle save states, for the unit tests to replay.

    mise exec -- uv run Scripts/record-fixtures.py

Needs JEVPLAYS_ROM, states/battle_trainer.state, states/battle_wild.state, and TYPESAFE_API_KEY.
Writes tests/fixtures/responses/<name>.json. Re-run when the questions change; commit the result.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from jevplays.brain.battle import battle_questions, battle_state
from jevplays.brain.client import Brain
from jevplays.emulator.pyboy import Emulator
from jevplays.state.snapshot import snapshot

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "responses"
GOAL = "Win the first battle"


async def record(rom: Path, states: Path) -> None:
    brain = Brain()
    try:
        for name in ("battle_trainer", "battle_wild"):
            with Emulator(rom) as emu:
                emu.load(states / f"{name}.state")
                state = snapshot(emu)
            sj = battle_state(state, goal=GOAL)
            qs = battle_questions(sj)
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
            move = response["answers"]["move"]
            print(
                f"{name}: {move['choice']} {move['probabilities']} confidence {move['confidence']} in {ms} ms"
            )
    finally:
        await brain.close()


def main() -> int:
    rom = os.environ.get("JEVPLAYS_ROM")
    if not rom or not os.environ.get("TYPESAFE_API_KEY"):
        print("need JEVPLAYS_ROM and TYPESAFE_API_KEY", file=sys.stderr)
        return 2
    asyncio.run(record(Path(rom), Path(os.environ.get("JEVPLAYS_STATES", "states"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
