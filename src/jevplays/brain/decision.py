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


@dataclass(frozen=True)
class GoalAction:
    goal_id: str

    def describe(self) -> str:
        return f"pursue {self.goal_id}"


@dataclass(frozen=True)
class PromptAction:
    yes: bool

    def describe(self) -> str:
        return "answer YES" if self.yes else "answer NO"


@dataclass(frozen=True)
class MenuAction:
    item: str | None
    """The menu label to select. None means close the menu without choosing anything."""

    def describe(self) -> str:
        return f"select {self.item}" if self.item is not None else "close the menu"


Action = BattleAction | GoalAction | PromptAction | MenuAction


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
    action_value: Action | None = field(default=None, compare=False)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("action_value")
        return d
