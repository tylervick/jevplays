"""Spec 13: `replay` feeds a fixture log end to end through the websocket."""

import asyncio
import json

from starlette.testclient import TestClient

from jevplays.brain.decision import Decision, PromptAction
from jevplays.cli import main
from jevplays.dashboard.replay import replay
from jevplays.dashboard.server import Broadcaster, create_app
from jevplays.runlog import RunDir
from tests.test_server import FakeSocket


def logged_run(tmp_path, n: int) -> RunDir:
    run = RunDir.create(tmp_path, rom=None, flags={})
    for i in range(n):
        run.append(
            Decision(
                id=f"d{i}",
                ts=float(i),
                kind="prompt",
                state_summary={"prompt": f"q{i}"},
                questions={},
                answers={},
                action="answer YES",
                model="jev-1.13.0",
                action_value=PromptAction(yes=True),
            )
        )
    return run


def test_replay_publishes_each_logged_decision_in_order_with_status_around_it(tmp_path):
    run = logged_run(tmp_path, 3)
    slept: list[float] = []

    async def fake_sleep(s):
        slept.append(s)

    async def scenario():
        bc = Broadcaster()
        sock = FakeSocket()
        await bc.connect(sock)
        n = await replay(run, bc, delay=0.5, sleep=fake_sleep)
        return n, [json.loads(m) for m in sock.sent]

    n, events = asyncio.run(scenario())
    assert n == 3
    decisions = [e for e in events if e["type"] == "decision"]
    assert [d["decision"]["id"] for d in decisions] == ["d0", "d1", "d2"]
    assert decisions[0]["decision"]["state_summary"] == {"prompt": "q0"}
    assert events[0]["type"] == "status" and events[0]["message"].startswith("replaying")
    assert events[-1] == {"type": "status", "status": "stopped", "message": "replayed 3 decisions"}
    assert slept == [0.5, 0.5]


def test_replay_honours_the_limit(tmp_path):
    run = logged_run(tmp_path, 5)

    async def scenario():
        bc = Broadcaster()
        return await replay(run, bc, delay=0, limit=2)

    assert asyncio.run(scenario()) == 2


def test_replayed_events_reach_a_real_websocket_client(tmp_path):
    # `client.portal.call` does accept a coroutine function in the installed Starlette, but the
    # implementation publishes a "running" status before *every* decision (its message carries
    # i/n progress), not once before the batch; for n=2 that is five events (status, decision,
    # status, decision, status), not the four the brief's primary variant assumes. Rather than
    # assert an exact, fragile interleaving, use the brief's documented fallback: run the replay
    # to completion first, then confirm a late joiner is brought current from `Broadcaster.latest`.
    run = logged_run(tmp_path, 2)
    bc = Broadcaster()
    asyncio.run(replay(run, bc, delay=0))
    app = create_app(bc)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        seen = [json.loads(ws.receive_text()) for _ in range(2)]
    assert {e["type"] for e in seen} == {"status", "decision"}
    status = next(e for e in seen if e["type"] == "status")
    decision = next(e for e in seen if e["type"] == "decision")
    assert status == {"type": "status", "status": "stopped", "message": "replayed 2 decisions"}
    assert decision["decision"]["id"] == "d1"


def test_replay_command_rejects_a_directory_that_is_not_a_run(tmp_path, capsys):
    assert main(["replay", str(tmp_path)]) == 2
    assert "run.json" in capsys.readouterr().err
