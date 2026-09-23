"""One run on disk: `runs/<stamp>/` with run.json, decisions.jsonl, memory.json, and checkpoints.

The loop writes through a RunDir; `jevplays run --resume` opens one and continues it; `jevplays
replay` reads the log back. Nothing here imports the emulator: `checkpoint` takes any object with
a `save(path)` method, which is what the real Emulator and the test fake both offer.
"""

import hashlib
import json
import os
import re
import warnings
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from jevplays.brain.decision import Decision

CHECKPOINT_EVERY = 25
"""Decisions between checkpoints. Spec 11."""
RUN_DIR_FORMAT = "%Y%m%d-%H%M%S"
_CHECKPOINT = re.compile(r"^checkpoint-(\d+)\.state$")


def _terminated(line: str) -> str:
    """The line as it was, with the newline jsonl needs (the torn last line may lack one)."""
    return line if line.endswith("\n") else line + "\n"


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
        if info["model"] == model and model in info["models"]:
            return  # nothing to record; don't rewrite run.json once per decision
        if not info["model"]:
            info["model"] = model
        if model not in info["models"]:
            info["models"].append(model)
        self._write_info(info)

    def mark_resumed(
        self,
        now: datetime | None = None,
        *,
        from_checkpoint: int | None = None,
        orphaned: int = 0,
    ) -> None:
        """Record a resume. With `from_checkpoint` the entry is a dict naming the checkpoint the
        run restarted from and how many decisions after it were orphaned; without it (a resume
        that resolved no checkpoint of its own) the entry is the plain timestamp string."""
        info = self.info()
        at = (now or datetime.now()).isoformat(timespec="seconds")
        entry: str | dict
        if from_checkpoint is None:
            entry = at
        else:
            entry = {"at": at, "from_checkpoint": from_checkpoint, "orphaned": orphaned}
        info["resumed_at"].append(entry)
        self._write_info(info)

    # -- decisions.jsonl ----------------------------------------------------------------

    @property
    def log_path(self) -> Path:
        return self.path / "decisions.jsonl"

    @property
    def orphaned_path(self) -> Path:
        return self.path / "decisions.orphaned.jsonl"

    def append(self, decision: Decision) -> int:
        torn = self._torn_line_number()
        with open(self.log_path, "a", encoding="utf-8") as f:
            if torn is not None:
                # A crash mid-write left a partial line. Close it off rather than let the new
                # decision fuse onto its tail.
                f.write("\n")
            f.write(json.dumps(decision.to_dict(), ensure_ascii=False) + "\n")
        if torn is not None:
            # Once repaired the partial line is no longer the last one, so `decisions()` could
            # not tell it from corruption. run.json remembers it instead: the line keeps its
            # slot (and its place in the count) and the log stays readable for good.
            self._note_torn_line(torn)
        return self.count()

    def _torn_line_number(self) -> int | None:
        """The 1-based line number of an unterminated final line (a torn write), else None."""
        if not self.log_path.is_file():
            return None
        with open(self.log_path, "rb") as f:
            f.seek(0, 2)
            if f.tell() == 0:
                return None
            f.seek(-1, 2)
            if f.read(1) == b"\n":
                return None
            f.seek(0)
            return sum(1 for _ in f)  # the unterminated line is still a line

    def _note_torn_line(self, number: int) -> None:
        info = self.info()
        torn = info.setdefault("torn_lines", [])
        if number not in torn:
            torn.append(number)
            self._write_info(info)

    def _torn_lines(self) -> set[int]:
        if not (self.path / "run.json").is_file():
            return set()
        return set(self.info().get("torn_lines", []))

    def count(self) -> int:
        """Non-blank lines in the log, torn last line included: the decision it was going to be
        happened, and the count is what checkpoints are numbered by. The next `append` repairs
        the line, so the count stays the same across that repair."""
        if not self.log_path.is_file():
            return 0
        with open(self.log_path, "rb") as f:
            return sum(1 for line in f if line.strip())

    def decisions(self) -> Iterator[dict]:
        """Every logged decision. A final line that does not parse is a torn write (the process
        died mid-`append`): it is skipped with a warning, as is a line a later `append` repaired.
        Any other line that does not parse is corruption, and raises."""
        if not self.log_path.is_file():
            return
        torn = self._torn_lines()
        with open(self.log_path, encoding="utf-8") as f:
            pending: tuple[int, str] | None = None
            for number, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                if pending is not None:
                    yield from self._parse(*pending, torn=torn)
                pending = (number, line)
            if pending is not None:
                yield from self._parse(*pending, torn=torn, last=True)

    def _parse(self, number: int, line: str, *, torn: set[int], last: bool = False) -> Iterator[dict]:
        try:
            yield json.loads(line)
        except ValueError as error:
            if not (last or number in torn):
                raise ValueError(f"{self.log_path}: line {number} is not valid JSON: {error}") from error
            warnings.warn(
                f"{self.log_path}: line {number} is incomplete (a torn write) and was skipped",
                stacklevel=2,
            )

    def truncate_to(self, n: int) -> int:
        """Drop everything after decision `n`, moving those lines to `decisions.orphaned.jsonl`.

        Resuming from `checkpoint-<n>.state` rewinds the game to just after decision `n`; any
        decision the log holds beyond that was rolled back with it and must not be replayed or
        counted. Returns how many lines moved (0 when the log is already at most `n` long)."""
        if self.count() <= n:
            return 0
        with open(self.log_path, encoding="utf-8") as f:
            lines = [line for line in f if line.strip()]
        keep, surplus = lines[:n], lines[n:]
        with open(self.orphaned_path, "a", encoding="utf-8") as f:
            f.writelines(_terminated(line) for line in surplus)
        # Rewrite through a temp file and a rename: a crash mid-write must leave the old log,
        # not an empty or half-written one.
        tmp = self.log_path.with_suffix(".jsonl.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(_terminated(line) for line in keep)
        os.replace(tmp, self.log_path)
        info = self.info()
        if any(number > n for number in info.get("torn_lines", [])):
            info["torn_lines"] = [number for number in info["torn_lines"] if number <= n]
            self._write_info(info)
        return len(surplus)

    # -- memory.json --------------------------------------------------------------------

    @property
    def memory_path(self) -> Path:
        return self.path / "memory.json"

    def save_memory(self, d: dict) -> None:
        """Write the run's `executor.options.Memory` out, whole, after every change to it.

        Through a temp file and a rename, like `truncate_to`: the loop rewrites this file every
        few seconds, and a crash mid-write must leave the last good memory rather than half of
        the new one -- a `--resume` reads it back and would otherwise start the run amnesiac."""
        tmp = self.memory_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.memory_path)

    def load_memory(self) -> dict | None:
        """What `save_memory` last wrote, or None for a run that never wrote any (one from
        before memory existed, or one that stopped before its first decision)."""
        if not self.memory_path.is_file():
            return None
        return json.loads(self.memory_path.read_text(encoding="utf-8"))

    # -- outcomes.jsonl -----------------------------------------------------------------

    @property
    def outcomes_path(self) -> Path:
        return self.path / "outcomes.jsonl"

    def append_outcome(self, outcome: dict) -> None:
        """Append one resolved prediction, keyed by the decision it scores. Its own stream
        because the decision line was written turns earlier and is never rewritten: `append`'s
        torn-line repair and `truncate_to`'s numbering both depend on that."""
        with open(self.outcomes_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(outcome, ensure_ascii=False) + "\n")

    def outcomes(self) -> Iterator[dict]:
        """Every resolved prediction. An unterminated line is a torn write and is skipped: a
        missing outcome costs one sample in a score, so there is nothing here worth raising
        over."""
        if not self.outcomes_path.is_file():
            return
        with open(self.outcomes_path, encoding="utf-8") as f:
            for line in f:
                if line.strip() and line.endswith("\n"):
                    yield json.loads(line)

    # -- checkpoints --------------------------------------------------------------------

    def checkpoint(self, emu, n: int) -> Path:
        path = self.path / f"checkpoint-{n}.state"
        emu.save(path)
        return path

    @staticmethod
    def checkpoint_number(path: Path) -> int:
        """The `<n>` in `checkpoint-<n>.state`: the decision count when it was written."""
        m = _CHECKPOINT.match(Path(path).name)
        if m is None:
            raise ValueError(f"not a checkpoint file name: {path}")
        return int(m.group(1))

    def last_checkpoint(self) -> Path | None:
        best: tuple[int, Path] | None = None
        for candidate in self.path.iterdir():
            m = _CHECKPOINT.match(candidate.name)
            if m and (best is None or int(m.group(1)) > best[0]):
                best = (int(m.group(1)), candidate)
        return best[1] if best else None

    # -- snapshots (#82) ----------------------------------------------------------------

    @property
    def snapshots_path(self) -> Path:
        return self.path / "snapshots"

    def snapshot(self, emu, n: int, sidecar: dict) -> Path:
        """The game and what the loop knew at decision `n`, after it was logged and before its
        buttons were pressed: the point a counterfactual branch starts from."""
        self.snapshots_path.mkdir(exist_ok=True)
        path = self.snapshots_path / f"{n}.state"
        emu.save(path)
        (self.snapshots_path / f"{n}.json").write_text(
            json.dumps(sidecar, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return path

    def snapshot_state(self, n: int) -> Path | None:
        path = self.snapshots_path / f"{n}.state"
        return path if path.is_file() else None

    def snapshot_info(self, n: int) -> dict | None:
        path = self.snapshots_path / f"{n}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def note_milestone(self, milestone: str, frame: int) -> None:
        self.snapshots_path.mkdir(exist_ok=True)
        with open(self.snapshots_path / "milestones.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"milestone": milestone, "frame": frame}) + "\n")

    def milestones_done(self) -> dict[str, int]:
        """The game frame each milestone was first seen done at, on the clock the sidecars use."""
        path = self.snapshots_path / "milestones.jsonl"
        done: dict[str, int] = {}
        if not path.is_file():
            return done
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                done.setdefault(row["milestone"], row["frame"])
        return done
