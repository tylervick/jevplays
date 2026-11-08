"""The `view` attached to every decision event: the decision in the words a viewer needs first.

Spec 2026-10-02 dashboard redesign, 3.6. Pure: a decision dict in, a plain dict out, from the
decision alone, so the loop and the replay of any old log present the same way. Nothing here
changes what Jev is asked or shown; the full `instructions` travel alongside the short label."""

import re

LABELS = {
    "move": "Which move?",
    "switch": "Switch out?",
    "switch_to": "Switch to which?",
    "run": "Run away?",
    "catch": "Throw a Poké Ball?",
    "heal": "Use a Potion?",
    "faint": "Faint before the next turn?",
    "explore": "What next?",
    "needs_heal": "Heal first?",
    "starter": "Which starter?",
    "prompt": "Answer YES?",
    "menu": "Which item?",
    "close": "Close the menu?",
}
"""A short introduction per question id. An id not here is shown with its underscores as spaces."""

PREDICTIONS = {"faint"}
"""Questions never applied by design: scored against the game later, not acted on."""

VERBS = {
    "battle": "presses",
    "explore": "walks",
    "prompt": "answers",
    "menu": "selects",
    "starter": "takes",
}

_MEMORY = re.compile(r"^(.*?)\s*\((new|visited|tried|talked already)\)$")


def present(decision: dict) -> dict:
    kind = decision.get("kind", "")
    summary = decision.get("state_summary") or {}
    questions = _questions(decision.get("questions") or {}, decision.get("answers") or {}, summary)
    action = decision.get("action", "")
    return {
        "actor": "jev" if decision.get("model") else "code",
        "kind": kind,
        "where": _where(kind, summary),
        "goal": _goal(summary),
        "questions": questions,
        "handoff": _handoff(kind, action),
        "reason": decision.get("fallback_reason", "") or "",
        "summary": _summary(decision, questions),
    }


def _questions(questions: dict, answers: dict, summary: dict) -> list[dict]:
    options_text = summary.get("options") if isinstance(summary.get("options"), dict) else {}
    rows = []
    for qid, q in questions.items():
        a = answers.get(qid)
        if not a:
            continue
        row = {
            "id": qid,
            "label": LABELS.get(qid, qid.replace("_", " ")),
            "instructions": q.get("instructions", ""),
            "primitive": a.get("primitive", q.get("primitive", "")),
            "role": "prediction" if qid in PREDICTIONS else ("applied" if a.get("applied") else "unused"),
        }
        if row["primitive"] == "choice":
            row["confidence"] = a.get("confidence")
            probabilities = a.get("probabilities") or {}
            row["options"] = [
                _option(oid, p, oid == a.get("choice"), options_text)
                for oid, p in sorted(probabilities.items(), key=lambda kv: -kv[1])
            ]
        else:
            row["yes"] = a.get("noul")
        rows.append(row)
    order = {"applied": 0, "unused": 1, "prediction": 2}
    rows.sort(key=lambda r: order[r["role"]])
    return rows


def _option(oid: str, p: float, chosen: bool, options_text: dict) -> dict:
    label, memory = oid, ""
    if oid in options_text:
        text = str(options_text[oid])
        m = _MEMORY.match(text)
        label, memory = (m.group(1), m.group(2)) if m else (text, "")
    return {"id": oid, "label": label, "memory": memory, "p": p, "chosen": chosen}


def _where(kind: str, summary: dict) -> str:
    if kind == "battle":
        ours, enemy = summary.get("our_pokemon") or {}, summary.get("enemy_pokemon") or {}
        battle_kind = (summary.get("battle") or {}).get("kind")
        whose = {"wild": "a wild ", "trainer": "a trainer's "}.get(battle_kind, "")
        parts = [_mon(ours), f"vs {whose}{_mon(enemy)}" if enemy else ""]
        return " ".join(p for p in parts if p)
    if kind == "explore":
        return f"on {summary['map']}" if summary.get("map") else ""
    if kind == "prompt":
        return f'the prompt "{summary["prompt"]}"' if summary.get("prompt") else ""
    if kind == "starter":
        return "at Oak's table"
    if kind == "menu":
        items = summary.get("menu_items") or []
        return "a menu: " + " / ".join(items) if items else ""
    return ""


def _mon(mon: dict) -> str:
    if not mon.get("name"):
        return ""
    return f"{mon['name']} L{mon['level']}" if mon.get("level") is not None else mon["name"]


def _goal(summary: dict) -> str:
    milestone = summary.get("milestone") or ""
    if milestone:
        standing = summary.get("standing_goal") or ""
        if not standing:
            return milestone
        return f"{milestone.rstrip('.')}. {standing}"
    return summary.get("goal", "") or ""


def _handoff(kind: str, action: str) -> str:
    verb = VERBS.get(kind, "does")
    if kind == "explore" and action.startswith("explore: "):
        action = action[len("explore: ") :]
    elif kind == "prompt" and action.startswith("answer "):
        action = action[len("answer ") :]
    elif kind == "menu" and action.startswith("select "):
        action = action[len("select ") :]
    elif kind == "starter" and action.startswith("take "):
        action = action[len("take ") :]
    return f"code {verb}: {action}"


def _summary(decision: dict, questions: list[dict]) -> str:
    action = decision.get("action", "")
    if action.startswith("explore: "):
        action = action[len("explore: ") :]
    if not decision.get("model"):
        reason = decision.get("fallback_reason") or ""
        return f"{action} · code: {reason}" if reason else f"{action} · code"
    applied = next((q for q in questions if q["role"] == "applied"), None)
    if applied is None:
        return action
    if applied["primitive"] == "choice":
        chosen = next((o for o in applied["options"] if o["chosen"]), None)
        return f"{action} · {_pct(chosen['p'])}" if chosen else action
    return f"{action} · yes {_pct(applied['yes'])}"


def _pct(p) -> str:
    return f"{round((p or 0) * 100)}%"
