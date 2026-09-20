"""What the brain returns: the action to take and the full record of how it was chosen."""

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class BattleAction:
    kind: str  # move | run | switch | heal | catch
    move: str | None = None
    target: str | None = None

    def describe(self) -> str:
        return {
            "move": f"use {self.move}",
            "run": "run away",
            "switch": f"switch to {self.target}",
            "heal": "use a Potion",
            "catch": "throw a Poké Ball",
        }[self.kind]


@dataclass
class Decision:
    id: str
    ts: float
    kind: str
    state_summary: dict
    questions: dict[str, dict]
    answers: dict[str, dict]
    action: str
    fallback: bool = False
    fallback_reason: str = ""
    model: str = ""
    input_tokens: int = 0
    latency_ms: int = 0
    action_value: BattleAction | None = field(default=None, compare=False)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("action_value")
        return d
