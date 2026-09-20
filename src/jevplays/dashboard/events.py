"""The messages the loop pushes to the page. Each is a JSON object with a `type`."""

import base64
import json

from jevplays.brain.decision import Decision
from jevplays.state.snapshot import GameState


def frame_event(jpeg: bytes) -> dict:
    return {"type": "frame", "jpeg": base64.b64encode(jpeg).decode("ascii")}


def state_event(state: GameState) -> dict:
    return {"type": "state", "state": state.to_dict()}


def status_event(status: str, message: str = "") -> dict:
    """status is one of running, waiting_for_api, paused, stopped."""
    return {"type": "status", "status": status, "message": message}


def decision_event(decision: Decision) -> dict:
    return {"type": "decision", "decision": decision.to_dict()}


def encode(event: dict) -> str:
    return json.dumps(event, separators=(",", ":"))
