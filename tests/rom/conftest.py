"""Fixtures for tests that need the real game.

JEVPLAYS_ROM points at a Pokémon Red or Blue dump. JEVPLAYS_STATES (default: states/) holds
the save states Scripts/make-states.py writes. Missing either skips the test rather than failing
it, so CI, which has neither, stays green while a developer with both gets full coverage.
"""

import os
from collections.abc import Callable
from pathlib import Path

import pytest

_rom = os.environ.get("JEVPLAYS_ROM")
if not _rom or not Path(_rom).is_file():
    # Set at collection time, before any fixture runs, so a run with no ROM never imports these
    # modules (and so never imports pyboy/SDL): pytest reads collect_ignore_glob from conftest.py
    # itself, ahead of collecting the sibling test_*.py files.
    collect_ignore_glob = ["test_*.py"]


@pytest.fixture(scope="session")
def rom() -> Path:
    path = os.environ.get("JEVPLAYS_ROM")
    if not path or not Path(path).is_file():
        pytest.skip("JEVPLAYS_ROM is not set or does not point at a file")
    return Path(path)


@pytest.fixture(scope="session")
def states_dir() -> Path:
    return Path(os.environ.get("JEVPLAYS_STATES", "states"))


@pytest.fixture
def state_path(states_dir: Path) -> Callable[[str], Path]:
    def _state(name: str) -> Path:
        path = states_dir / f"{name}.state"
        if not path.is_file():
            pytest.skip(f"{path} is missing; run `mise run states`")
        return path

    return _state
