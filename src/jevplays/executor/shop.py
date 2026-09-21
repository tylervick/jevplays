"""The two scripted counters: the nurse and the Mart clerk. Their screens are mechanical (a HEAL
menu, a quantity box), so code drives them; Jev decides whether to go there, not what to press."""

from jevplays.executor.dialog import answer_prompt, cursor_label, skip_dialog, wait_for, yes_no_open
from jevplays.executor.talk import talk_to
from jevplays.state.modes import Mode
from jevplays.state.snapshot import rows_of, snapshot

NURSE_TILE, NURSE_FACE = (3, 3), "up"
CLERK_TILE, CLERK_FACE = (2, 5), "left"

MAX_PER_TRIP = 99
"""The quantity box tops out at 99 of anything."""

SHELF_SCAN = 10
"""Presses down the shelf before giving up on finding an item. The longest early-game shelf is
six items plus CANCEL, so ten reaches every row and still ends."""


def _label_starts(rows, prefix: str) -> bool:
    label = cursor_label(rows)
    return label is not None and label.startswith(prefix)


def _exit_to_overworld(emu, max_iters: int = 12) -> bool:
    """Press B until the counter's menus are gone. Bounded: a counter's closing dialog is a
    handful of screens deep at most, and this must never spin forever waiting on a game that
    (for some other reason) never returns to the overworld."""
    for _ in range(max_iters):
        if snapshot(emu).mode is Mode.OVERWORLD:
            return True
        emu.press("b", settle=30)
    return snapshot(emu).mode is Mode.OVERWORLD


def heal_at_nurse(emu) -> bool:
    if not talk_to(emu, *NURSE_TILE, NURSE_FACE, patience=0):
        return False
    if not wait_for(emu, lambda rows: _label_starts(rows, "HEAL")):
        return False
    emu.press("a", settle=60)
    skip_dialog(emu, patience=60)
    _exit_to_overworld(emu)
    s = snapshot(emu)
    return bool(s.party) and s.party[0].hp == s.party[0].max_hp


def _list_is_open(rows) -> bool:
    """The BUY list is up: something is highlighted and the shelf's prices are on screen."""
    return cursor_label(rows) is not None and any("¥" in "".join(row) for row in rows)


def _bag_count(emu, name: str) -> int:
    return sum(item.quantity for item in snapshot(emu).bag if item.name == name)


def _buy(emu, *, label: str, bag_name: str, count: int) -> int:
    """Buy `count` of the shelf item whose label starts with `label`. Returns how many are in the
    bag afterwards, so the caller compares it with what was there before rather than trusting a
    boolean.

    A shop that does not stock the item is an ordinary outcome, not an error: the scan runs out,
    the macro backs out to the overworld, and the count comes back unchanged. That is what keeps
    an unverified inventory (the Pewter shelf, #27) from needing to be guessed at here.
    """
    if count <= 0:
        return _bag_count(emu, bag_name)
    count = min(count, MAX_PER_TRIP)
    if not talk_to(emu, *CLERK_TILE, CLERK_FACE, patience=0):
        return _bag_count(emu, bag_name)
    if not wait_for(emu, lambda rows: _label_starts(rows, "BUY")):
        return _bag_count(emu, bag_name)
    emu.press("a", settle=60)
    if not wait_for(emu, _list_is_open):
        return _bag_count(emu, bag_name)
    for _ in range(SHELF_SCAN):
        if _label_starts(rows_of(emu.tilemap()), label):
            break
        emu.press("down", settle=16)
    else:
        _exit_to_overworld(emu)
        return _bag_count(emu, bag_name)
    emu.press("a", settle=60)
    if not wait_for(emu, lambda rows: any("×0" in "".join(row) for row in rows)):
        return _bag_count(emu, bag_name)
    for _ in range(max(0, count - 1)):
        emu.press("up", settle=16)
    emu.press("a", settle=60)
    if wait_for(emu, yes_no_open, frames=300):
        answer_prompt(emu, True)
    # Not skip_dialog: after a purchase the "Thank you!" arrow-dialog returns to the item list
    # with its "Take your time." flavor text still on screen, which is not dialog to skip through
    # -- skip_dialog's idle nudge would read it as stuck text and press A on the highlighted item
    # again, buying more. Wait for the arrow-dismissal to land back on that menu instead.
    wait_for(emu, lambda rows: cursor_label(rows) is not None, frames=300)
    _exit_to_overworld(emu)
    return _bag_count(emu, bag_name)


def buy_pokeballs(emu, count: int) -> int:
    return _buy(emu, label="POKé BALL", bag_name="POKE BALL", count=count)


def buy_potions(emu, count: int) -> int:
    return _buy(emu, label="POTION", bag_name="POTION", count=count)
