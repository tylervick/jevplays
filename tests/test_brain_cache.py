import asyncio

import pytest

from jevplays.brain.cache import CachedBrain, ModelDrift, cache_key


class DictStore:
    def __init__(self):
        self.rows = {}

    def get_response(self, key):
        return self.rows.get(key)

    def put_response(self, key, response, latency_ms, model):
        self.rows.setdefault(key, (response, latency_ms))


class Inner:
    model = "jev-latest"

    def __init__(self, reported="jev-1.13.0"):
        self.calls = 0
        self.reported = reported
        self.closed = False

    async def ask(self, state, questions):
        self.calls += 1
        return {"model": self.reported, "answers": {"n": self.calls}}, 300

    async def close(self):
        self.closed = True


Q = {"run": {"type": "noul", "instructions": "Run?"}}


def test_the_second_identical_ask_is_served_from_the_store_and_marked_cached():
    inner, store = Inner(), DictStore()
    brain = CachedBrain(inner, store, expected_model="jev-1.13.0")
    first, _ = asyncio.run(brain.ask({"hp": "low"}, Q))
    second, latency = asyncio.run(brain.ask({"hp": "low"}, Q))
    assert inner.calls == 1 and brain.calls == 1 and brain.hits == 1
    assert second == {**first, "cached": True} and latency == 300
    assert "cached" not in first


def test_the_key_changes_with_model_state_and_questions():
    base = cache_key("jev-latest", {"hp": "low"}, Q)
    assert base == cache_key("jev-latest", {"hp": "low"}, dict(Q))
    assert base != cache_key("jev-other", {"hp": "low"}, Q)
    assert base != cache_key("jev-latest", {"hp": "high"}, Q)
    assert base != cache_key("jev-latest", {"hp": "low"}, {"catch": Q["run"]})


def test_a_different_model_than_the_run_used_stops_the_measurement():
    brain = CachedBrain(Inner(reported="jev-2.0.0"), DictStore(), expected_model="jev-1.13.0")
    with pytest.raises(ModelDrift, match="jev-2.0.0"):
        asyncio.run(brain.ask({}, Q))


def test_close_closes_the_inner_brain():
    inner = Inner()
    asyncio.run(CachedBrain(inner, DictStore(), expected_model=None).close())
    assert inner.closed


def test_close_tolerates_a_brain_with_nothing_to_close():
    class Bare:
        async def ask(self, state, questions):
            return {}, 0

    asyncio.run(CachedBrain(Bare(), DictStore(), expected_model=None).close())


def test_concurrent_misses_converge_on_the_first_answer_stored(tmp_path):
    """Two branch processes miss on the same input at once: the one whose answer lands second in
    the store must return the first one's, so every branch faces the same Jev."""
    from jevplays.branch.store import BranchStore

    db = tmp_path / "branches.sqlite"
    store_a, store_b = BranchStore(db), BranchStore(db)
    brain_b = CachedBrain(Inner(), store_b, expected_model=None)

    class Racing(Inner):
        async def ask(self, state, questions):
            # while A's request is in flight, B misses, asks, and stores its answer first
            self.competing = await brain_b.ask(state, questions)
            return {"model": self.reported, "answers": {"n": "A's own"}}, 999

    racing = Racing()
    brain_a = CachedBrain(racing, store_a, expected_model=None)
    got, latency = asyncio.run(brain_a.ask({"hp": "low"}, Q))
    assert racing.competing == ({"model": "jev-1.13.0", "answers": {"n": 1}}, 300)
    assert (got, latency) == racing.competing
    assert store_a.get_response(cache_key("jev-latest", {"hp": "low"}, Q)) == racing.competing
    assert brain_a.calls == 1 and brain_b.calls == 1
