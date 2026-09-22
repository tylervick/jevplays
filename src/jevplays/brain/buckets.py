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


def supplies_bucket(*, potions: int, money: int, price: int, expects: int | None) -> str | None:
    """What the bag holds for the fight the milestone is walking into, or None when the milestone
    has no fight to stock up for.

    Sibling of `readiness_bucket`: that one sizes up the lead, this one sizes up the bag. Jev is
    shown `bag` and the milestone's description, and nothing in either says that a Potion is what
    a gym fight is for, or that a shelf sells one for what we are carrying (#52). Both halves of
    that are arithmetic, so both belong here.

    The word is present whenever there is a fight ahead and says which case we are in, rather
    than appearing only when the bag is bare: a key whose mere presence means "go shopping" is a
    recommendation, and what Jev is shown is meant to be facts.
    """
    if expects is None:
        return None
    if potions > 0:
        return "stocked"
    return "none, affordable" if money >= price else "none, unaffordable"
