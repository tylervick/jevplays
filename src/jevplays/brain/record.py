"""The Decision-record shape shared by every decision point: how a question is logged, and how
a raw answer becomes an `applied`-tracked record.

Both helpers read dicts this package built or validated itself: `q` comes from a `*_questions`
builder, and `a` is one entry of the SDK response's pydantic `model_dump()`, so the keys are
guaranteed by construction and a missing one is a programming error, not bad input.
"""


def question_record(q: dict) -> dict:
    return {
        "primitive": q["type"],
        "instructions": q["instructions"],
        "options": list(q["criteria"]) if q["type"] == "choice" else [],
    }


def answer_record(a: dict) -> dict:
    if a["type"] == "choice":
        return {
            "primitive": "choice",
            "choice": a["choice"],
            "probabilities": dict(a["probabilities"]),
            "confidence": a["confidence"],
            "applied": False,
        }
    return {"primitive": "noul", "noul": a["noul"], "applied": False}
