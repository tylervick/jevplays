"""A Starlette app: the static page, and a websocket that fans events out to every open tab."""

import asyncio
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
        self.first_client = asyncio.Event()
        """Set the first time a tab connects, so `replay` can hold off until someone is watching."""

    async def connect(self, ws) -> None:
        self.clients.add(ws)
        self.first_client.set()
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


async def serve(
    app: Starlette, host: str = "127.0.0.1", port: int = 8765, stop: asyncio.Event | None = None
) -> None:
    """Serve until cancelled, or until `stop` is set: then uvicorn shuts down the way it wants
    to (its lifespan logs a traceback when it is cancelled mid-wait instead)."""
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    if stop is None:
        await server.serve()
        return
    serving = asyncio.create_task(server.serve())
    stopped = asyncio.create_task(stop.wait())
    await asyncio.wait({serving, stopped}, return_when=asyncio.FIRST_COMPLETED)
    stopped.cancel()
    if not serving.done():
        server.should_exit = True
    # Awaited either way: when serving finished first it did so on its own -- a port already in
    # use is the usual reason -- and its exception belongs to the caller, not to a task nobody
    # ever looks at again.
    await serving
