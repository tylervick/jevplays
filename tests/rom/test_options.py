"""What `generate` offers on Viridian City after the Pokédex, and the old man's option carried
through the real loop.

`viridian_oldman.state` is Viridian City just after the Pokédex, the old man (picture 72,
`executor.options.sprite_noun`) still standing where he always does. Talking to him shows only
his own "private property" text -- checked against pret/pokered's ViridianCity script, his own
on-touch handler sets no flag and never moves him, so nothing about the talk itself ever clears
him off the map. What does is the run moving on: once he reads "talked already" the second test
lets the milestone carry it off Viridian City, at which point there is no picture-72 sprite to
find because we are no longer on his map.
"""

import asyncio

from jevplays.emulator.pyboy import Emulator
from jevplays.executor import maps
from jevplays.executor.goals import active_milestone
from jevplays.executor.options import Memory, generate
from jevplays.loop import Loop, LoopConfig
from jevplays.state.snapshot import snapshot

OLD_MAN_PICTURE = 72


class Quiet:
    async def publish(self, event: dict) -> None:
        pass


def test_generate_on_the_old_mans_map_offers_exits_doors_him_and_the_milestone(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("viridian_oldman"))
        state = snapshot(emu)
        options = generate(emu, state, Memory.empty(), active_milestone(state))
        by_id = {o.id: o for o in options}
        assert {"exit_north", "door_41", "door_42", "milestone"} <= set(by_id)
        assert by_id["exit_north"].text == "go north to Route 2"
        old_man = next(
            (o for o in options if o.kind == "npc" and o.text.startswith("talk to an old man")), None
        )
        assert old_man is not None


class TalkThenMoveOnBrain:
    """`explore`: `option_id` while its own label still reads "new"; once it reads "talked
    already" (or anything else), the milestone instead (the first offered option if even that is
    not on the list). Every other choice question gets the first criterion, and every noul --
    `needs_heal` and every battle noul alike -- is 0, so a wild battle met along the way is fought
    with the first move and nothing more judged about it.

    Forcing `option_id` forever, `ThrowBrain`-style, would never let the run move: see the module
    docstring for why talking to him never changes anything about the map on its own."""

    def __init__(self, option_id: str) -> None:
        self.option_id = option_id

    async def ask(self, state: dict, questions: dict):
        answers = {}
        for qid, q in questions.items():
            if qid == "explore":
                criteria = q["criteria"]
                label = criteria.get(self.option_id, "")
                if self.option_id in criteria and label.endswith("(new)"):
                    choice = self.option_id
                elif "milestone" in criteria:
                    choice = "milestone"
                else:
                    choice = next(iter(criteria))
                answers[qid] = {
                    "type": "choice",
                    "choice": choice,
                    "probabilities": {o: (1.0 if o == choice else 0.0) for o in criteria},
                    "confidence": 1.0,
                }
            elif q["type"] == "choice":
                first = next(iter(q["criteria"]))
                answers[qid] = {
                    "type": "choice",
                    "choice": first,
                    "probabilities": {o: (1.0 if o == first else 0.0) for o in q["criteria"]},
                    "confidence": 1.0,
                }
            else:
                answers[qid] = {"type": "noul", "noul": 0.0}
        return {"model": "stand-in", "usage": {"input_tokens": 0}, "answers": answers}, 1


def test_the_old_mans_option_is_remembered_and_the_run_moves_off_his_map(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("viridian_oldman"))
        state = snapshot(emu)
        milestone = active_milestone(state)
        options = generate(emu, state, Memory.empty(), milestone)
        old_man = next(o for o in options if o.kind == "npc" and o.text.startswith("talk to an old man"))
        slot = int(old_man.id.split("_", 1)[1])

        memory = Memory.empty()
        loop = Loop(
            emu,
            Quiet(),
            LoopConfig(paced=False, fps=0.001),
            brain=TalkThenMoveOnBrain(old_man.id),
            memory=memory,
        )
        asyncio.run(loop.run(max_iterations=400))

        final = snapshot(emu)
        # He never moves (his script is decorative); what the run proves is that it talked and moved on.
        assert final.map_id != maps.VIRIDIAN_CITY
        assert (maps.VIRIDIAN_CITY, slot) in memory.talked
