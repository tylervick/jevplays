"""A Starlette app: the static page, and a websocket that fans events out to every open tab."""

import asyncio
from collections.abc import Callable
from pathlib import Path
from time import monotonic

import uvicorn
from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from jevplays.dashboard.events import encode

STATIC = Path(__file__).parent / "static"

TRY_AGAIN_LATER = 1013
"""The close code a socket past `max_viewers` gets; the page reads it as "the demo is full"."""


class Broadcaster:
    """Holds the open sockets and the last event of each type, so a new tab is current at once."""

    def __init__(self, *, max_viewers: int | None = None, clock: Callable[[], float] = monotonic) -> None:
        self.clients: set = set()
        self.latest: dict[str, dict] = {}
        self.first_client = asyncio.Event()
        """Set the first time a tab connects, so `replay` can hold off until someone is watching."""
        self.max_viewers = max_viewers
        """Tabs served at once; None is no limit. Each one is its own frame stream."""
        self._clock = clock
        self._idle_since = clock()
        self._watched = asyncio.Event()

    @property
    def viewers(self) -> int:
        return len(self.clients)

    @property
    def full(self) -> bool:
        return self.max_viewers is not None and self.viewers >= self.max_viewers

    def idle_for(self) -> float:
        """Seconds since the last tab closed -- or since startup, before the first one opened --
        and 0 while anyone is watching. A run left for people to drop in on pauses on this."""
        return 0.0 if self.clients else self._clock() - self._idle_since

    async def wait_for_viewer(self) -> None:
        """Return once a tab is open: at once if one already is."""
        await self._watched.wait()

    async def connect(self, ws) -> None:
        self.clients.add(ws)
        self.first_client.set()
        self._watched.set()
        for event in self.latest.values():
            await self._send(ws, event)

    def disconnect(self, ws) -> None:
        if ws not in self.clients:
            return
        self.clients.discard(ws)
        if not self.clients:
            self._idle_since = self._clock()
            self._watched.clear()

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

    async def health(request):
        """What the demo supervisor polls: a run waiting on purpose is not a hung one (#67)."""
        status = broadcaster.latest.get("status")
        return JSONResponse({"status": status["status"] if status else None, "viewers": broadcaster.viewers})

    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        if broadcaster.full:
            # Accepted first so the page sees the code; refusing the handshake reads as 1006.
            await ws.close(code=TRY_AGAIN_LATER)
            return
        await broadcaster.connect(ws)
        try:
            while True:
                await ws.receive_text()  # the page never sends; this only notices the close
        except WebSocketDisconnect:
            broadcaster.disconnect(ws)

    return Starlette(
        routes=[
            Route("/", index),
            Route("/health", health),
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
