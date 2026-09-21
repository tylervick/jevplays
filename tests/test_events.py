import base64
import json

from jevplays.dashboard.events import encode, frame_event, state_event, status_event
from jevplays.emulator import ram
from jevplays.state.events import EVENTS, TRACKED_FLAGS, flag_index, flags_set
from jevplays.state.snapshot import snapshot
from tests.support import FakeEmulator, FakeMemory


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


def test_decision_event_wraps_the_record():
    from jevplays.brain.decision import Decision
    from jevplays.dashboard.events import decision_event

    d = Decision(
        id="abc", ts=1.0, kind="battle", state_summary={}, questions={}, answers={}, action="use SCRATCH"
    )
    ev = decision_event(d)
    assert (
        ev["type"] == "decision"
        and ev["decision"]["action"] == "use SCRATCH"
        and "action_value" not in ev["decision"]
    )


def test_event_table_has_the_story_flags_at_the_measured_bits():
    assert len(EVENTS) == 507
    assert flag_index("got_starter") == 34 and flag_index("oak_got_parcel") == 56
    assert flag_index("got_pokedex") == 37 and flag_index("beat_brock") == 119


def test_flags_set_reads_only_tracked_flags():
    mem = FakeMemory()
    for name in ("got_starter", "battled_rival_in_oaks_lab"):
        n = flag_index(name)
        mem[ram.wEventFlags + n // 8] = mem[ram.wEventFlags + n // 8] | (1 << (n % 8))
    assert flags_set(mem) == frozenset({"got_starter", "battled_rival_in_oaks_lab"})
    assert set(TRACKED_FLAGS) >= flags_set(mem)
