"""The only place thresholds and priorities live. Raw answers stay in the Decision, so a threshold
change never needs a new request."""

from jevplays.brain.decision import BattleAction

HEAL_THRESHOLD = 0.7
CATCH_THRESHOLD = 0.6
RUN_THRESHOLD = 0.7
SWITCH_THRESHOLD = 0.7


def _noul(answers: dict[str, dict], key: str) -> float:
    a = answers.get(key)
    return a["noul"] if a and a.get("type") == "noul" else 0.0


def choose_battle_action(answers: dict[str, dict], state_json: dict) -> tuple[BattleAction, list[str]]:
    """Ordered rules; the first that fires wins. Returns the action and the answer ids it used."""
    hp = state_json.get("our_pokemon", {}).get("hp")
    if _noul(answers, "heal") > HEAL_THRESHOLD and hp in ("low", "critical"):
        return BattleAction(kind="heal"), ["heal"]
    if _noul(answers, "catch") > CATCH_THRESHOLD:
        return BattleAction(kind="catch"), ["catch"]
    if _noul(answers, "run") > RUN_THRESHOLD:
        return BattleAction(kind="run"), ["run"]
    if _noul(answers, "switch") > SWITCH_THRESHOLD and "switch_to" in answers:
        return BattleAction(kind="switch", target=answers["switch_to"]["choice"]), ["switch", "switch_to"]
    return BattleAction(kind="move", move=answers["move"]["choice"]), ["move"]
