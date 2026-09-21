"""The only place thresholds and priorities live. Raw answers stay in the Decision, so a threshold
change never needs a new request."""

from jevplays.brain.decision import BattleAction

HEAL_THRESHOLD = 0.7
CATCH_THRESHOLD = 0.6
RUN_THRESHOLD = 0.7
SWITCH_THRESHOLD = 0.7
HEAL_FIRST_THRESHOLD = 0.7
PROMPT_YES_THRESHOLD = 0.5
MENU_CLOSE_THRESHOLD = 0.6
NEVER_NICKNAME = True


def _noul(answers: dict[str, dict], key: str) -> float:
    a = answers.get(key)
    return a["noul"] if a and a.get("type") == "noul" else 0.0


def choose_battle_action(answers: dict[str, dict], state_json: dict) -> tuple[BattleAction | None, list[str]]:
    """Ordered rules; the first that fires wins. Returns the action and the answer ids it used.

    Total: when nothing else fires and there is no usable "move" choice answer either, returns
    (None, []) rather than raising, so the caller decides how to fall back."""
    hp = state_json.get("our_pokemon", {}).get("hp")
    if _noul(answers, "heal") > HEAL_THRESHOLD and hp in ("low", "critical"):
        return BattleAction(kind="heal"), ["heal"]
    if _noul(answers, "catch") > CATCH_THRESHOLD:
        return BattleAction(kind="catch"), ["catch"]
    if _noul(answers, "run") > RUN_THRESHOLD:
        return BattleAction(kind="run"), ["run"]
    if _noul(answers, "switch") > SWITCH_THRESHOLD and answers.get("switch_to", {}).get("type") == "choice":
        # switch_to's choice is a bench label now, not a species name; slot stays None here —
        # resolving a label to a party index is the caller's job, via brain.battle.bench_slots.
        return BattleAction(kind="switch", target=answers["switch_to"]["choice"]), ["switch", "switch_to"]
    if answers.get("move", {}).get("type") == "choice":
        return BattleAction(kind="move", move=answers["move"]["choice"]), ["move"]
    return None, []


def choose_explore(answers: dict[str, dict], option_ids: list[str]) -> tuple[str, list[str]]:
    """The option to take next, and the answer ids used. Heals first when `needs_heal` clears
    the threshold and a `heal` option is on offer; otherwise the `explore` choice, so long as it
    names an option actually on the list. When it does not (or there is no usable `explore`
    answer at all), falls back to `milestone` when that is on offer, else the first option --
    code decided that, not Jev, so `used` comes back empty."""
    if _noul(answers, "needs_heal") > HEAL_FIRST_THRESHOLD and "heal" in option_ids:
        used = ["needs_heal"] if "needs_heal" in answers else []
        return "heal", used
    explore = answers.get("explore")
    if explore and explore.get("type") == "choice" and explore["choice"] in option_ids:
        return explore["choice"], ["explore"]
    if "milestone" in option_ids:
        return "milestone", []
    return (option_ids[0] if option_ids else ""), []


def choose_prompt(answers: dict[str, dict], text: str) -> tuple[bool, list[str]]:
    """Whether to answer YES, and the answer ids used. Never asks when the on-screen text is
    about nicknaming and the policy says never to nickname."""
    if NEVER_NICKNAME and "nickname" in text.lower():
        return False, []
    used = ["prompt"] if "prompt" in answers else []
    return _noul(answers, "prompt") > PROMPT_YES_THRESHOLD, used


def choose_menu(answers: dict[str, dict]) -> tuple[str | None, list[str]]:
    """The menu item to select (None to close), and the answer ids used."""
    if _noul(answers, "close") > MENU_CLOSE_THRESHOLD:
        used = ["close"] if "close" in answers else []
        return None, used
    menu = answers.get("menu")
    if menu and menu.get("type") == "choice":
        return menu["choice"], ["menu"]
    return None, []
