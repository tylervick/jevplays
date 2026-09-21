"""One run on disk: `runs/<stamp>/` with run.json, decisions.jsonl, and numbered checkpoints.

The loop writes through a RunDir; `jevplays run --resume` opens one and continues it; `jevplays
replay` reads the log back. Nothing here imports the emulator: `checkpoint` takes any object with
a `save(path)` method, which is what the real Emulator and the test fake both offer.
"""

import hashlib
import json
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from jevplays.brain.decision import Decision

CHECKPOINT_EVERY = 25
"""Decisions between checkpoints. Spec 11."""
RUN_DIR_FORMAT = "%Y%m%d-%H%M%S"
_CHECKPOINT = re.compile(r"^checkpoint-(\d+)\.state$")


def rom_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RunDir:
    def __init__(self, path: Path) -> None:
        self.path = path

    # -- creation and opening -----------------------------------------------------------

    @classmethod
    def create(cls, root: Path, *, rom: Path | None, flags: dict, now: datetime | None = None) -> "RunDir":
        now = now or datetime.now()
        path = root / now.strftime(RUN_DIR_FORMAT)
        path.mkdir(parents=True, exist_ok=False)
        run = cls(path)
        run._write_info(
            {
                "rom_sha256": rom_sha256(rom) if rom is not None else "",
                "started_at": now.isoformat(timespec="seconds"),
                "flags": flags,
                "model": "",
                "models": [],
                "resumed_at": [],
                "checkpoint_every": CHECKPOINT_EVERY,
            }
        )
        return run

    @classmethod
    def open(cls, path: Path) -> "RunDir":
        if not (path / "run.json").is_file():
            raise FileNotFoundError(f"{path / 'run.json'} is missing; not a run directory")
        return cls(path)

    # -- run.json -----------------------------------------------------------------------

    def info(self) -> dict:
        return json.loads((self.path / "run.json").read_text(encoding="utf-8"))

    def _write_info(self, info: dict) -> None:
        (self.path / "run.json").write_text(
            json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    def set_model(self, model: str) -> None:
        info = self.info()
        if not info["model"]:
            info["model"] = model
        if model not in info["models"]:
            info["models"].append(model)
        self._write_info(info)

    def mark_resumed(self, now: datetime | None = None) -> None:
        info = self.info()
        info["resumed_at"].append((now or datetime.now()).isoformat(timespec="seconds"))
        self._write_info(info)

    # -- decisions.jsonl ----------------------------------------------------------------

    @property
    def log_path(self) -> Path:
        return self.path / "decisions.jsonl"

    def append(self, decision: Decision) -> int:
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(decision.to_dict(), ensure_ascii=False) + "\n")
        return self.count()

    def count(self) -> int:
        if not self.log_path.is_file():
            return 0
        with open(self.log_path, "rb") as f:
            return sum(1 for line in f if line.strip())

    def decisions(self) -> Iterator[dict]:
        if not self.log_path.is_file():
            return
        with open(self.log_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)

    # -- checkpoints --------------------------------------------------------------------

    def checkpoint(self, emu, n: int) -> Path:
        path = self.path / f"checkpoint-{n}.state"
        emu.save(path)
        return path

    def last_checkpoint(self) -> Path | None:
        best: tuple[int, Path] | None = None
        for candidate in self.path.iterdir():
            m = _CHECKPOINT.match(candidate.name)
            if m and (best is None or int(m.group(1)) > best[0]):
                best = (int(m.group(1)), candidate)
        return best[1] if best else None
