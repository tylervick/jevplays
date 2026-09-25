"""The image must never be able to hold game data, and fly.toml and the Dockerfile must agree
on where the volume is. No Docker here: these read the files; CI's `image` job builds it."""

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAME_DATA = {
    "roms",
    "states",
    "runs",
    ".worktrees",
    "**/*.gb",
    "**/*.gbc",
    "**/*.state",
    "**/*.ram",
    "mise.local.toml",
}
MAY_COPY = {"pyproject.toml", "uv.lock", "README.md", ".python-version", "src", "Scripts/demo-loop.py"}


def dockerfile() -> list[str]:
    return (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()


def fly() -> dict:
    return tomllib.loads((ROOT / "fly.toml").read_text(encoding="utf-8"))


def test_the_build_context_leaves_out_every_kind_of_game_data():
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    ignored = {line.strip() for line in lines if line.strip() and not line.startswith("#")}
    assert GAME_DATA <= ignored


def test_the_image_copies_only_the_package_and_the_supervisor():
    sources = set()
    for line in dockerfile():
        if line.startswith("COPY "):
            parts = [p for p in line.split()[1:] if not p.startswith("--")]
            sources.update(parts[:-1])
    assert sources and sources <= MAY_COPY


def test_the_rom_and_the_runs_live_on_the_volume():
    config = fly()
    mount = config["mounts"]["destination"]
    assert config["env"]["JEVPLAYS_ROM"].startswith(mount + "/")
    [cmd] = [json.loads(line[len("CMD ") :]) for line in dockerfile() if line.startswith("CMD ")]
    assert cmd[cmd.index("--runs-dir") + 1].startswith(mount + "/")


def test_the_machine_runs_always_and_is_checked_on_health():
    """The demo pauses itself when unwatched; Fly auto-stop would fight that and the resume."""
    service = fly()["http_service"]
    assert service["internal_port"] == 8765
    assert service["auto_stop_machines"] == "off"
    assert [c["path"] for c in service["checks"]] == ["/health"]


def test_fly_waits_longer_than_the_supervisor_does_for_a_run_to_checkpoint():
    """`stop()` gives a run 15s after SIGTERM to write its exit checkpoint before SIGKILL."""
    timeout = fly()["kill_timeout"]
    assert fly()["kill_signal"] == "SIGTERM"
    assert int(str(timeout).rstrip("s")) > 15
