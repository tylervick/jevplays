import base64
import json

from jevplays.dashboard.events import encode, frame_event, state_event, status_event
from jevplays.state.snapshot import snapshot
from tests.support import FakeEmulator


def test_frame_event_carries_base64_jpeg():
    ev = frame_event(b"\xff\xd8abc")
    assert ev["type"] == "frame"
    assert base64.b64decode(ev["jpeg"]) == b"\xff\xd8abc"


def test_state_event_wraps_the_state_dict():
    ev = state_event(snapshot(FakeEmulator()))
    assert ev["type"] == "state"
    assert ev["state"]["mode"] == "overworld"


def test_status_event_and_encode_round_trip():
    ev = status_event("running", "walking the intro")
    assert json.loads(encode(ev)) == {"type": "status", "status": "running", "message": "walking the intro"}
