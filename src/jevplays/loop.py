"""The orchestrator: snapshot, publish, advance, repeat.

Milestone 1 advances the game without deciding anything: dialog and battle text get an A,
transitions get a wait, and every decision point (overworld, menu, prompt, battle menu) idles.
Milestone 2 replaces the idle branches with a request to Jev; the publish side stays as is.

Pacing: the emulator runs as fast as it can, so the loop sleeps to keep emulated frames in step
with wall-clock time at 60 frames per second. That is what makes the dashboard watchable.
"""

import asyncio
from dataclasses import dataclass
from itertools import count
from time import monotonic

from jevplays.dashboard.events import frame_event, state_event
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


class Loop:
    def __init__(self, emu, broadcaster, config: LoopConfig | None = None) -> None:
        self.emu = emu
        self.broadcaster = broadcaster
        self.config = config or LoopConfig()

    def advance(self, state: GameState) -> int:
        """Move the game forward one step for the current mode. Returns emulated frames spent."""
        if state.mode in (Mode.DIALOG, Mode.BATTLE_WAIT):
            return self.emu.press("a", settle=30)
        if state.mode is Mode.TRANSITION:
            return self.emu.tick(30)
        return self.emu.tick(self.config.idle_frames)

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
            emulated += self.advance(state)
            if self.config.paced:
                due = started + emulated / FRAMES_PER_SECOND
                await asyncio.sleep(max(0.0, due - monotonic()))
            else:
                await asyncio.sleep(0)
