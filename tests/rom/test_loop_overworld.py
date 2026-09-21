"""The loop playing the overworld against the real game, from `states/route1.state`."""

import asyncio

from jevplays.emulator import ram
from jevplays.emulator.pyboy import Emulator
from jevplays.executor import maps
from jevplays.loop import Loop, LoopConfig
from jevplays.state.snapshot import snapshot


class Collector:
    """A broadcaster that keeps the status messages, so a test can read the run's narrative."""

    def __init__(self) -> None:
        self.statuses: list[str] = []

    async def publish(self, event: dict) -> None:
        if event["type"] == "status":
            self.statuses.append(event["message"])


class FirstChoiceBrain:
    """Jev's stand-in, with no API behind it: always the first choice, every noul at zero. It
    exists so the battles a walk runs into get fought (without a brain the battle menu idles,
    which is milestone 2's behaviour) and the overworld options can be watched all the way
    through. The first option is the milestone (`executor.options` puts it first), so the story
    still runs; what it answers is not the point, that the loop carries the answers out is."""

    def __init__(self) -> None:
        self.calls = 0

    async def ask(self, state: dict, questions: dict):
        self.calls += 1
        answers = {}
        for qid, q in questions.items():
            if q["type"] == "choice":
                options = list(q["criteria"])
                answers[qid] = {
                    "type": "choice",
                    "choice": options[0],
                    "probabilities": {o: (1.0 if o == options[0] else 0.0) for o in options},
                    "confidence": 0.9,
                }
            else:
                answers[qid] = {"type": "noul", "noul": 0.0}
        return {"model": "first-choice", "usage": {"input_tokens": 0}, "answers": answers}, 1


def test_without_a_brain_the_first_option_is_the_milestone_and_the_walk_starts(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("route1"))
        start = (emu.mem[ram.wXCoord], emu.mem[ram.wYCoord])
        loop = Loop(emu, Collector(), LoopConfig(paced=False))
        asyncio.run(loop.run(max_iterations=600))

        explores = [d for d in loop.decisions if d.kind == "explore"]
        assert explores and explores[0].action_value.kind == "milestone"
        assert explores[0].state_summary["milestone"] == "Deliver Oak's parcel and get the Pokédex"
        assert loop.milestone is not None and loop.milestone.id == "get_pokedex"
        # Either the walk crossed into Viridian, or a wild battle stopped it part-way up Route 1
        # -- with no brain the battle menu idles, as it has since milestone 2 -- but either way
        # the option was chosen, recorded, and walked towards.
        moved = (emu.mem[ram.wXCoord], emu.mem[ram.wYCoord]) != start
        assert emu.mem[ram.wCurMap] != maps.ROUTE_1 or moved
        assert loop.decisions


def test_the_pokedex_milestone_runs_from_route_1_to_the_mart_and_back_to_oak(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("route1"))
        collector = Collector()
        loop = Loop(emu, collector, LoopConfig(paced=False), brain=FirstChoiceBrain())
        asyncio.run(loop.run(max_iterations=1200))

        assert "got_oaks_parcel" in snapshot(emu).flags  # the Mart clerk handed it over
        assert "got_pokedex" in snapshot(emu).flags  # and Oak took it, in his lab
        assert "milestone done: get_pokedex" in collector.statuses
        first = [d for d in loop.decisions if d.kind == "explore"][0]
        assert first.action == "explore: work on the milestone: Deliver Oak's parcel and get the Pokédex"
        assert "to viridian_mart" in collector.statuses and "to oaks_lab" in collector.statuses
