"""Scoring a branch measurement. Pure functions over rows, so every number the report prints can
be recomputed from `branches.sqlite` alone."""


def _values(response: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for qid, answer in response.get("answers", {}).items():
        if answer.get("type") == "noul":
            out[qid] = float(answer["noul"])
        elif answer.get("type") == "choice":
            for option, p in answer.get("probabilities", {}).items():
                out[f"{qid}:{option}"] = float(p)
    return out


def answer_spread(responses: list[dict]) -> float:
    """The largest absolute difference, across `responses` to one input, of any probability or
    noul. An answer one response has and another lacks counts as a spread of 1.0."""
    values = [_values(r) for r in responses]
    keys = set().union(*values) if values else set()
    spread = 0.0
    for key in keys:
        seen = [v[key] for v in values if key in v]
        if len(seen) < len(values):
            return 1.0
        spread = max(spread, max(seen) - min(seen))
    return spread
