import asyncio
import json

from starlette.testclient import TestClient

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
