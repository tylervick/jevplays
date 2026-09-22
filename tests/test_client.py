import asyncio

import pytest

from jevplays.brain.client import Brain
from jevplays.brain.errors import BrainUnavailable


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def model_dump(self):
        return self._payload


class FakeClient:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    async def system_one(self, state, questions, **kwargs):
        self.calls.append((state, questions))
        if self.error:
            raise self.error
        return FakeResponse(self.payload)

    async def aclose(self):
        pass


PAYLOAD = {
    "model": "jev-1.13.0",
    "usage": {"input_tokens": 10, "output_tokens": 1},
    "answers": {
        "move": {"type": "choice", "choice": "SCRATCH", "probabilities": {"SCRATCH": 1.0}, "confidence": 1.0}
    },
}
QUESTIONS = {
    "move": {"type": "choice", "instructions": "Which?", "criteria": {"SCRATCH": None}},
    "run": {"type": "noul", "instructions": "Run?", "criteria": {"true": "yes", "false": "no"}},
}


def test_ask_converts_questions_and_returns_the_dump_and_latency():
    fake = FakeClient(payload=PAYLOAD)
    brain = Brain(client=fake)
    response, ms = asyncio.run(brain.ask({"x": 1}, QUESTIONS))
    assert response == PAYLOAD and ms >= 0
    state, questions = fake.calls[0]
    assert state == {"x": 1}
    assert type(questions["move"]).__name__ == "Choice" and type(questions["run"]).__name__ == "Noul"
    assert questions["move"].criteria == {"SCRATCH": None}


def test_api_errors_become_brain_unavailable():
    from typesafe_sdk import TypeSafeAPIConnectionError

    brain = Brain(client=FakeClient(error=TypeSafeAPIConnectionError("boom")))
    with pytest.raises(BrainUnavailable):
        asyncio.run(brain.ask({}, QUESTIONS))


class HangingClient:
    """A request that stays open and never answers -- the failure the SDK's retries cannot see,
    because nothing ever raises."""

    def __init__(self):
        self.calls = 0

    async def system_one(self, state, questions):
        self.calls += 1
        await asyncio.sleep(30)
        raise AssertionError("should have been given up on long before this")


def test_a_request_that_never_answers_becomes_brain_unavailable():
    """#47: a paced run stopped dead in a battle with an open connection to the API and no
    timeout, so the loop's waiting_for_api path never fired and the run never recovered."""
    client = HangingClient()
    brain = Brain(client=client, timeout=0.05)
    with pytest.raises(BrainUnavailable, match="no answer"):
        asyncio.run(brain.ask({"map": "Route 1"}, {}))
    assert client.calls == 1


def test_a_request_that_answers_in_time_is_untouched():
    brain = Brain(client=FakeClient(payload={"answers": {}}), timeout=5)
    response, latency_ms = asyncio.run(brain.ask({}, {}))
    assert response == {"answers": {}} and latency_ms >= 0
