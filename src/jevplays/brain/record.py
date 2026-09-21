"""The Decision-record shape shared by every decision point: how a question is logged, and how
a raw answer becomes an `applied`-tracked record.
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
