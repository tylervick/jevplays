# The demo supervisor (Scripts/demo-loop.py) and the package it runs, headless. No game data:
# .dockerignore keeps it out of the context and the COPY lines below name everything that goes in.
# The ROM is on the Fly volume at /data/rom (see fly.toml and README.md "Production").
FROM ghcr.io/astral-sh/uv:0.12.17-python3.14-trixie-slim@sha256:63018e7b676ef735eee4da4f9c2e7b5f5e3851fa023745d78ce91d1a099a35fd

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_SYNC=1 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first, so a change to src/ does not reinstall them.
COPY pyproject.toml uv.lock README.md .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY Scripts/demo-loop.py ./Scripts/demo-loop.py
RUN uv sync --frozen --no-dev

EXPOSE 8765
CMD ["uv", "run", "python", "Scripts/demo-loop.py", "--host", "0.0.0.0", "--runs-dir", "/data/runs", "--speed", "3", "--daily-decisions", "3000"]
