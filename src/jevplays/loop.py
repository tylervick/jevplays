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
import time
import uuid
from dataclasses import dataclass
from functools import partial
from itertools import count
from time import monotonic

from jevplays.brain.battle import battle_questions, battle_state, decide_battle
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
from jevplays.executor import navigate, shop
from jevplays.executor.battle import MacroError
from jevplays.executor.dialog import answer_prompt, cursor_label, skip_dialog
from jevplays.executor.goals import Goal
from jevplays.executor.maps import VIRIDIAN_MART, node_of
from jevplays.executor.navigate import Navigator, goto_far
from jevplays.executor.talk import talk_to
from jevplays.state.modes import Mode
from jevplays.state.snapshot import GameState, rows_of, snapshot

FRAMES_PER_SECOND = 60

NAV_STEP_FRAMES = 26
"""What one navigator step costs, near enough: a held direction plus its settle. The navigator
ticks the emulator itself, so this is only what the pacer is told; under-reporting makes the loop
sleep less, never stall."""
MACRO_FRAMES = 60
"""Same idea for a scripted macro, which spends far more than this talking and reading."""

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
    def __init__(self, emu, broadcaster, config: LoopConfig | None = None, brain=None) -> None:
        self.emu = emu
        self.broadcaster = broadcaster
        self.config = config or LoopConfig()
        self.brain = brain
        self.decisions: list[Decision] = []
        self.navigator = Navigator()
        self.goal: Goal | None = None
        self.goal_started_at: float = 0.0
        self.blocked_goals: set[str] = set()
        """Goals the navigator or a macro could not carry out. Never offered again this run."""
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
        await self.broadcaster.publish(decision_event(decision))

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
        decision = await self._decide("battle", sj, questions, decide_battle)
        if decision is None:
            return 0
        await self.broadcaster.publish(status_event("running", f"pressing: {decision.action}"))
        try:
            battle_macros.apply(self.emu, decision.action_value)
        except MacroError as error:
            return await self._retry_after_macro_error(decision, error, state)
        await self.broadcaster.publish(status_event("running", decision.action))
        return self.emu.tick(30)

    async def _retry_after_macro_error(self, decision: Decision, error: MacroError, state: GameState) -> int:
        """A macro can fail mid-way (e.g. a move fell out of the list between snapshot and
        press). Retry once: back out with B, and if we are still at the battle menu, try the
        same decision again. A second failure means the decision could not be carried out at
        all, so we fall through to `_after_second_failure` rather than silently pressing on."""
        await self.broadcaster.publish(status_event("running", f"macro failed: {error}; retrying once"))
        frames = self.emu.press("b", settle=20)
        retry_state = snapshot(self.emu)
        if retry_state.mode is Mode.BATTLE_MENU:
            try:
                battle_macros.apply(self.emu, decision.action_value)
            except MacroError:
                return await self._after_second_failure(decision, state)
        return frames

    async def _after_second_failure(self, decision: Decision, state: GameState) -> int:
        """The decision could not be carried out twice in a row. Try the safe default -- the
        first usable move -- once; if even that fails, back out and hold at this mode instead of
        asking the brain again about a screen it cannot act on."""
        moves = decision.state_summary["our_pokemon"]["moves"]
        first = next((m["name"] for m in moves if m["pp"] != "out"), moves[0]["name"])
        try:
            battle_macros.apply(self.emu, BattleAction(kind="move", move=first))
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
        if self.navigator.busy:
            return await self._walk(state)
        if self.goal is None:
            return await self._pick_goal(state)
        if self._arrived and state.map_id == self._goal_map:
            return await self._run_macro()
        return await self._plan(state)

    async def _pick_goal(self, state: GameState) -> int:
        options = [g for g in goal_table.available_goals(state) if g.id not in self.blocked_goals]
        if not options:
            return self.emu.tick(self.config.idle_frames)
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
        self.goal_started_at = monotonic()
        await self.broadcaster.publish(status_event("running", f"goal: {self.goal.id}"))
        return await self._plan(state)

    async def _plan(self, state: GameState) -> int:
        """Build the active goal's legs from where we are standing now. No legs means we are
        already there, so the macro runs this turn -- unless the map is not in the map graph at
        all, in which case there is no way to route anywhere and the goal is out of reach."""
        self._goal_map, self._arrived = state.map_id, False
        legs = self.goal.legs(state)
        if not legs:
            if node_of(state.map_id, *state.tile).startswith("map_"):
                return await self._block_goal("no route out of an unmapped map")
            self._arrived = True
            return await self._run_macro()
        self.navigator.plan(self.emu, state, legs)
        await self.broadcaster.publish(status_event("running", self.navigator.describe()))
        return self.emu.tick(self.config.idle_frames)

    async def _walk(self, state: GameState) -> int:
        result = self.navigator.step(self.emu, state)
        if result == "stuck":
            return await self._block_goal("the navigator gave up")
        if result == "leg_done":
            await self.broadcaster.publish(status_event("running", self.navigator.describe()))
        elif result == "done":
            # The macro waits for the next turn: a warp can land us mid-cutscene, and the turn
            # after this one re-reads the mode (and the goal's `done`) before pressing anything.
            self._arrived = True
            self._goal_map = self.emu.mem[ram.wCurMap]
            await self.broadcaster.publish(status_event("running", f"arrived: {self.goal.id}"))
        return NAV_STEP_FRAMES

    async def _finish_goal(self) -> int:
        finished = self.goal.id
        self._clear_goal()
        await self.broadcaster.publish(status_event("running", f"goal done: {finished}"))
        return self.emu.tick(self.config.idle_frames)

    async def _block_goal(self, why: str) -> int:
        blocked = self.goal.id
        self.blocked_goals.add(blocked)
        self._clear_goal()
        await self.broadcaster.publish(status_event("running", f"goal blocked: {blocked} ({why})"))
        return self.emu.tick(self.config.idle_frames)

    def _clear_goal(self) -> None:
        self.goal = None
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
        if not self._apply_macro(macro, snapshot(self.emu)):
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
            return self._wander()
        raise ValueError(f"unknown goal macro {macro!r}")

    def _choose_charmander(self) -> bool:
        """The ball on Oak's table is not a sprite, so this is a walk-face-A, not a `talk_to`.
        Every YES/NO along the way is Jev-free on purpose: the only one is the nickname box,
        and policy says never nickname."""
        if not goto_far(self.emu, 6, 4):
            return False
        self.emu.press("up", hold=4, settle=12)
        self.emu.press("a", settle=60)
        skip_dialog(self.emu, answer=lambda text: "nickname" not in text.lower())
        return True

    def _wander(self) -> bool:
        """One step in the grass, alternating up and down, until something jumps out."""
        direction = "up" if self._wander_up else "down"
        self._wander_up = not self._wander_up
        if navigate.step(self.emu, direction):
            return True
        return navigate.step(self.emu, "down" if direction == "up" else "up")

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
        return self._select_menu_item(decision.action_value.item, len(state.menu_items))

    def _select_menu_item(self, item: str, item_count: int) -> int:
        """Walk the cursor down to `item` and press A. Bounded by the number of items on screen
        so a label that never comes up under the cursor cannot spin the menu forever."""
        frames = 0
        for _ in range(item_count):
            label = cursor_label(rows_of(self.emu.tilemap()))
            if label is not None and label.startswith(item):
                break
            frames += self.emu.press("down", settle=16)
        return frames + self.emu.press("a", settle=30)

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
