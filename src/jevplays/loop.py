"""The orchestrator: snapshot, publish, advance, repeat.

Milestone 1 advanced the game without deciding anything: dialog and battle text got an A,
transitions got a wait, and every decision point (overworld, menu, prompt, battle menu) idled.
Milestone 2 replaces the battle menu's idle branch with a request to Jev; the other decision
points still idle until milestone 3.

Pacing: the emulator runs as fast as it can, so the loop sleeps to keep emulated frames in step
with wall-clock time at 60 frames per second. That is what makes the dashboard watchable.
"""

import asyncio
from dataclasses import dataclass
from itertools import count
from time import monotonic

from jevplays.brain.battle import battle_questions, battle_state, decide_battle
from jevplays.brain.decision import Decision
from jevplays.brain.errors import BrainUnavailable
from jevplays.dashboard.events import decision_event, frame_event, state_event, status_event
from jevplays.executor import battle as battle_macros
from jevplays.executor.battle import MacroError
from jevplays.state.modes import Mode
from jevplays.state.snapshot import GameState, snapshot

FRAMES_PER_SECOND = 60


@dataclass
class LoopConfig:
    fps: float = 15.0
    """Dashboard frames per second, not emulator frames."""
    idle_frames: int = 30
    """How long to let the game run when nothing needs pressing."""
    paced: bool = True
    """Sleep so emulated time matches wall time. Off in tests."""
    goal: str = "Win every battle and explore"
    """Told to Jev with every battle question so its judgments serve the same objective."""
    backoff_max: float = 30.0
    """Cap, in seconds, on the doubling sleep after a BrainUnavailable."""


class Loop:
    def __init__(self, emu, broadcaster, config: LoopConfig | None = None, brain=None) -> None:
        self.emu = emu
        self.broadcaster = broadcaster
        self.config = config or LoopConfig()
        self.brain = brain
        self.decisions: list[Decision] = []
        self._backoff = min(1.0, self.config.backoff_max)

    async def advance(self, state: GameState) -> int:
        """Move the game forward one step for the current mode. Returns emulated frames spent."""
        if state.mode in (Mode.DIALOG, Mode.BATTLE_WAIT):
            return self.emu.press("a", settle=30)
        if state.mode is Mode.TRANSITION:
            return self.emu.tick(30)
        if state.mode is Mode.BATTLE_MENU and self.brain is not None:
            return await self._battle_turn(state)
        return self.emu.tick(self.config.idle_frames)

    async def _battle_turn(self, state: GameState) -> int:
        sj = battle_state(state, goal=self.config.goal)
        questions = battle_questions(sj)
        try:
            response, latency_ms = await self.brain.ask(sj, questions)
        except BrainUnavailable as error:
            await self.broadcaster.publish(
                status_event(
                    "waiting_for_api",
                    f"TypeSafe unavailable: {error}; retrying in {self._backoff:.0f}s",
                )
            )
            await asyncio.sleep(self._backoff)
            self._backoff = min(self._backoff * 2, self.config.backoff_max)
            return 0
        self._backoff = min(1.0, self.config.backoff_max)
        decision = decide_battle(
            sj,
            questions,
            response,
            model=response.get("model", ""),
            input_tokens=response.get("usage", {}).get("input_tokens", 0),
            latency_ms=latency_ms,
        )
        self.decisions.append(decision)
        await self.broadcaster.publish(decision_event(decision))
        await self.broadcaster.publish(status_event("running", decision.action))
        try:
            battle_macros.apply(self.emu, decision.action_value)
        except MacroError as error:
            return await self._retry_after_macro_error(decision, error)
        return self.emu.tick(30)

    async def _retry_after_macro_error(self, decision: Decision, error: MacroError) -> int:
        """A macro can fail mid-way (e.g. a move fell out of the list between snapshot and
        press). Retry once: back out with B, and if we are still at the battle menu, try the
        same decision again. A second failure means the decision could not be carried out at
        all, so the record is corrected and re-published rather than silently pressing on."""
        await self.broadcaster.publish(status_event("running", f"macro failed: {error}; retrying once"))
        frames = self.emu.press("b", settle=20)
        retry_state = snapshot(self.emu)
        if retry_state.mode is Mode.BATTLE_MENU:
            try:
                battle_macros.apply(self.emu, decision.action_value)
            except MacroError as second_error:
                decision.fallback = True
                decision.fallback_reason = f"macro failed twice: {second_error}"
                await self.broadcaster.publish(decision_event(decision))
                await self.broadcaster.publish(status_event("running", "macro failed; pressed B"))
        return frames

    async def run(self, max_iterations: int | None = None) -> None:
        started = monotonic()
        emulated = 0
        last_frame_at = float("-inf")
        last_state: GameState | None = None
        for i in count():
            if max_iterations is not None and i >= max_iterations:
                return
            state = snapshot(self.emu)
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
