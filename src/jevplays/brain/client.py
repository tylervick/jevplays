"""The only module that imports the TypeSafe SDK.

One request per decision point. The SDK retries transient failures itself; anything that still
fails becomes BrainUnavailable so the loop can pause and show it, never press a random button.
"""

import time

from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, TypeSafeError

from jevplays.brain.errors import BrainUnavailable

__all__ = ["Brain", "BrainUnavailable", "to_sdk_questions"]


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
    def __init__(self, model: str = "jev-latest", client=None) -> None:
        self.model = model
        self._client = client if client is not None else AsyncTypeSafeClient(model=model)

    async def ask(self, state: dict, questions: dict[str, dict]) -> tuple[dict, int]:
        sdk_questions = to_sdk_questions(questions)
        started = time.monotonic()
        try:
            response = await self._client.system_one(state, sdk_questions)
        except TypeSafeError as error:
            raise BrainUnavailable(str(error)) from error
        return response.model_dump(), int((time.monotonic() - started) * 1000)

    async def close(self) -> None:
        await self._client.aclose()
