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
