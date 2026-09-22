"""The orchestrator: snapshot, publish, advance, repeat.

Milestone 1 advanced the game without deciding anything: dialog and battle text got an A,
transitions got a wait, and every decision point (overworld, menu, prompt, battle menu) idled.
Milestone 2 replaced the battle menu's idle branch with a request to Jev. Milestone 3 did the
same for the overworld, and milestone 4b turned that into exploration: code generates the
options the map affords (`executor.options`), Jev picks one, the navigator walks its legs, and a
scripted macro finishes it off. `executor.goals`' milestones are the spine that keeps the run
moving, and the last one being done ends it. Jev judges (which option, yes or no, which item);
code executes (routes, button presses, counters, memory).

Pacing: the emulator runs as fast as it can, so the loop sleeps to keep emulated frames in step
with wall-clock time at 60 frames per second. That is what makes the dashboard watchable.
"""

import asyncio
import heapq
import time
import uuid
from dataclasses import dataclass, replace
from functools import partial
from itertools import count
from time import monotonic

from jevplays.brain.battle import ALL_ACTIONS, battle_questions, battle_state, bench_slots, decide_battle
from jevplays.brain.decision import Action, BattleAction, Decision, ExploreAction, MenuAction, PromptAction
from jevplays.brain.errors import BrainUnavailable
from jevplays.brain.explore import decide_explore, explore_questions, explore_state
from jevplays.brain.policy import settled_prompt
from jevplays.brain.prompt import (
    decide_menu,
    decide_prompt,
    menu_questions,
    menu_state,
    prompt_questions,
    prompt_state,
)
from jevplays.calibration import QUESTION as FAINT
from jevplays.calibration import Pending, observe, resolve_prediction
from jevplays.dashboard.events import decision_event, frame_event, state_event, status_event
from jevplays.emulator import ram
from jevplays.executor import battle as battle_macros
from jevplays.executor import goals as goal_table
from jevplays.executor import navigate, shop, world
from jevplays.executor.battle import MacroError
from jevplays.executor.dialog import answer_prompt, cursor_label, skip_dialog
from jevplays.executor.goals import Goal
from jevplays.executor.maps import VIRIDIAN_MART
from jevplays.executor.navigate import Navigator, goto_far
from jevplays.executor.options import Memory, Option, generate
from jevplays.executor.talk import talk_to
from jevplays.runlog import CHECKPOINT_EVERY, RunDir
from jevplays.state.modes import Mode
from jevplays.state.snapshot import GameState, rows_of, snapshot

FRAMES_PER_SECOND = 60

NAV_STEP_FRAMES = 56
"""What one navigator step costs, near enough: an 8-frame hold plus up to 48 frames waiting for
wWalkCounter to come back to zero. The navigator ticks the emulator itself, so this is only what
the pacer is told; under-reporting makes the loop sleep less, never stall."""
MACRO_FRAMES = 60
"""Same idea for a scripted macro, which spends far more than this talking and reading."""
MACRO_BACKOUT_PRESSES = 3
"""How many B presses `_retry_after_macro_error` will spend getting back to the battle menu
before giving up on the retry. The macros back out themselves, so this only covers a screen they
could not close."""

OPTION_BUDGET_S = 90.0
"""How long one option's macro may hold the loop before Jev is asked again. Some options never
complete on their own -- the grass is done only when a battle interrupts it -- so without a
budget the first absorbing option picked would be the last decision Jev ever made. An option
dropped this way is marked `tried`, which is what Jev is shown the next time it is offered.

The clock restarts when the legs finish, so this governs the macro phase only: a long walk is
bounded by the navigator's own stuck detector instead. Paced, Route 1 to the Viridian Mart takes
151 s, and a budget spanning the walk would cancel that option on the turn it arrived -- before
its macro ever ran, and writing a `tried` that says nothing true about the option."""
GRASS_CANDIDATES = 40
"""How many of the nearest grass cells `wander` runs a path search to. Bounded so the search
cannot grow with the map."""

REPEATABLE_COUNTERS = frozenset(("heal", "shop"))
"""NPC macros worth running again: healing and buying are not things one does once."""


@dataclass
class LoopConfig:
    fps: float = 15.0
    """Dashboard frames per second, not emulator frames."""
    idle_frames: int = 30
    """How long to let the game run when nothing needs pressing."""
    paced: bool = True
    """Sleep so emulated time matches wall time. Off in tests."""
    goal: str = "Win every battle and explore"
    """Told to Jev with every battle question so its judgments serve the same objective. The
    overworld has the milestones (`executor.goals`); this is the battle's free-text fallback,
    used until one is active."""
    backoff_max: float = 30.0
    """Cap, in seconds, on the doubling sleep after a BrainUnavailable."""


def local_decision(kind: str, sj: dict, action: Action, reason: str) -> Decision:
    """A decision code made on its own, because there is no brain to ask or because policy
    settles it without asking. Recorded and published exactly like one of Jev's, with no
    questions and no answers, so the log and the dashboard stay complete."""
    return Decision(
        id=uuid.uuid4().hex[:12],
        ts=time.time(),
        kind=kind,
        state_summary=sj,
        questions={},
        answers={},
        action=action.describe(),
        fallback=True,
        fallback_reason=reason,
        action_value=action,
    )


class Loop:
    def __init__(
        self,
        emu,
        broadcaster,
        config: LoopConfig | None = None,
        brain=None,
        run_dir: RunDir | None = None,
        memory: Memory | None = None,
    ) -> None:
        self.emu = emu
        self.broadcaster = broadcaster
        self.config = config or LoopConfig()
        self.brain = brain
        self.run_dir = run_dir
        self.memory = memory if memory is not None else Memory.empty()
        """What this run has already done, in the words Jev is shown (`executor.options`). A
        `--resume` hands the memory the run dir kept; a fresh run starts empty."""
        self._logged_before = run_dir.count() if run_dir is not None else 0
        self.decisions: list[Decision] = []
        self.navigator = Navigator()
        self.milestone: Goal | None = None
        """The milestone the run is working towards, refreshed every overworld turn. None once
        the last one is done, which is what finishes the run."""
        self.option: Option | None = None
        """The option Jev picked and the loop is carrying out, or None between decisions."""
        self.option_started_at: float = 0.0
        self.finished = False
        """The last milestone is done. `run()` returns on the turn this is set."""
        self.clock = monotonic
        """Wall clock for the option budget. A test swaps it for one it controls."""
        self._announced_no_options = False
        """Whether the "nothing to do here" pause has already been published for this map."""
        self._option_map: int | None = None
        """The map the option was generated on: where `tried` and `talked already` are keyed,
        even when the option's own legs have since carried us onto another map."""
        self._seen_map: int | None = None
        """The map the last overworld turn ran on, so a change is noticed exactly once."""
        self._arrived = False
        """The legs are finished: the next overworld turn runs the option's `after` macro."""
        self._wander_up = True
        self._backoff = min(1.0, self.config.backoff_max)
        self._hold: tuple[Mode, str] | None = None
        self.game_frames = 0
        """Frames the game has actually spent this session, for pacing and for the page."""
        self._pending: Pending | None = None
        if hasattr(emu, "capture_every"):
            # Only a run somebody is watching pays for capture: each captured frame costs an
            # extra emulated frame and a JPEG encode, and an unpaced run is being measured, not
            # watched. See _play_frames for what the captures are for.
            emu.capture_every = round(FRAMES_PER_SECOND / config.fps) if config.paced else 0
        """The faint prediction waiting for the game to answer it (calibration.py)."""
        """Set after a macro fails twice and the safe default fails too: (mode, decision id) to
        wait out until the screen changes, so the loop stops asking the brain about a decision
        it cannot carry out."""

    @property
    def decision_count(self) -> int:
        """Decisions on record for this run: what the log already held plus this session's."""
        return self._logged_before + len(self.decisions)

    async def advance(self, state: GameState) -> int:
        """Move the game forward one step for the current mode. Returns emulated frames spent."""
        if state.mode in (Mode.DIALOG, Mode.BATTLE_WAIT):
            return self.emu.press("a", settle=30)
        if state.mode is Mode.TRANSITION:
            return self.emu.tick(30)
        if state.mode is Mode.BATTLE_MENU and self.brain is not None:
            return await self._battle_turn(state)
        if state.mode is Mode.OVERWORLD:
            return await self._overworld_turn(state)
        if state.mode is Mode.PROMPT:
            return await self._prompt_turn(state)
        if state.mode is Mode.MENU:
            return await self._menu_turn(state)
        return self.emu.tick(self.config.idle_frames)

    # -- asking Jev ---------------------------------------------------------------------

    async def _decide(self, kind: str, sj: dict, questions: dict, decoder, offline=None) -> Decision | None:
        """One decision point, end to end: ask, decode, record, publish.

        `offline` is the `(action, reason)` code falls back to when there is no brain; without
        it a brainless loop makes no decision at all. Returns None when the brain is
        unavailable (the caller presses nothing and tries again next iteration)."""
        if self.brain is None:
            if offline is None:
                return None
            decision = local_decision(kind, sj, *offline)
        else:
            try:
                response, latency_ms = await self.brain.ask(sj, questions)
            except BrainUnavailable as error:
                await self._wait_for_api(error)
                return None
            self._backoff = min(1.0, self.config.backoff_max)
            decision = decoder(
                sj,
                questions,
                response,
                model=response.get("model", ""),
                input_tokens=response.get("usage", {}).get("input_tokens", 0),
                latency_ms=latency_ms,
            )
        await self._record(decision)
        return decision

    async def _record(self, decision: Decision) -> None:
        self.decisions.append(decision)
        if self.run_dir is not None:
            self.run_dir.append(decision)
            if decision.model:
                self.run_dir.set_model(decision.model)
        await self.broadcaster.publish(decision_event(decision))
        await self._maybe_checkpoint()

    async def _maybe_checkpoint(self) -> None:
        if self.run_dir is not None and self.decision_count % CHECKPOINT_EVERY == 0:
            await self.checkpoint()

    async def checkpoint(self):
        """Save the game where it stands, named by the decision count, so `--resume` can pick
        it up. None without a run dir."""
        if self.run_dir is None:
            return None
        path = self.run_dir.checkpoint(self.emu, self.decision_count)
        await self.broadcaster.publish(status_event("running", f"checkpoint {self.decision_count}"))
        return path

    async def _wait_for_api(self, error: BrainUnavailable) -> None:
        await self.broadcaster.publish(
            status_event(
                "waiting_for_api",
                f"TypeSafe unavailable: {error}; retrying in {self._backoff:.0f}s",
            )
        )
        await asyncio.sleep(self._backoff)
        self._backoff = min(self._backoff * 2, self.config.backoff_max)

    # -- battles ------------------------------------------------------------------------

    async def _battle_turn(self, state: GameState) -> int:
        if self._hold is not None and state.mode == self._hold[0]:
            return self.emu.tick(self.config.idle_frames)
        sj = battle_state(state, goal=goal_table.battle_goal(self.milestone, fallback=self.config.goal))
        questions = battle_questions(sj)
        decision = await self._decide("battle", sj, questions, partial(decide_battle, supported=ALL_ACTIONS))
        if decision is None:
            return 0
        # Before the macros, not after: the turn happens whether or not this decision's own
        # action survives (a failed switch falls back to a move), so the prediction is still
        # about a turn that was played and still deserves to be scored.
        self._note_prediction(decision, state)
        try:
            decision.action_value = self._resolve_switch(decision.action_value, state)
        except MacroError as error:
            return await self._retry_after_macro_error(decision, error, state)
        await self.broadcaster.publish(status_event("running", f"pressing: {decision.action}"))
        try:
            battle_macros.apply(self.emu, decision.action_value, active_slot=state.active_slot or 0)
        except MacroError as error:
            return await self._retry_after_macro_error(decision, error, state)
        await self.broadcaster.publish(status_event("running", decision.action))
        return self.emu.tick(30)

    def _note_prediction(self, decision: Decision, state: GameState) -> None:
        """Remember the faint prediction this decision carried, so the next decision point can
        score it against the party. Nothing reads it to decide anything; see calibration.py."""
        answer = decision.answers.get(FAINT)
        if answer is None or self.run_dir is None:
            return
        self._pending = Pending(decision.id, state.active_slot or 0, answer["noul"])

    async def _watch_prediction(self, state: GameState) -> None:
        """Catch a faint while it is still on screen. The blackout that follows heals the party,
        so by the next decision point there is nothing left to read (#36)."""
        if self._pending is None:
            return
        latched = observe(self._pending, state)
        if latched is not self._pending and latched.seen_faint:
            await self.broadcaster.publish(status_event("running", "our Pokémon fainted"))
        self._pending = latched

    def _resolve_prediction(self, state: GameState, *, final: bool = False) -> None:
        """Write the pending prediction's outcome once the game has answered it. `final` is the
        run ending: there is no next battle menu to wait for, so the question is answered now
        rather than left unscored (#51)."""
        if self._pending is None or self.run_dir is None:
            return
        outcome = resolve_prediction(self._pending, state, ts=time.time(), final=final)
        if outcome is None:
            return
        self.run_dir.append_outcome(outcome)
        self._pending = None

    def _resolve_switch(self, action: BattleAction, state: GameState) -> BattleAction:
        """A "switch" decision names a bench label, not a party index -- sj never carries one
        (see `bench_slots`' docstring), so this is where the label becomes the slot `apply` needs.
        Every other kind passes through untouched. A label `bench_slots(state)` does not
        recognize -- the bench Pokémon fainted or was swapped between the snapshot and this
        decision -- raises MacroError, so the caller treats it exactly like any other macro
        failure: retried once (against the original, still-unresolved action, which fails
        `apply`'s own "switch requires a slot" check), then the safe default."""
        if action.kind != "switch":
            return action
        for label, idx in bench_slots(state):
            if label == action.target:
                return replace(action, slot=idx)
        raise MacroError(f"switch target {action.target!r} is not on the bench")

    async def _retry_after_macro_error(self, decision: Decision, error: MacroError, state: GameState) -> int:
        """A macro can fail mid-way (e.g. a move fell out of the list between snapshot and
        press). Retry once: get back to the battle menu, then try the same decision again. A
        second failure means the decision could not be carried out at all, so we fall through to
        `_after_second_failure` rather than silently pressing on.

        The macros back out to the battle menu themselves before raising, so the first B here is
        usually a settling press on a menu that ignores it (B does nothing at the top-level battle
        menu). When the macro could not close its screen, or one opened after it gave up, B is
        pressed up to `MACRO_BACKOUT_PRESSES` times, re-snapshotting each time, and if the battle
        menu still has not come back the retry is skipped: the next loop iteration reads the
        screen afresh."""
        await self.broadcaster.publish(status_event("running", f"macro failed: {error}; retrying once"))
        frames = 0
        for _ in range(MACRO_BACKOUT_PRESSES):
            frames += self.emu.press("b", settle=20)
            if snapshot(self.emu).mode is not Mode.BATTLE_MENU:
                continue
            try:
                battle_macros.apply(self.emu, decision.action_value, active_slot=state.active_slot or 0)
            except MacroError:
                return await self._after_second_failure(decision, state)
            break
        return frames

    async def _after_second_failure(self, decision: Decision, state: GameState) -> int:
        """The decision could not be carried out twice in a row. Try the safe default -- the
        first usable move -- once; if even that fails, back out and hold at this mode instead of
        asking the brain again about a screen it cannot act on."""
        moves = decision.state_summary["our_pokemon"]["moves"]
        first = next((m["name"] for m in moves if m["pp"] != "out"), moves[0]["name"])
        try:
            battle_macros.apply(
                self.emu, BattleAction(kind="move", move=first), active_slot=state.active_slot or 0
            )
        except MacroError:
            frames = self.emu.press("b", settle=20)
            self._hold = (state.mode, decision.id)
            await self.broadcaster.publish(
                status_event("paused", "macro failed; waiting for the screen to change")
            )
            return frames
        await self.broadcaster.publish(
            status_event("running", "macro failed twice; used the first move instead")
        )
        return self.emu.tick(30)

    # -- the overworld ------------------------------------------------------------------

    async def _overworld_turn(self, state: GameState) -> int:
        """One option at a time: walk it, finish it, drop it, or ask Jev for the next one.

        The milestone is refreshed first, because it is what ends the run and what the option
        list is generated against. Then, in order: the navigator walks a plan that is still
        running; an option whose budget is gone is dropped and marked `tried`; an option that
        has arrived runs its `after` macro; and with no option at all, code generates what this
        map affords and Jev picks one.

        The budget is checked before the macro rather than after it (the brief's order) because
        `wander` keeps the option "arrived" turn after turn on purpose: checked the other way
        round, a grass option would never give the decision back.
        """
        if self._note_map(state.map_id):
            self._save_memory()
        ended = await self._refresh_milestone(state)
        if ended is not None:
            return ended
        if self.navigator.busy:
            return await self._walk(state)
        if self.option is not None:
            if self.clock() - self.option_started_at > OPTION_BUDGET_S:
                return await self._option_budget_spent()
            if self._arrived:
                return await self._run_macro(state)
            # The plan ended without arriving (a leg gave up quietly). Nothing is charged
            # against the option; the next turn generates the list again from where we stand.
            self._clear_option()
        return await self._choose_option(state)

    def _note_map(self, map_id: int) -> bool:
        """Remember the map we are standing on, once per arrival. True when that was new to this
        turn, so the caller knows the memory is worth writing out."""
        if map_id == self._seen_map:
            return False
        self._seen_map = map_id
        known = map_id in self.memory.visited_maps
        self.memory.note_map(map_id)
        return not known

    async def _refresh_milestone(self, state: GameState) -> int | None:
        """The milestone for this turn. Returns the frames to spend when the run is over, and
        None when there is still a milestone to work towards."""
        previous = self.milestone
        self.milestone = goal_table.active_milestone(state)
        if previous is not None and (self.milestone is None or self.milestone.id != previous.id):
            await self.broadcaster.publish(status_event("running", f"milestone done: {previous.id}"))
        if self.milestone is None:
            if not self.finished:
                self.finished = True
                # The last turn of the run still deserves its answer: nothing after this reaches
                # a battle menu, so waiting for one would drop it (#51).
                self._resolve_prediction(state, final=True)
                await self.broadcaster.publish(status_event("finished", "Boulder Badge"))
            return self.emu.tick(self.config.idle_frames)
        return None

    async def _choose_option(self, state: GameState) -> int:
        """Generate what this map affords, ask Jev which one to do, and start it."""
        options = generate(self.emu, state, self.memory, self.milestone)
        if not options:
            if not self._announced_no_options:
                self._announced_no_options = True
                await self.broadcaster.publish(status_event("paused", "nothing to do from here"))
            return self.emu.tick(self.config.idle_frames)
        self._announced_no_options = False
        sj = explore_state(state, options, self.milestone)
        questions = explore_questions(sj)
        offline = self._offline_option(options)
        decision = await self._decide(
            "explore",
            sj,
            questions,
            partial(decide_explore, options=options),
            offline=(
                ExploreAction(option_id=offline.id, kind=offline.kind, text=offline.text),
                f"no brain: {offline.text}",
            ),
        )
        if decision is None:
            return 0
        chosen = next(
            (o for o in options if o.id == decision.action_value.option_id),
            options[0],
        )
        return await self._start_option(chosen, state)

    @staticmethod
    def _offline_option(options: list[Option]) -> Option:
        """What a brainless run does: the first option this map has not been tried on, with the
        milestone first when it is offered, so an offline run still walks the story."""
        fresh = [o for o in options if o.memory != "tried"] or options
        return next((o for o in fresh if o.kind == "milestone"), fresh[0])

    async def _start_option(self, option: Option, state: GameState) -> int:
        """Take the option on: plan its legs, or count it arrived when it has none (the grass
        is `wander` from where we stand, so there is nowhere to walk to first)."""
        self.option = option
        self.option_started_at = self.clock()
        self._option_map = state.map_id
        self._arrived = not option.legs
        await self.broadcaster.publish(status_event("running", f"option: {option.text}"))
        if option.legs:
            self.navigator.plan(self.emu, state, list(option.legs))
            await self.broadcaster.publish(status_event("running", self.navigator.describe()))
        return self.emu.tick(self.config.idle_frames)

    async def _walk(self, state: GameState) -> int:
        result = self.navigator.step(self.emu, state)
        if result == "stuck":
            return await self._option_tried("the navigator gave up")
        if result == "lost":
            # The map changed under the plan (a blackout, a scripted teleport). The route is for
            # a map we are not on any more, and so is the option list it came from: drop both and
            # let the next turn generate fresh options from wherever we actually are.
            self._clear_option()
            await self.broadcaster.publish(status_event("running", "re-planning after a map change"))
            return NAV_STEP_FRAMES
        if result == "leg_done":
            await self.broadcaster.publish(status_event("running", self.navigator.describe()))
        elif result == "done":
            # The macro waits for the next turn: a warp can land us mid-cutscene, and the turn
            # after this one re-reads the mode before pressing anything. The budget starts here,
            # not where the legs did: see OPTION_BUDGET_S.
            self._arrived = True
            self.option_started_at = self.clock()
            await self.broadcaster.publish(status_event("running", f"arrived: {self.option.text}"))
        return NAV_STEP_FRAMES

    async def _option_budget_spent(self) -> int:
        """The option has had its turn. It is marked `tried` -- nothing came of it in the time it
        was given -- and Jev is asked again, which is how an option that never completes on its
        own (the grass) gives the decision back."""
        return await self._option_tried("its budget ran out", why_in_message=False)

    async def _option_tried(self, why: str, *, why_in_message: bool = True) -> int:
        """Mark the option `tried` for this map and let go of it. There is no retry counter: the
        memory word is the record, and Jev sees it in the option list next time.

        Only an option that changed nothing is marked (spec section 3). An option whose legs
        carried the run onto another map before whatever went wrong changed something: marking
        it against the map it was generated on would tell Jev that leaving Pallet Town, or
        working on the milestone from there, led nowhere -- when what it actually did was arrive
        somewhere and then fail there. The failure is still published either way."""
        option = self.option
        if self.emu.mem[ram.wCurMap] == self._option_map:
            self.memory.note_tried(self._option_map, option.id)
            self._save_memory()
        self._clear_option()
        message = f"tried: {option.text}" + (f" ({why})" if why_in_message else f"; {why}")
        await self.broadcaster.publish(status_event("running", message))
        return self.emu.tick(self.config.idle_frames)

    def _clear_option(self) -> None:
        self.option = None
        self.option_started_at = 0.0
        self.navigator.clear()
        self._option_map, self._arrived = None, False

    def _save_memory(self) -> None:
        if self.run_dir is not None:
            self.run_dir.save_memory(self.memory.to_dict())

    async def _run_macro(self, state: GameState) -> int:
        """Run the scripted tail of the option -- talking, healing, buying, wandering. A macro
        that fails marks the option `tried`, the same as a navigator that gives up. One that
        works finishes the option, except `wander`: the grass is one step per turn, so it keeps
        the option until a battle interrupts it or its budget runs out."""
        option = self.option
        macro = option.after
        if macro is None:
            if self.emu.mem[ram.wCurMap] == self._option_map:
                # Arriving is the whole of an exit or a door -- but we are standing on the map
                # this option started from, so it carried us nowhere and had no macro to make up
                # for it. Remember that, or it comes back `(new)` and can be chosen forever (#53).
                return await self._option_tried("it went nowhere")
            # An exit or a door: arriving is the whole of it.
            await self.broadcaster.publish(status_event("running", f"done: {option.text}"))
            self._clear_option()
            return self.emu.tick(self.config.idle_frames)
        await self.broadcaster.publish(status_event("running", f"{option.id}: {macro}"))
        try:
            worked = self._apply_macro(macro, snapshot(self.emu))
        except Exception as error:  # a macro is a script over a live game: never kill the run
            return await self._option_tried(f"{macro} raised {type(error).__name__}: {error}")
        if not worked:
            return await self._option_tried(f"{macro} did not work")
        if option.kind == "npc" and macro not in REPEATABLE_COUNTERS:
            # A nurse and a shop clerk are worth going back to; "talked already" would read as a
            # reason not to. Only an NPC with something to say once is remembered as talked to.
            self.memory.note_talked(self._option_map, int(option.id.split("_", 1)[1]))
            self._save_memory()
        if macro == "wander":
            return MACRO_FRAMES  # still in the grass; the option runs again next turn
        await self.broadcaster.publish(status_event("running", f"done: {option.text}"))
        self._clear_option()
        return MACRO_FRAMES

    def _apply_macro(self, macro: str, state: GameState) -> bool:
        """Carry out one option's `after` macro. `talk_<slot>` is the generated NPC one, which
        reads the option itself for the tile to talk from and the way to face; the rest are
        scripted counters and cutscenes that know where they are going."""
        emu = self.emu
        if macro == "talk_oak":
            if state.map_id == VIRIDIAN_MART:
                # The `get_pokedex` milestone runs this macro twice: once at the Mart, where the
                # clerk hands the parcel over, and once in the lab, where Oak takes it. (5, 3) is
                # Oak's tile; in the Mart it is behind the counter, so the walk fails outright.
                if "got_oaks_parcel" in state.flags:
                    # Walking in already fired the clerk's trigger. Pressing A at him now would
                    # only open BUY/SELL/QUIT, so leave the Mart alone: the next plan routes to
                    # the lab, because the milestone's legs read the same flag.
                    return True
                return talk_to(emu, *shop.CLERK_TILE, shop.CLERK_FACE)
            return talk_to(emu, 5, 3, "up")
        if macro == "talk_brock":
            return talk_to(emu, 4, 2, "up")
        if macro == "heal":
            return shop.heal_at_nurse(emu)
        if macro == "shop":
            # Top the bag up with whatever the shelf has of what it wants (balls, then Potions).
            # A full bag is not a failure -- there was nothing to do -- but wanting something and
            # coming away with nothing is, so Jev sees "tried" on a shelf that cannot help.
            wanted = shop.shopping_list(state)
            if not wanted:
                return True
            return any(shop.restock(emu, state).values())
        if macro == "choose_charmander":
            return self._choose_charmander()
        if macro == "wander":
            return self._wander(state)
        if macro.startswith("talk_") and macro[len("talk_") :].isdigit():
            # An NPC option: the walk leg has already put us on the tile the option was planned
            # from, and `talk_to` faces the sprite itself once its own walk is done, so there is
            # nothing to do here but hand it the tile and the facing the option carries.
            return talk_to(emu, *self.option.target, self.option.face)
        raise ValueError(f"unknown option macro {macro!r}")

    def _choose_charmander(self) -> bool:
        """The ball on Oak's table is not a sprite, so this is a walk-face-A, not a `talk_to`.

        Both YES/NO boxes on the way are answered in code, not by Jev. "So! You want CHARMANDER?"
        is answered YES because a NO puts the ball back and leaves the goal exactly where it
        started -- Jev already chose to come here, and re-asking it at the confirmation box only
        gives it a way to deadlock its own goal. The nickname box is answered NO by the same
        policy the PROMPT branch applies (`skip_dialog` is handed the one rule it needs)."""
        if not goto_far(self.emu, 6, 4):
            return False
        self.emu.press("up", hold=4, settle=12)
        self.emu.press("a", settle=60)
        skip_dialog(self.emu, answer=lambda text: "nickname" not in text.lower())
        return True

    def _wander(self, state: GameState) -> bool:
        """One step towards, or inside, the tall grass -- which is the only place a wild battle
        can start. Walking on the road forever is how the first version of this stalled."""
        grid = world.build_grid(self.emu)
        grass = grid.grass()
        if not grass:
            return False  # nothing to train in here; the honest answer is to give up on the goal
        here = (self.emu.mem[ram.wXCoord], self.emu.mem[ram.wYCoord])
        if here in grass:
            moved = self._step_inside_grass(grid, here, grass)
        else:
            moved = self._step_towards_grass(grid, here, grass, world.blocked_by_sprites(state.sprites))
        if moved:
            return True
        # Nothing moved. If the screen has left the overworld, a wild battle started on the way
        # in -- which is exactly what wandering is for -- so that is not a failure to charge
        # against the goal's retries; the loop's battle branch takes it from here.
        return snapshot(self.emu).mode is not Mode.OVERWORLD

    def _step_towards_grass(self, grid, here, grass, blocked=frozenset()) -> bool:
        """One step of the shortest path to the nearest reachable grass cell, so the walk shows
        on the dashboard a tile at a time like every other move the loop makes."""
        nearest = heapq.nsmallest(
            GRASS_CANDIDATES, grass, key=lambda c: abs(c[0] - here[0]) + abs(c[1] - here[1])
        )
        best = None
        for cell in nearest:
            straight = abs(cell[0] - here[0]) + abs(cell[1] - here[1])
            if best is not None and straight >= len(best):
                break  # every remaining candidate is further off than the path we already have
            path = world.astar(grid, here, cell, frozenset(blocked))
            if path and (best is None or len(path) < len(best)):
                best = path
                if len(best) == straight:
                    break  # an unobstructed path; nothing closer can exist
        if not best:
            return False
        return navigate.step(self.emu, world.direction_to(here, best[0]))

    def _step_inside_grass(self, grid, here, grass) -> bool:
        """Standing in the grass already: step to another grass cell, alternating up and down so
        the walk stays in the patch instead of drifting out of it."""
        first = "up" if self._wander_up else "down"
        self._wander_up = not self._wander_up
        order = [first, "down" if first == "up" else "up", "left", "right"]
        neighbours = [
            (d, (here[0] + world.DIRECTIONS[d][0], here[1] + world.DIRECTIONS[d][1])) for d in order
        ]
        for direction, cell in neighbours:
            if cell in grass and navigate.step(self.emu, direction):
                return True
        for direction, cell in neighbours:
            if grid.walkable(*cell) and navigate.step(self.emu, direction):
                return True
        return False

    # -- prompts and menus --------------------------------------------------------------

    def _goal_description(self) -> str:
        return self.milestone.description if self.milestone is not None else self.config.goal

    async def _prompt_turn(self, state: GameState) -> int:
        sj = prompt_state(state, self._goal_description())
        text = sj.get("prompt") or ""
        settled = settled_prompt(text)
        if settled is not None:
            # Settled by policy, so Jev is never asked: a nickname is not a judgment call, and
            # neither is the way out of the move-learning ring (#55).
            yes, why = settled
            decision = local_decision("prompt", sj, PromptAction(yes=yes), f"policy: {why}")
            await self._record(decision)
        else:
            decision = await self._decide(
                "prompt",
                sj,
                prompt_questions(sj),
                decide_prompt,
                offline=(PromptAction(yes=True), "no brain: answering YES"),
            )
            if decision is None:
                return 0
        await self.broadcaster.publish(status_event("running", decision.action))
        answer_prompt(self.emu, decision.action_value.yes)
        return self.emu.tick(30)

    async def _menu_turn(self, state: GameState) -> int:
        """The scripted macros own the menus they open (the Mart's, the nurse's), so this is the
        safety net for a menu the loop finds itself in front of: pick an item or close it."""
        if not state.menu_items:
            return self.emu.press("b", settle=30)
        sj = menu_state(state, self._goal_description())
        decision = await self._decide(
            "menu",
            sj,
            menu_questions(sj),
            decide_menu,
            offline=(MenuAction(item=None), "no brain: closing the menu"),
        )
        if decision is None:
            return 0
        await self.broadcaster.publish(status_event("running", decision.action))
        if decision.action_value.item is None:
            return self.emu.press("b", settle=30)
        return await self._select_menu_item(decision.action_value.item, sj)

    async def _select_menu_item(self, item: str, sj: dict) -> int:
        """Walk the cursor down to `item` and press A. Bounded by the number of items on screen
        so a label that never comes up under the cursor cannot spin the menu forever -- and when
        it never does come up, back out with B rather than press A on whatever is highlighted:
        selecting the wrong thing in a shop or a PC costs money or a Pokémon."""
        frames = 0
        for _ in range(len(sj["menu_items"])):
            label = cursor_label(rows_of(self.emu.tilemap()))
            if label is not None and label.startswith(item):
                return frames + self.emu.press("a", settle=30)
            frames += self.emu.press("down", settle=16)
        reason = f"menu: {item} not reached under the cursor"
        await self._record(local_decision("menu", sj, MenuAction(item=None), reason))
        await self.broadcaster.publish(status_event("running", f"{reason}; closing it instead"))
        return frames + self.emu.press("b", settle=30)

    # -- the loop itself ----------------------------------------------------------------

    async def _play_frames(self, frames: list[bytes], *, until: float) -> None:
        """Play captured frames out across the rest of this step's wall-clock window.

        The game is emulated in batches -- a walking step is `NAV_STEP_FRAMES` frames ticked in
        one go -- and a paced run then sleeps out the remainder of the step. Publishing one frame
        per batch is what made the page lurch (#31): motion arrived in ~1 fps jumps with a
        half-second of stillness after each. The batch's own frames are already captured, so they
        are spread across the sleep instead, and the page plays smoothly one step behind.
        """
        if not frames:
            return
        for i, jpeg in enumerate(frames):
            await self.broadcaster.publish(frame_event(jpeg))
            remaining = len(frames) - i - 1
            if remaining:
                await asyncio.sleep(max(0.0, (until - monotonic()) / remaining))

    def _take_frames(self) -> list[bytes]:
        take = getattr(self.emu, "take_frames", None)
        return take() if take is not None else []

    def _frame_count(self) -> int | None:
        counter = getattr(self.emu, "frame_count", None)
        return counter() if counter is not None else None

    async def run(self, max_iterations: int | None = None) -> None:
        """Play until `max_iterations` turns have passed or the last milestone is done (`finished`)."""
        started = monotonic()
        emulated = 0
        # What `advance` returns is an estimate -- `_walk` reports NAV_STEP_FRAMES whatever the
        # navigator spent -- so pacing by it drifts: the loop sleeps out time the game never
        # spent, and a paced run crawls. The emulator's own counter is the clock when it has one
        # (a fake in a test may not), and the returned counts stay the fallback.
        first_count = self._frame_count()
        last_frame_at = float("-inf")
        last_state: GameState | None = None
        for i in count():
            if max_iterations is not None and i >= max_iterations:
                return
            state = snapshot(self.emu)
            if self._hold is not None and state.mode != self._hold[0]:
                self._hold = None
            await self._watch_prediction(state)
            self._resolve_prediction(state)
            if state != last_state:
                await self.broadcaster.publish(state_event(state))
                last_state = state
            now = monotonic()
            if not self.config.paced and now - last_frame_at >= 1 / self.config.fps:
                # Nothing is captured when unpaced, so the screen is grabbed here as before.
                await self.broadcaster.publish(frame_event(self.emu.frame_jpeg()))
                last_frame_at = now
            spent = await self.advance(state)
            if self.finished:
                return
            counted = self._frame_count()
            if counted is not None and first_count is not None:
                self.game_frames = counted - first_count
                emulated = self.game_frames
            else:
                emulated += spent
                self.game_frames = emulated
            captured = self._take_frames()
            if self.config.paced:
                due = started + emulated / FRAMES_PER_SECOND
                await self._play_frames(captured, until=due)
                await asyncio.sleep(max(0.0, due - monotonic()))
            else:
                # `captured` is empty unpaced (nothing is capturing); draining it above is what
                # keeps a stale backlog from reaching the page if anything ever does capture.
                await asyncio.sleep(0)
