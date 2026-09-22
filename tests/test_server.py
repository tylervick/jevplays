import asyncio
import json

from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from jevplays.dashboard.events import status_event
from jevplays.dashboard.server import Broadcaster, create_app


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(text)


def test_broadcaster_sends_to_every_client_and_remembers_the_latest_per_type():
    async def scenario():
        bc = Broadcaster()
        a, b = FakeSocket(), FakeSocket()
        await bc.connect(a)
        await bc.publish(status_event("running"))
        await bc.publish(status_event("paused"))
        await bc.connect(b)  # late joiner gets the latest status on connect
        return bc, a, b

    bc, a, b = asyncio.run(scenario())
    assert [json.loads(m)["status"] for m in a.sent] == ["running", "paused"]
    assert [json.loads(m)["status"] for m in b.sent] == ["paused"]
    assert bc.latest["status"]["status"] == "paused"


def test_broadcaster_drops_a_client_whose_send_fails():
    class Broken(FakeSocket):
        async def send_text(self, text: str) -> None:
            raise RuntimeError("gone")

    async def scenario():
        bc = Broadcaster()
        await bc.connect(Broken())
        await bc.publish(status_event("running"))
        return bc

    bc = asyncio.run(scenario())
    assert bc.clients == set()


def test_page_and_static_files_are_served():
    client = TestClient(create_app(Broadcaster()))
    page = client.get("/")
    assert page.status_code == 200
    assert "Jev plays" in page.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200


def test_websocket_receives_the_latest_events_on_connect():
    bc = Broadcaster()
    bc.latest["status"] = status_event("running", "hello")
    client = TestClient(create_app(bc))
    with client.websocket_connect("/ws") as ws:
        first = json.loads(ws.receive_text())
    assert first == {"type": "status", "status": "running", "message": "hello"}


def test_the_page_serves_the_same_html_for_the_stream_layout_and_the_css_knows_it():
    client = TestClient(create_app(Broadcaster()))
    assert client.get("/?layout=stream").status_code == 200
    css = client.get("/static/styles.css").text
    js = client.get("/static/app.js").text
    assert 'body[data-layout="stream"]' in css
    assert "dataset.layout" in js and "1920px" in css


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_idle_time_counts_from_the_last_viewer_leaving_and_is_zero_while_anyone_watches():
    """A demo left running for people to drop in on should not play to an empty room: the run
    pauses once nobody has watched for a while, so the broadcaster keeps the time since the last
    tab closed. It counts from startup until the first viewer arrives."""

    async def scenario():
        clock = Clock()
        bc = Broadcaster(clock=clock)
        clock.now += 30
        before_anyone = bc.idle_for()
        a = FakeSocket()
        await bc.connect(a)
        clock.now += 500
        while_watched = bc.idle_for()
        bc.disconnect(a)
        clock.now += 12
        return before_anyone, while_watched, bc.idle_for(), bc.viewers

    before_anyone, while_watched, after_leaving, viewers = asyncio.run(scenario())
    assert before_anyone == 30
    assert while_watched == 0
    assert after_leaving == 12
    assert viewers == 0


def test_wait_for_viewer_returns_when_a_tab_connects_and_at_once_when_one_already_has():
    async def scenario():
        bc = Broadcaster()
        waiting = asyncio.create_task(bc.wait_for_viewer())
        await asyncio.sleep(0)
        assert not waiting.done()
        a = FakeSocket()
        await bc.connect(a)
        await asyncio.wait_for(waiting, 1)
        await asyncio.wait_for(bc.wait_for_viewer(), 1)  # already watched: no wait
        bc.disconnect(a)
        again = asyncio.create_task(bc.wait_for_viewer())
        await asyncio.sleep(0)
        assert not again.done()  # the last viewer left, so the next wait waits
        again.cancel()

    asyncio.run(scenario())


def test_a_socket_past_max_viewers_is_closed_with_try_again_later():
    """Every viewer gets their own frame stream from a home upload, so a link that travels must
    not be able to take the connection with it. The page reads 1013 as "the demo is full"."""
    bc = Broadcaster(max_viewers=1)
    client = TestClient(create_app(bc))
    with client.websocket_connect("/ws"):
        assert bc.viewers == 1
        with client.websocket_connect("/ws") as second:
            try:
                second.receive_text()
            except WebSocketDisconnect as closed:
                assert closed.code == 1013
            else:
                raise AssertionError("the second viewer was not turned away")
        assert bc.viewers == 1


def test_health_reports_the_latest_status_and_how_many_are_watching():
    """The demo supervisor polls this to tell a run that is waiting on purpose (nobody watching,
    or today's budget spent) from one that has hung (#67)."""
    bc = Broadcaster()
    client = TestClient(create_app(bc))
    assert client.get("/health").json() == {"status": None, "viewers": 0}
    bc.latest["status"] = status_event("unwatched", "nobody is watching")
    with client.websocket_connect("/ws"):
        assert client.get("/health").json() == {"status": "unwatched", "viewers": 1}
