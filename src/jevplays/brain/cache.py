"""A brain that remembers its answers, for branch measurements (#82).

Jev sees buckets, not numbers, so branches of one decision keep putting the same question to it.
`CachedBrain` wraps the real brain, has the same `ask`, and answers a repeated input from the
store. The loop cannot tell the difference, and the SDK stays in `brain/client.py`."""

import hashlib
import json
from typing import Protocol


class ResponseStore(Protocol):
    def get_response(self, key: str) -> tuple[dict, int] | None: ...

    def put_response(self, key: str, response: dict, latency_ms: int, model: str) -> None: ...


class ModelDrift(RuntimeError):
    """A live answer came from a different model than the run being measured used, so branches
    would compare two versions of Jev. The measurement stops rather than mix them."""


def cache_key(model: str, state: dict, questions: dict) -> str:
    blob = json.dumps(
        {"model": model, "state": state, "questions": questions},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class CachedBrain:
    def __init__(self, inner, store: ResponseStore, *, expected_model: str | None) -> None:
        self.inner = inner
        self.store = store
        self.expected_model = expected_model or None
        self.model = getattr(inner, "model", "")
        self.calls = 0
        self.hits = 0

    async def ask(self, state: dict, questions: dict) -> tuple[dict, int]:
        key = cache_key(self.model, state, questions)
        hit = self.store.get_response(key)
        if hit is not None:
            self.hits += 1
            response, latency_ms = hit
            return {**response, "cached": True}, latency_ms
        response, latency_ms = await self.inner.ask(state, questions)
        self.calls += 1
        reported = response.get("model", "")
        if self.expected_model and reported and reported != self.expected_model:
            raise ModelDrift(f"the run used {self.expected_model}; this answer came from {reported}")
        # Another branch process may have asked the same input while this one waited; the store
        # keeps the first write, and returning that one (not this answer) means every branch that
        # puts this input to Jev gets the same answer (spec: "The response cache").
        self.store.put_response(key, response, latency_ms, reported)
        stored = self.store.get_response(key)
        return stored if stored is not None else (response, latency_ms)

    async def close(self) -> None:
        close = getattr(self.inner, "close", None)
        if close is not None:
            await close()
