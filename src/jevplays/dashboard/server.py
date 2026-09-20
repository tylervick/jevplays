"""A Starlette app: the static page, and a websocket that fans events out to every open tab."""

from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.responses import FileResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from jevplays.dashboard.events import encode

STATIC = Path(__file__).parent / "static"


class Broadcaster:
    """Holds the open sockets and the last event of each type, so a new tab is current at once."""

    def __init__(self) -> None:
        self.clients: set = set()
        self.latest: dict[str, dict] = {}

    async def connect(self, ws) -> None:
        self.clients.add(ws)
        for event in self.latest.values():
            await self._send(ws, event)

    def disconnect(self, ws) -> None:
        self.clients.discard(ws)

    async def publish(self, event: dict) -> None:
        self.latest[event["type"]] = event
        for ws in list(self.clients):
            await self._send(ws, event)

    async def _send(self, ws, event: dict) -> None:
        try:
            await ws.send_text(encode(event))
        except Exception:
            self.disconnect(ws)


def create_app(broadcaster: Broadcaster) -> Starlette:
    async def index(request):
        return FileResponse(STATIC / "index.html")

    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        await broadcaster.connect(ws)
        try:
            while True:
                await ws.receive_text()  # the page never sends; this only notices the close
        except WebSocketDisconnect:
            broadcaster.disconnect(ws)

    return Starlette(
        routes=[
            Route("/", index),
            WebSocketRoute("/ws", ws_endpoint),
            Mount("/static", StaticFiles(directory=STATIC), name="static"),
        ]
    )


async def serve(app: Starlette, host: str = "127.0.0.1", port: int = 8765) -> None:
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    await uvicorn.Server(config).serve()
