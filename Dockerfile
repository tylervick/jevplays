# The demo supervisor (Scripts/demo-loop.py) and the package it runs, headless. No game data:
# .dockerignore keeps it out of the context and the COPY lines below name everything that goes in.
# The ROM is on the Fly volume at /data/rom (see fly.toml and README.md "Production").
FROM ghcr.io/astral-sh/uv:0.12.17-python3.14-trixie-slim@sha256:63018e7b676ef735eee4da4f9c2e7b5f5e3851fa023745d78ce91d1a099a35fd

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_SYNC=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_CACHE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first, so a change to src/ does not reinstall them.
COPY pyproject.toml uv.lock README.md .python-version ./
# pyboy ships its own tiny placeholder ROM (used only when a caller gives it no path of its own);
# jevplays always passes JEVPLAYS_ROM, so it is dead weight here and the one thing that would
# otherwise put a *.gb file in the image by an accident of a dependency, not of this Dockerfile.
# The delete has to run in this same layer: a later RUN's delete only whiteouts the file in the
# final filesystem view, but flyctl deploy pushes every layer, bytes and all, to the registry.
# UV_NO_CACHE (above) keeps uv's cache, which would hold a second copy of it, out of every layer.
RUN uv sync --frozen --no-dev --no-install-project && \
    find /app/.venv \( -name '*.gb' -o -name '*.gbc' -o -name '*.state' -o -name '*.ram' \) -delete

COPY src ./src
COPY Scripts/demo-loop.py ./Scripts/demo-loop.py
# Only the project itself installs here, no new third-party packages, so nothing in this layer
# can reintroduce game data; no second delete needed.
RUN uv sync --frozen --no-dev

EXPOSE 8765
CMD ["uv", "run", "python", "Scripts/demo-loop.py", "--host", "0.0.0.0", "--runs-dir", "/data/runs", "--speed", "3", "--daily-decisions", "3000"]
