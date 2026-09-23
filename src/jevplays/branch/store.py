"""Everything one branch measurement writes: `runs/<stamp>/branches/branches.sqlite`.

One file, in WAL mode, written by every branch process at once. A branch's decisions go in as it
makes them; its `branch` row goes in when it ends, so a (decision, alternative, seed) with a row
is finished and one without is not -- which is how an interrupted measurement resumes (spec:
"Storage")."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decision_info (
    decision INTEGER PRIMARY KEY, kind TEXT NOT NULL, chosen TEXT NOT NULL,
    alternatives TEXT NOT NULL, strongest TEXT, offline TEXT, reference_frames INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS skipped (decision INTEGER PRIMARY KEY, reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS branch (
    decision INTEGER NOT NULL, alternative TEXT NOT NULL, seed INTEGER NOT NULL,
    outcome TEXT NOT NULL, frames INTEGER, blackouts INTEGER NOT NULL,
    jev_calls INTEGER NOT NULL, cache_hits INTEGER NOT NULL, error TEXT, finished_at TEXT NOT NULL,
    PRIMARY KEY (decision, alternative, seed)
);
CREATE TABLE IF NOT EXISTS decision (
    decision INTEGER NOT NULL, alternative TEXT NOT NULL, seed INTEGER NOT NULL,
    seq INTEGER NOT NULL, body TEXT NOT NULL,
    PRIMARY KEY (decision, alternative, seed, seq)
);
CREATE TABLE IF NOT EXISTS response (
    key TEXT PRIMARY KEY, body TEXT NOT NULL, latency_ms INTEGER NOT NULL, model TEXT NOT NULL
);
"""


class BranchKey(NamedTuple):
    decision: int
    alternative: str
    seed: int


@dataclass(frozen=True)
class BranchResult:
    outcome: str  # done | capped | stalled | error
    frames: int | None
    blackouts: int
    jev_calls: int
    cache_hits: int
    error: str | None = None


@dataclass(frozen=True)
class DecisionInfo:
    decision: int
    kind: str
    chosen: str
    alternatives: list[str]
    strongest: str | None
    offline: str | None
    reference_frames: int


class BranchStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._db = sqlite3.connect(path, timeout=60, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    # -- meta, decisions measured, decisions skipped ------------------------------------

    def set_meta(self, key: str, value: str) -> None:
        self._db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))

    def meta(self) -> dict[str, str]:
        return dict(self._db.execute("SELECT key, value FROM meta"))

    def put_decision_info(self, info: DecisionInfo) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO decision_info VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                info.decision,
                info.kind,
                info.chosen,
                json.dumps(info.alternatives),
                info.strongest,
                info.offline,
                info.reference_frames,
            ),
        )

    def decision_infos(self) -> list[DecisionInfo]:
        rows = self._db.execute("SELECT * FROM decision_info ORDER BY decision")
        return [DecisionInfo(d, k, c, json.loads(a), s, o, r) for d, k, c, a, s, o, r in rows]

    def skip(self, decision: int, reason: str) -> None:
        self._db.execute("INSERT OR REPLACE INTO skipped VALUES (?, ?)", (decision, reason))

    def skipped(self) -> dict[int, str]:
        return dict(self._db.execute("SELECT decision, reason FROM skipped ORDER BY decision"))

    # -- branches -----------------------------------------------------------------------

    def done(self) -> set[BranchKey]:
        return {BranchKey(*row) for row in self._db.execute("SELECT decision, alternative, seed FROM branch")}

    def clear_partial(self, key: BranchKey) -> None:
        """Forget the decisions of a branch that never finished, so rerunning it starts clean."""
        self._db.execute(
            "DELETE FROM decision WHERE decision = ? AND alternative = ? AND seed = ?", tuple(key)
        )

    def add_decision(self, key: BranchKey, seq: int, body: dict) -> None:
        self._db.execute(
            "INSERT INTO decision VALUES (?, ?, ?, ?, ?)",
            (*key, seq, json.dumps(body, ensure_ascii=False)),
        )

    def branch_decisions(self, key: BranchKey) -> list[dict]:
        rows = self._db.execute(
            "SELECT body FROM decision WHERE decision = ? AND alternative = ? AND seed = ? ORDER BY seq",
            tuple(key),
        )
        return [json.loads(body) for (body,) in rows]

    def finish_branch(self, key: BranchKey, result: BranchResult) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO branch VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                *key,
                result.outcome,
                result.frames,
                result.blackouts,
                result.jev_calls,
                result.cache_hits,
                result.error,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )

    def branches(self, decision: int | None = None) -> list[tuple[BranchKey, BranchResult]]:
        sql = (
            "SELECT decision, alternative, seed, outcome, frames, blackouts, jev_calls, cache_hits, error "
            "FROM branch"
        )
        args: tuple = ()
        if decision is not None:
            sql += " WHERE decision = ?"
            args = (decision,)
        sql += " ORDER BY decision, alternative, seed"
        return [
            (BranchKey(d, a, s), BranchResult(o, f, b, c, h, e))
            for d, a, s, o, f, b, c, h, e in self._db.execute(sql, args)
        ]

    # -- the response cache (brain/cache.py's store) ------------------------------------

    def get_response(self, key: str) -> tuple[dict, int] | None:
        row = self._db.execute("SELECT body, latency_ms FROM response WHERE key = ?", (key,)).fetchone()
        return (json.loads(row[0]), row[1]) if row else None

    def put_response(self, key: str, response: dict, latency_ms: int, model: str) -> None:
        self._db.execute(
            "INSERT OR IGNORE INTO response VALUES (?, ?, ?, ?)",
            (key, json.dumps(response, ensure_ascii=False), latency_ms, model),
        )


class BranchSink:
    """What a branch's `Loop` writes through in place of a `RunDir`: its decisions go to the store
    under the branch's key; checkpoints, memory and faint outcomes are not kept."""

    def __init__(self, store: BranchStore, key: BranchKey) -> None:
        self.store = store
        self.key = key
        self._n = 0

    def count(self) -> int:
        return self._n

    def append(self, decision) -> int:
        self._n += 1
        self.store.add_decision(self.key, self._n, decision.to_dict())
        return self._n

    def set_model(self, model: str) -> None:
        pass

    def checkpoint(self, emu, n: int) -> None:
        return None

    def save_memory(self, d: dict) -> None:
        pass

    def append_outcome(self, outcome: dict) -> None:
        pass


def export_branch(store: BranchStore, key: BranchKey, root: Path) -> Path:
    """Write one branch out as an ordinary run directory, so `jevplays replay` plays it."""
    from jevplays.runlog import RunDir

    run = RunDir.create(root, rom=None, flags={"branch": list(key), "measurement": str(store.path)})
    with open(run.log_path, "w", encoding="utf-8") as f:
        for body in store.branch_decisions(key):
            f.write(json.dumps(body, ensure_ascii=False) + "\n")
    return run.path
