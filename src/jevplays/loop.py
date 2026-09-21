"""The orchestrator: snapshot, publish, advance, repeat.

Milestone 1 advanced the game without deciding anything: dialog and battle text got an A,
transitions got a wait, and every decision point (overworld, menu, prompt, battle menu) idled.
Milestone 2 replaced the battle menu's idle branch with a request to Jev. Milestone 3 does the
same for the overworld: Jev picks a goal from `executor.goals`, the navigator walks its legs, a
scripted macro finishes it off, and the prompt and menu branches ask Jev how to answer. Jev
judges (which goal, yes or no, which item); code executes (routes, button presses, counters).

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
from jevplays.brain.decision import Action, BattleAction, Decision, GoalAction, MenuAction, PromptAction
from jevplays.brain.errors import BrainUnavailable
from jevplays.brain.goal import decide_goal, goal_questions, goal_state
from jevplays.brain.policy import NEVER_NICKNAME
from jevplays.brain.prompt import (
    decide_menu,
    decide_prompt,
    menu_questions,
    menu_state,
    prompt_questions,
    prompt_state,
)
from jevplays.dashboard.events import decision_event, frame_event, state_event, status_event
from jevplays.emulator import ram
from jevplays.executor import battle as battle_macros
from jevplays.executor import goals as goal_table
from jevplays.executor import navigate, shop, world
from jevplays.executor.battle import MacroError
from jevplays.executor.dialog import answer_prompt, cursor_label, skip_dialog
from jevplays.executor.goals import Goal
from jevplays.executor.maps import VIRIDIAN_MART, node_of
from jevplays.executor.navigate import Leg, Navigator, goto_far
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

GOAL_BUDGET_S = 180.0
"""How long one goal may hold the loop before Jev is asked again. Some goals never complete on
their own -- `train_nearby` is done only when something else interrupts it -- so without a budget
the first absorbing goal picked would be the last decision Jev ever made."""
GOAL_RETRIES = 3
"""How many times a goal may fail -- a stuck navigator, a macro that does not work -- before it
is dropped for the rest of the run. One failure is often a wandering NPC or a mistimed script."""
GRASS_CANDIDATES = 40
"""How many of the nearest grass cells `wander` runs a path search to. Bounded so the search
cannot grow with the map."""

MAX_POKEBALLS = 5
"""How many balls one `buy_pokeballs` trip buys at most, money permitting."""
POKEBALL_PRICE = 200


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
    overworld has the real goal table (`executor.goals`); this is the battle's free-text one."""
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
    ) -> None:
        self.emu = emu
        self.broadcaster = broadcaster
        self.config = config or LoopConfig()
        self.brain = brain
        self.run_dir = run_dir
        self._logged_before = run_dir.count() if run_dir is not None else 0
        self.decisions: list[Decision] = []
        self.navigator = Navigator()
        self.goal: Goal | None = None
        self.goal_started_at: float = 0.0
        self.clock = monotonic
        """Wall clock for the goal budget. A test swaps it for one it controls."""
        self._goal_failures: dict[str, int] = {}
        """How many times each goal has failed. At GOAL_RETRIES it is out for the rest of the run."""
        self._announced_dead_end = False
        """Whether the "all goals blocked" pause has already been published for this dead end."""
        self._goal_map: int | None = None
        """The map the active goal's legs were planned on (or arrived at). A different map with
        the navigator idle means the game moved us -- the starter cutscene walks the player into
        Oak's lab -- so the legs are planned again from where we actually are."""
        self._arrived = False
        """The legs are finished: the next overworld turn runs the goal's `after` macro."""
        self._wander_up = True
        self._backoff = min(1.0, self.config.backoff_max)
        self._hold: tuple[Mode, str] | None = None
        """Set after a macro fails twice and the safe default fails too: (mode, decision id) to
        wait out until the screen changes, so the loop stops asking the brain about a decision
        it cannot carry out."""

    @property
    def blocked_goals(self) -> set[str]:
        """The goals that have used up their retries and are no longer offered to Jev."""
        return {goal_id for goal_id, n in self._goal_failures.items() if n >= GOAL_RETRIES}

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
        sj = battle_state(state, goal=self.config.goal)
        questions = battle_questions(sj)
        decision = await self._decide("battle", sj, questions, partial(decide_battle, supported=ALL_ACTIONS))
        if decision is None:
            return 0
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

        The macros back out to the battle menu themselves before raising, so usually there is
        nothing to press here and the snapshot below is already `BATTLE_MENU`. When it is not --
        a screen the macro could not close, or one that opened after it gave up -- B is pressed
        up to `MACRO_BACKOUT_PRESSES` times, re-snapshotting each time, and if the battle menu
        still has not come back the retry is skipped: the next loop iteration reads the screen
        afresh."""
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
        """One goal at a time: finish it, walk it, pick one, re-plan it, or run its macro."""
        if self.goal is not None and self.goal.done(state):
            return await self._finish_goal()
        if self.goal is not None and self.clock() - self.goal_started_at > GOAL_BUDGET_S:
            return await self._goal_budget_spent()
        if self.navigator.busy:
            return await self._walk(state)
        if self.goal is None:
            return await self._pick_goal(state)
        if self._arrived and state.map_id == self._goal_map:
            return await self._run_macro()
        return await self._plan(state)

    async def _pick_goal(self, state: GameState) -> int:
        blocked = self.blocked_goals
        options = [g for g in goal_table.available_goals(state) if g.id not in blocked]
        if not options:
            if not self._announced_dead_end:
                self._announced_dead_end = True
                message = (
                    f"all goals blocked: {', '.join(sorted(blocked))}"
                    if blocked
                    else "no goal is available right now"
                )
                await self.broadcaster.publish(status_event("paused", message))
            return self.emu.tick(self.config.idle_frames)
        self._announced_dead_end = False
        sj = goal_state(state, options)
        questions = goal_questions(sj)
        ids = [g.id for g in options]
        decision = await self._decide(
            "goal",
            sj,
            questions,
            partial(decide_goal, available_ids=ids),
            offline=(GoalAction(goal_id=ids[0]), "no brain: the first available goal"),
        )
        if decision is None:
            return 0
        self.goal = goal_table.goal_by_id(decision.action_value.goal_id)
        self.goal_started_at = self.clock()
        await self.broadcaster.publish(status_event("running", f"goal: {self.goal.id}"))
        return await self._plan(state)

    async def _plan(self, state: GameState) -> int:
        """Build the active goal's legs from where we are standing now. No legs means we are
        already there, so the macro runs this turn -- unless the map is not in the map graph at
        all (a house, the Viridian Gym), in which case there is no route from here and the only
        move that helps is walking back out of the door we came in by."""
        self._goal_map, self._arrived = state.map_id, False
        legs = self.goal.legs(state)
        if not legs:
            if node_of(state.map_id, *state.tile).startswith("map_"):
                legs = [Leg(kind="warp", dest_map=ram.WARP_LAST_MAP, label="back outside")]
                self.navigator.plan(self.emu, state, legs)
                await self.broadcaster.publish(status_event("running", self.navigator.describe()))
                return self.emu.tick(self.config.idle_frames)
            self._arrived = True
            return await self._run_macro()
        self.navigator.plan(self.emu, state, legs)
        await self.broadcaster.publish(status_event("running", self.navigator.describe()))
        return self.emu.tick(self.config.idle_frames)

    async def _walk(self, state: GameState) -> int:
        result = self.navigator.step(self.emu, state)
        if result == "stuck":
            return await self._block_goal("the navigator gave up")
        if result == "lost":
            # The map changed under the plan (a blackout, a scripted teleport). The route is for
            # a map we are not on any more, but the goal itself is untouched, so no retry.
            self.navigator.clear()
            await self.broadcaster.publish(status_event("running", "re-planning after a map change"))
            fresh = snapshot(self.emu)
            if fresh.mode is not Mode.OVERWORLD:
                return NAV_STEP_FRAMES  # mid-teleport; the next overworld turn re-plans
            return await self._plan(fresh)
        if result == "leg_done":
            await self.broadcaster.publish(status_event("running", self.navigator.describe()))
        elif result == "done":
            # The macro waits for the next turn: a warp can land us mid-cutscene, and the turn
            # after this one re-reads the mode (and the goal's `done`) before pressing anything.
            self._arrived = True
            self._goal_map = self.emu.mem[ram.wCurMap]
            await self.broadcaster.publish(status_event("running", f"arrived: {self.goal.id}"))
        return NAV_STEP_FRAMES

    async def _goal_budget_spent(self) -> int:
        """The goal has had its turn. It is not a failure -- nothing went wrong and no retry is
        charged -- so it stays on offer; the next iteration simply asks Jev again, which is how
        a goal that never completes on its own gives the decision back."""
        spent = self.goal.id
        self._clear_goal()
        await self.broadcaster.publish(status_event("running", f"goal budget spent: {spent}"))
        return self.emu.tick(self.config.idle_frames)

    async def _finish_goal(self) -> int:
        finished = self.goal.id
        self._clear_goal()
        await self.broadcaster.publish(status_event("running", f"goal done: {finished}"))
        return self.emu.tick(self.config.idle_frames)

    async def _block_goal(self, why: str) -> int:
        """A goal that did not work. It gets GOAL_RETRIES tries before it is dropped, because one
        failure is usually an NPC in a doorway rather than a goal that cannot be done at all."""
        goal_id = self.goal.id
        failures = self._goal_failures.get(goal_id, 0) + 1
        self._goal_failures[goal_id] = failures
        self._clear_goal()
        if failures >= GOAL_RETRIES:
            message = f"goal blocked: {goal_id} ({why})"
        else:
            message = f"goal failed {failures}/{GOAL_RETRIES}: {goal_id} ({why})"
        await self.broadcaster.publish(status_event("running", message))
        return self.emu.tick(self.config.idle_frames)

    def _clear_goal(self) -> None:
        self.goal = None
        self.goal_started_at = 0.0
        self.navigator.clear()
        self._goal_map, self._arrived = None, False

    async def _run_macro(self) -> int:
        """Run the scripted tail of the goal -- talking, choosing, healing, buying, wandering.
        A macro that fails blocks the goal, the same as a navigator that gives up. One that
        works clears `_arrived`, so the next turn plans the goal's legs again: for `wander`
        that is another step in the grass, and for a goal whose next phase starts somewhere
        else (the parcel, once the clerk has handed it over) it is the route there."""
        macro = self.goal.after
        if macro is None:
            return await self._block_goal("arrived, but the goal has no macro to finish it")
        await self.broadcaster.publish(status_event("running", f"{self.goal.id}: {macro}"))
        try:
            worked = self._apply_macro(macro, snapshot(self.emu))
        except Exception as error:  # a macro is a script over a live game: never kill the run
            return await self._block_goal(f"{macro} raised {type(error).__name__}: {error}")
        if not worked:
            return await self._block_goal(f"{macro} did not work")
        self._arrived = False
        return MACRO_FRAMES

    def _apply_macro(self, macro: str, state: GameState) -> bool:
        emu = self.emu
        if macro == "talk_oak":
            if state.map_id == VIRIDIAN_MART:
                # `deliver_parcel` runs this macro twice: once at the Mart, where the clerk hands
                # the parcel over, and once in the lab, where Oak takes it. (5, 3) is Oak's tile;
                # in the Mart it is behind the counter, so the walk there fails outright.
                if "got_oaks_parcel" in state.flags:
                    # Walking in already fired the clerk's trigger. Pressing A at him now would
                    # only open BUY/SELL/QUIT, so leave the Mart alone: the next plan routes to
                    # the lab, because the goal's legs read the same flag.
                    return True
                return talk_to(emu, *shop.CLERK_TILE, shop.CLERK_FACE)
            return talk_to(emu, 5, 3, "up")
        if macro == "talk_old_man":
            return talk_to(emu, 18, 10, "up", answer=lambda text: True)
        if macro == "talk_brock":
            return talk_to(emu, 4, 2, "up")
        if macro == "heal":
            return shop.heal_at_nurse(emu)
        if macro == "buy_pokeballs":
            before = goal_table.balls(state)
            count = min(MAX_POKEBALLS, state.money // POKEBALL_PRICE)
            return shop.buy_pokeballs(emu, count) > before
        if macro == "choose_charmander":
            return self._choose_charmander()
        if macro == "wander":
            return self._wander(state)
        raise ValueError(f"unknown goal macro {macro!r}")

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
        return self.goal.description if self.goal is not None else self.config.goal

    async def _prompt_turn(self, state: GameState) -> int:
        sj = prompt_state(state, self._goal_description())
        text = sj.get("prompt") or ""
        if NEVER_NICKNAME and "nickname" in text.lower():
            # Settled by policy, so Jev is never asked: a nickname is not a judgment call.
            decision = local_decision("prompt", sj, PromptAction(yes=False), "policy: never nickname")
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

    async def run(self, max_iterations: int | None = None) -> None:
        started = monotonic()
        emulated = 0
        last_frame_at = float("-inf")
        last_state: GameState | None = None
        for i in count():
            if max_iterations is not None and i >= max_iterations:
                return
            state = snapshot(self.emu)
            if self._hold is not None and state.mode != self._hold[0]:
                self._hold = None
            if state != last_state:
                await self.broadcaster.publish(state_event(state))
                last_state = state
            now = monotonic()
            if now - last_frame_at >= 1 / self.config.fps:
                await self.broadcaster.publish(frame_event(self.emu.frame_jpeg()))
                last_frame_at = now
            emulated += await self.advance(state)
            if self.config.paced:
                due = started + emulated / FRAMES_PER_SECOND
                await asyncio.sleep(max(0.0, due - monotonic()))
            else:
                await asyncio.sleep(0)
