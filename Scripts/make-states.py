#!/usr/bin/env -S uv run
"""Write the save states tests/rom/ load, one per Mode the harness detects.

    uv run Scripts/make-states.py [--out states/] [--only NAME]

Needs JEVPLAYS_ROM. Each state is a snapshot of the game a few frames into a known screen:

    overworld.state       Red's bedroom, player free to move
    dialog.state          Oak's "Hello there!" with the ▼ arrow waiting for A
    menu.state            the START menu open in the bedroom
    prompt.state          the SAVE yes/no question ("Would you like to SAVE the game?")
    route1.state          Route 1, overworld, Charmander in party
    battle_trainer.state  the rival battle, FIGHT menu open
    battle_wait.state     mid-turn text after choosing SCRATCH
    battle_wild.state     a wild battle, FIGHT menu open

Milestone 3 adds the overworld's decision points, walked with the real loop and a stand-in brain:

    pallet.state          Pallet Town, outside Red's house, before the starter
    prompt_starter.state  the "Do you want CHARMANDER?" YES/NO box in Oak's lab
    viridian.state        Viridian City, arrived from Route 1
    viridian_center.state inside the Viridian Pokémon Center, before the nurse
    mart_parcel.state     inside the Viridian Mart, the clerk's parcel just handed over
    dex.state             Oak's lab, the Pokédex just received
    mart_dex.state        inside the Viridian Mart after the Pokédex, before buying
    viridian_oldman.state Viridian City after the Pokédex, the old man still asleep

Milestone 4a adds the two battles the item and switch macros need, both from `battle_wild.state`:

    battle_items.state    the same wild battle with 5 POKé BALLs and 3 POTIONs in the bag
    battle_two.state      a later wild battle, with the caught Pokémon on the bench

Save states are gitignored: they are copies of the game's memory.
"""

import argparse
import asyncio
import os
import sys
from collections.abc import Callable
from pathlib import Path

from jevplays.emulator import ram
from jevplays.emulator.intro import ARROW_COL, ARROW_ROW, cursor_label, walk_intro
from jevplays.emulator.pyboy import Emulator
from jevplays.emulator.text import ARROW
from jevplays.executor import maps
from jevplays.executor.autoplay import finish_battle, play_one_turn, wait_for_fight_menu
from jevplays.executor.battle import throw_ball
from jevplays.executor.dialog import skip_dialog
from jevplays.executor.goals import OLD_MAN_PICTURE
from jevplays.executor.navigate import Leg, Navigator, goto, step
from jevplays.loop import Loop, LoopConfig
from jevplays.state.modes import Mode, yes_no_at
from jevplays.state.snapshot import GameState, snapshot

MILESTONE_1_STATES = ("overworld", "dialog", "menu", "prompt")
BATTLE_STATES = ("route1", "battle_trainer", "battle_wait", "battle_wild")
ITEM_STATES = ("battle_items", "battle_two")
STORY_STATES = (
    "pallet",
    "prompt_starter",
    "viridian",
    "viridian_center",
    "mart_parcel",
    "dex",
    "mart_dex",
    "viridian_oldman",
)
GROUPS: dict[str, tuple[str, ...]] = {
    "milestone1": MILESTONE_1_STATES,
    "battle": BATTLE_STATES,
    "items": ITEM_STATES,
    "story": STORY_STATES,
}

STORY_ITERATIONS = 6000
"""A ceiling on the scripted walk from Route 1 to the old man, not a target: the walk stops the
moment the last story state is written."""


def wait_for(emu: Emulator, condition, *, frames: int = 600, every: int = 5) -> None:
    for _ in range(0, frames, every):
        if condition(emu.rows()):
            return
        emu.tick(every)
    raise SystemExit("timed out waiting for the screen to settle")


def starter_answer(text: str) -> bool:
    return "nickname" not in text.lower()


def make_battle_states(rom: Path, out: Path) -> None:
    with Emulator(rom) as emu:
        emu.load(out / "overworld.state")
        assert goto(emu, 7, 1), "bedroom stairs"
        emu.tick(60)
        assert goto(emu, 3, 7), "front door mat"
        step(emu, "down", settle=30)
        emu.tick(60)
        assert emu.mem[ram.wCurMap] == 0, "Pallet Town"
        assert goto(emu, 10, 1), "route 1 edge"
        emu.tick(90)
        skip_dialog(
            emu,
            patience=150,
            stop_when=lambda rows: (
                emu.mem[ram.wCurMap] == 40 and not any("".join(r).strip("· ") for r in rows[13:17])
            ),
        )
        emu.tick(120)
        skip_dialog(emu, patience=60)
        assert emu.mem[ram.wCurMap] == 40, "Oak's lab"
        assert goto(emu, 6, 4), "below Charmander's ball"
        emu.press("up", hold=4, settle=12)
        emu.press("a", settle=60)
        skip_dialog(
            emu,
            answer=starter_answer,
            patience=40,
            stop_when=lambda rows: emu.mem[ram.wPartyCount] == 1,
        )
        skip_dialog(emu, answer=starter_answer, patience=40)
        assert emu.mem[ram.wPartyCount] == 1, "took Charmander"
        goto(emu, 4, 11)  # the rival interrupts before the door is reached
        skip_dialog(emu, patience=60, stop_when=lambda rows: emu.mem[ram.wIsInBattle] != 0)
        wait_for_fight_menu(emu)
        assert emu.mem[ram.wIsInBattle] == 2, "trainer battle"
        emu.save(out / "battle_trainer.state")
        play_one_turn(emu)
        emu.tick(30)
        emu.save(out / "battle_wait.state")
        finish_battle(emu)
        skip_dialog(emu, answer=lambda text: False, patience=60)
        assert goto(emu, 4, 11), "lab door"
        step(emu, "down", settle=30)
        emu.tick(30)
        step(emu, "left")
        step(emu, "left")
        assert goto(emu, 10, 2) and goto(emu, 10, 1), "pallet north"
        step(emu, "up", settle=30)
        step(emu, "up", settle=30)
        emu.tick(60)
        assert emu.mem[ram.wCurMap] == 12, "Route 1"
        emu.save(out / "route1.state")
        pattern = ["up", "up", "left", "up", "right", "up", "left", "up", "right", "up"]
        for i in range(300):
            if emu.mem[ram.wIsInBattle] == 1:
                break
            direction = pattern[i % len(pattern)]
            if not step(emu, direction, settle=12):
                step(emu, "right" if direction == "left" else "left", settle=12)
        else:
            raise SystemExit("no wild encounter on Route 1")
        wait_for_fight_menu(emu)
        emu.save(out / "battle_wild.state")


BAG_ITEMS = (4, 5, 20, 3, ram.BAG_END)
"""What `write_bag` puts in the bag: item 4 (POKé BALL) x5, item 20 (POTION) x3, terminator."""

CATCH_PRESSES = 40
"""A ceiling on the A presses between throwing the ball and the nickname box."""


def write_bag(emu: Emulator) -> None:
    """Give the player five Poké Balls and three Potions.

    The same doctoring `goal_hurt` does to HP, for the same reason: no walk the scripts take
    stops at a battle holding both, and the Viridian Mart sells both, so this is a bag the game
    could really be carrying.
    """
    emu.mem[ram.wNumBagItems] = 2
    for offset, value in enumerate(BAG_ITEMS):
        emu.mem[ram.wBagItems + offset] = value


def heal_party_slot(emu: Emulator, slot: int) -> None:
    """Put a party slot back to its own max HP, the way a Pokémon Center would."""
    base = ram.wPartyMons + slot * ram.PARTY_MON_SIZE
    max_hp = ram.read_u16(emu.mem, base + ram.MON_MAX_HP)
    emu.mem[base + ram.MON_HP] = max_hp >> 8
    emu.mem[base + ram.MON_HP + 1] = max_hp & 0xFF


def make_item_states(rom: Path, out: Path) -> None:
    """`battle_items.state` and `battle_two.state`, both descended from `battle_wild.state`.

    `battle_items` is that battle with a bag written into RAM. `battle_two` is played forward
    from it: the enemy is put on 1 HP so the ball certainly catches, the nickname box is
    answered NO (the policy never nicknames), and the overworld walk stumbles into a second
    wild battle -- this time with the caught Pokémon on the bench, which is what makes a
    switch decision possible at all. The catch leaves that Pokémon on the 1 HP it was caught
    at, so it is healed back to full first: a Center would have done the same, and a bench
    Pokémon one hit from fainting is no switch candidate to ask about.
    """
    with Emulator(rom) as emu:
        emu.load(out / "battle_wild.state")
        write_bag(emu)
        emu.tick(1)
        emu.save(out / "battle_items.state")

    with Emulator(rom) as emu:
        emu.load(out / "battle_items.state")
        emu.mem[ram.wEnemyMonHP] = 0
        emu.mem[ram.wEnemyMonHP + 1] = 1
        throw_ball(emu)
        for _ in range(CATCH_PRESSES):
            if yes_no_at(emu.rows()) is not None:
                break
            emu.press("a", settle=40)
        else:
            raise SystemExit("the ball never reached the nickname box")
        emu.press("down", settle=16)
        emu.press("a", settle=40)
        for _ in range(40):
            if snapshot(emu).mode is Mode.OVERWORLD:
                break
            emu.press("a", settle=40)
        else:
            raise SystemExit("the overworld never came back after the catch")
        assert emu.mem[ram.wPartyCount] == 2, "the caught Pokémon joined the party"
        heal_party_slot(emu, 1)
        for i in range(300):
            if emu.mem[ram.wIsInBattle] == 1:
                break
            step(emu, "up" if i % 2 == 0 else "down", settle=12)
        else:
            raise SystemExit("no second wild encounter")
        wait_for_fight_menu(emu)
        assert emu.mem[ram.wIsInBattle] == 1, "a wild battle with two Pokémon in the party"
        emu.save(out / "battle_two.state")


def settle_overworld(emu: Emulator, frames: int = 900) -> None:
    """Let a warp or a cutscene finish, so a state is saved at a screen and not mid-transition."""
    for _ in range(0, frames, 10):
        if snapshot(emu).mode is Mode.OVERWORLD:
            return
        emu.tick(10)
    raise SystemExit("the overworld never came back")


def make_story_intro_states(rom: Path, out: Path) -> None:
    """`pallet.state` and `prompt_starter.state`, from milestone 1's bedroom.

    The same walk `make_battle_states` takes -- downstairs, out of the front door, north out of
    Pallet Town into Oak's cutscene, and up to Charmander's ball -- stopped at the two screens
    milestone 3 asks Jev about: standing outside the house with no Pokémon, and the YES/NO box
    that offers the starter.
    """
    with Emulator(rom) as emu:
        emu.load(out / "overworld.state")
        assert goto(emu, 7, 1), "bedroom stairs"
        emu.tick(60)
        assert goto(emu, 3, 7), "front door mat"
        step(emu, "down", settle=30)
        emu.tick(60)
        assert emu.mem[ram.wCurMap] == maps.PALLET_TOWN, "Pallet Town"
        settle_overworld(emu)
        emu.save(out / "pallet.state")
        print(f"wrote {out / 'pallet'}.state")
        assert goto(emu, 10, 1), "route 1 edge"
        emu.tick(90)
        skip_dialog(
            emu,
            patience=150,
            stop_when=lambda rows: (
                emu.mem[ram.wCurMap] == maps.OAKS_LAB and not any("".join(r).strip("· ") for r in rows[13:17])
            ),
        )
        emu.tick(120)
        skip_dialog(emu, patience=60)
        assert emu.mem[ram.wCurMap] == maps.OAKS_LAB, "Oak's lab"
        assert goto(emu, 6, 4), "below Charmander's ball"
        emu.press("up", hold=4, settle=12)
        emu.press("a", settle=60)
        assert skip_dialog(emu, patience=80, stop_when=lambda rows: yes_no_at(rows) is not None), (
            "the CHARMANDER YES/NO box"
        )
        emu.save(out / "prompt_starter.state")
        print(f"wrote {out / 'prompt_starter'}.state")


class FirstChoiceBrain:
    """Jev's stand-in for a scripted walk: always the first choice, every noul at zero. No API key
    and no network, so building states never spends a request; what Jev really answers at these
    screens is recorded separately by `Scripts/record-fixtures.py`. It exists so the battles the
    walk runs into get fought and the goals run to completion."""

    async def ask(self, state: dict, questions: dict) -> tuple[dict, int]:
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


class Quiet:
    """The loop publishes to a broadcaster; a script has no dashboard to publish to."""

    async def publish(self, event: dict) -> None:
        return None


class StoryFinished(Exception):
    """Raised out of the loop once every story state has been written."""


def _in(map_id: int, *flags: str) -> Callable[[GameState], bool]:
    """A milestone: the overworld, on `map_id`, with `flags` already set."""

    def holds(state: GameState) -> bool:
        return (
            state.mode is Mode.OVERWORLD and state.map_id == map_id and all(f in state.flags for f in flags)
        )

    return holds


def _viridian_old_man(state: GameState) -> bool:
    return _in(maps.VIRIDIAN_CITY, "got_pokedex")(state) and any(
        sprite.picture == OLD_MAN_PICTURE for sprite in state.sprites
    )


MILESTONES: dict[str, Callable[[GameState], bool]] = {
    "viridian": _in(maps.VIRIDIAN_CITY),
    "mart_parcel": _in(maps.VIRIDIAN_MART, "got_oaks_parcel"),
    "dex": _in(maps.OAKS_LAB, "got_pokedex"),
    "mart_dex": _in(maps.VIRIDIAN_MART, "got_pokedex"),
    "viridian_oldman": _viridian_old_man,
}
"""Each state the scripted walk writes, and the first moment it may be written. The loop chooses
its own goals, so these are conditions rather than a fixed sequence of button presses."""


class RecordingLoop(Loop):
    """The real loop with a save hook. Before every turn it writes the milestone states whose
    condition now holds, and gives up the walk as soon as none are left."""

    def __init__(self, emu: Emulator, out: Path) -> None:
        super().__init__(emu, Quiet(), LoopConfig(paced=False, fps=0.001), brain=FirstChoiceBrain())
        self.out = out
        self.pending = dict(MILESTONES)

    async def advance(self, state: GameState) -> int:
        for name in [n for n, holds in self.pending.items() if holds(state)]:
            del self.pending[name]
            self.emu.save(self.out / f"{name}.state")
            print(f"wrote {self.out / name}.state")
        if not self.pending:
            raise StoryFinished
        return await super().advance(state)


def make_walked_story_states(rom: Path, out: Path) -> None:
    """Route 1 to the old man, played by the loop itself: Jev's stand-in picks the goals, the
    navigator walks them, and the milestones fall out along the way."""
    with Emulator(rom) as emu:
        emu.load(out / "route1.state")
        loop = RecordingLoop(emu, out)
        try:
            asyncio.run(loop.run(max_iterations=STORY_ITERATIONS))
        except StoryFinished:
            return
        raise SystemExit(f"the walk never reached: {', '.join(sorted(loop.pending))}")


def make_center_state(rom: Path, out: Path) -> None:
    """`viridian_center.state`: a detour into the Pokémon Center from `viridian.state`. The loop
    only goes there when the lead is hurt, which the parcel walk is not reliably hurt enough to
    be, so this is a plain one-leg warp plan instead."""
    with Emulator(rom) as emu:
        emu.load(out / "viridian.state")
        nav = Navigator()
        leg = Leg(kind="warp", dest_map=maps.VIRIDIAN_POKECENTER, label="to viridian_pokecenter")
        nav.plan(emu, snapshot(emu), [leg])
        for _ in range(200):
            state = snapshot(emu)
            if state.map_id == maps.VIRIDIAN_POKECENTER:
                break
            result = nav.step(emu, state)
            if result == "stuck":
                raise SystemExit("the navigator gave up on the Viridian Pokémon Center")
            if result == "interrupted":
                skip_dialog(emu, patience=60)
        else:
            raise SystemExit("never reached the Viridian Pokémon Center")
        settle_overworld(emu)
        emu.save(out / "viridian_center.state")
        print(f"wrote {out / 'viridian_center'}.state")


def make_story_states(rom: Path, out: Path) -> None:
    make_story_intro_states(rom, out)
    make_walked_story_states(rom, out)
    make_center_state(rom, out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=Path(os.environ.get("JEVPLAYS_STATES", "states")))
    parser.add_argument(
        "--only",
        choices=sorted(GROUPS) + list(MILESTONE_1_STATES + BATTLE_STATES + ITEM_STATES + STORY_STATES),
        default=None,
        help="one group, or one state (which runs the group that state belongs to)",
    )
    args = parser.parse_args(argv)
    rom = os.environ.get("JEVPLAYS_ROM")
    if not rom:
        print("JEVPLAYS_ROM is not set", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)

    def selected(group: str) -> bool:
        return args.only is None or args.only == group or args.only in GROUPS[group]

    run_milestone_1 = selected("milestone1")
    run_battles = selected("battle")
    run_items = selected("items")
    run_story = selected("story")

    if run_milestone_1:
        with Emulator(Path(rom)) as emu:
            emu.tick(120)
            for _ in range(400):
                if cursor_label(emu.rows()) == "NEW GAME":
                    break
                emu.press("start", hold=4, settle=6)
            emu.press("a", settle=60)
            wait_for(emu, lambda rows: rows[ARROW_ROW][ARROW_COL] == ARROW)
            emu.save(args.out / "dialog.state")

        with Emulator(Path(rom)) as emu:
            walk_intro(emu)
            emu.tick(30)
            emu.save(args.out / "overworld.state")

            emu.press("start", settle=30)
            wait_for(emu, lambda rows: cursor_label(rows) == "POKéMON")
            emu.save(args.out / "menu.state")

            for _ in range(3):
                emu.press("down")
            emu.press("a", settle=60)
            # cursor_label would read "YES·IME…" here because the box overlaps the trainer card,
            # so use the same YES/NO detector snapshot() relies on.
            wait_for(emu, lambda rows: yes_no_at(rows) is not None)
            emu.save(args.out / "prompt.state")

        for name in MILESTONE_1_STATES:
            print(f"wrote {args.out / name}.state")

    if run_battles:
        make_battle_states(Path(rom), args.out)
        for name in BATTLE_STATES:
            print(f"wrote {args.out / name}.state")

    if run_items:
        make_item_states(Path(rom), args.out)
        for name in ITEM_STATES:
            print(f"wrote {args.out / name}.state")

    if run_story:
        make_story_states(Path(rom), args.out)

    return 0


if __name__ == "__main__":
    sys.exit(main())
