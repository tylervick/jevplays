"""When a branch ends (spec: "When a branch stops"). Counted in game frames throughout, never
wall-clock time (#61)."""

CAP_FACTOR = 3
"""A branch may spend this many times the frames the logged run took to the same milestone."""
MIN_CAP_FRAMES = 3_600
"""One game minute: the smallest cap, so a decision just before its milestone is not capped
before any alternative could get there."""
STALL_FRAMES = 20_000
"""Game frames with no new decision before a branch is called stalled: the #67 hang."""


def cap_for(reference_frames: int) -> int:
    return max(CAP_FACTOR * reference_frames, MIN_CAP_FRAMES)


class Stopper:
    """The `stop` a branch's Loop is given. Returns "done", "capped" or "stalled" to end the run,
    None to go on, and counts blackouts along the way."""

    def __init__(self, target: str, cap_frames: int, stall_frames: int = STALL_FRAMES) -> None:
        self.target = target
        self.cap_frames = cap_frames
        self.stall_frames = stall_frames
        self.blackouts = 0
        self._down = False
        self._seen = -1
        self._last_decision_at = 0

    def __call__(self, loop, state) -> str | None:
        if loop.finished or (loop.milestone is not None and loop.milestone.id != self.target):
            return "done"
        down = bool(state.party) and all(m.hp == 0 for m in state.party)
        if down and not self._down:
            self.blackouts += 1
        self._down = down
        if len(loop.decisions) != self._seen:
            self._seen = len(loop.decisions)
            self._last_decision_at = loop.game_frames
        if loop.game_frames >= self.cap_frames:
            return "capped"
        if loop.game_frames - self._last_decision_at >= self.stall_frames:
            return "stalled"
        return None
