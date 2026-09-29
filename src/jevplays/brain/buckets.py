"""Numbers to words. Jev is weak at arithmetic and strong at judgment, so code does the math."""


def hp_bucket(hp: int, max_hp: int) -> str:
    if max_hp <= 0 or hp <= 0:
        return "critical"
    fraction = hp / max_hp
    if fraction >= 1:
        return "full"
    if fraction > 0.6:
        return "healthy"
    if fraction > 0.3:
        return "hurt"
    if fraction > 0.1:
        return "low"
    return "critical"


def pp_bucket(pp: int) -> str:
    if pp <= 0:
        return "out"
    if pp <= 5:
        return "low"
    return "plenty"


def power_bucket(power: int) -> str:
    if power <= 0:
        return "none"
    if power < 50:
        return "weak"
    if power < 80:
        return "medium"
    return "strong"


def money_bucket(money: int) -> str:
    if money < 500:
        return "broke"
    if money < 2000:
        return "some"
    if money < 10000:
        return "comfortable"
    return "rich"


def quantity_bucket(n: int) -> str:
    if n <= 0:
        return "none"
    if n <= 3:
        return "few"
    return "plenty"


def readiness_bucket(level: int, expects: int | None) -> str | None:
    """How the lead measures up to the fight the milestone is walking into, or None when the
    milestone has no fight worth sizing up.

    The comparison is arithmetic, so it belongs here rather than in the model: Jev is shown the
    lead's level and the milestone's description, and nothing in either says a level-9 Charmander
    loses to a level-14 Onix (#42). The bands are deliberately coarse -- two levels of slack
    before "close" becomes "ready" -- because the point is a judgment, not a gate.
    """
    if expects is None:
        return None
    if level >= expects:
        return "ready"
    if level >= expects - 2:
        return "close"
    return "outmatched"


PARTY_GOAL = 3
"""The party the standing goal asks for (`goals.STANDING_CLAUSE`: "Build a party of three")."""
_COUNT_WORDS = {1: "one", 2: "two", 3: "three"}


def party_size_bucket(size: int) -> str | None:
    """How far the party is towards the standing goal's three, as a fact ("one of three"), or None
    with no party. Counting against the goal is arithmetic, so code says it: every measured run
    reached Brock with one Pokémon while the goal asked for three, and nothing Jev saw put the two
    side by side (#110)."""
    if size <= 0:
        return None
    return f"{_COUNT_WORDS[min(size, PARTY_GOAL)]} of {_COUNT_WORDS[PARTY_GOAL]}"
