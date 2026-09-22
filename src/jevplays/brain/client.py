"""The only module that imports the TypeSafe SDK.

One request per decision point. The SDK retries transient failures itself; anything that still
fails becomes BrainUnavailable so the loop can pause and show it, never press a random button.
"""

import asyncio
import time

from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, TypeSafeError

from jevplays.brain.errors import BrainUnavailable

REQUEST_TIMEOUT_S = 30.0
"""How long one decision's request may stay open before the loop gives up on it.

The SDK retries what fails. A connection that stays open and never answers never fails, so
nothing retries it and the await never returns -- a run stopped dead in a battle that way (#47),
process up, dashboard served, permanently still. Spec 2 quotes a few hundred milliseconds per
request, so this is generous rather than tight."""

__all__ = ["REQUEST_TIMEOUT_S", "Brain", "BrainUnavailable", "to_sdk_questions"]


def to_sdk_questions(questions: dict[str, dict]) -> dict:
    out = {}
    for qid, q in questions.items():
        if q["type"] == "choice":
            out[qid] = Choice(instructions=q["instructions"], criteria=q["criteria"])
        elif q["type"] == "noul":
            out[qid] = Noul(instructions=q["instructions"], criteria=q.get("criteria"))
        else:
            raise ValueError(f"unsupported question type {q['type']!r} for {qid}")
    return out


class Brain:
    def __init__(self, model: str = "jev-latest", client=None, timeout: float = REQUEST_TIMEOUT_S) -> None:
        self.model = model
        self.timeout = timeout
        self._client = client if client is not None else AsyncTypeSafeClient(model=model)

    async def ask(self, state: dict, questions: dict[str, dict]) -> tuple[dict, int]:
        sdk_questions = to_sdk_questions(questions)
        started = time.monotonic()
        try:
            response = await asyncio.wait_for(
                self._client.system_one(state, sdk_questions), timeout=self.timeout
            )
        except TimeoutError as error:
            # Into the same path a failed request takes: the loop shows waiting_for_api, backs
            # off, and asks the same question again rather than pressing a button on a guess.
            raise BrainUnavailable(f"no answer in {self.timeout:.0f}s") from error
        except TypeSafeError as error:
            raise BrainUnavailable(str(error)) from error
        return response.model_dump(), int((time.monotonic() - started) * 1000)

    async def close(self) -> None:
        await self._client.aclose()
