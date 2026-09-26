"""Scripts/ntfy.sh is how the workflows post to ntfy. Exercised against a local HTTP server."""

import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "Scripts" / "ntfy.sh"


def serve_once(status: int = 200):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            received.append((self.path, self.headers.get("Authorization"), self.rfile.read(length).decode()))
            self.send_response(status)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    return server, thread, received


def run(message: str, **env) -> subprocess.CompletedProcess:
    base = {k: v for k, v in os.environ.items() if k not in ("NTFY_URL", "NTFY_TOKEN")}
    return subprocess.run(["bash", str(SCRIPT), message], env={**base, **env}, capture_output=True, text=True)


def test_it_posts_the_message_with_the_token():
    server, thread, received = serve_once()
    result = run("deploy ok", NTFY_URL=f"http://127.0.0.1:{server.server_port}/demo", NTFY_TOKEN="tk")
    thread.join(5)
    server.server_close()
    assert result.returncode == 0
    assert received == [("/demo", "Bearer tk", "deploy ok")]


def test_without_a_url_it_does_nothing():
    assert run("deploy ok").returncode == 0


def test_a_refused_post_is_reported_but_never_fails_the_job():
    server, thread, received = serve_once(status=403)
    result = run("deploy ok", NTFY_URL=f"http://127.0.0.1:{server.server_port}/demo")
    thread.join(5)
    server.server_close()
    assert result.returncode == 0
    assert "ntfy post failed" in result.stderr
