"""The two scripted counters: the nurse and the Mart clerk. Their screens are mechanical (a HEAL
menu, a quantity box), so code drives them; Jev decides whether to go there, not what to press."""

from jevplays.executor.dialog import answer_prompt, cursor_label, skip_dialog, yes_no_open
from jevplays.executor.talk import talk_to
from jevplays.state.snapshot import rows_of, snapshot

NURSE_TILE, NURSE_FACE = (3, 3), "up"
CLERK_TILE, CLERK_FACE = (2, 5), "left"


def wait_for(emu, predicate, frames: int = 900) -> bool:
    for _ in range(0, frames, 10):
        rows = rows_of(emu.tilemap())
        if predicate(rows):
            return True
        if rows[16][18] == "▼":
            emu.press("a", settle=30)
        else:
            emu.tick(10)
    return False


def _label_starts(rows, prefix: str) -> bool:
    label = cursor_label(rows)
    return label is not None and label.startswith(prefix)


def heal_at_nurse(emu) -> bool:
    talk_to(emu, *NURSE_TILE, NURSE_FACE, patience=0)
    if not wait_for(emu, lambda rows: _label_starts(rows, "HEAL")):
        return False
    emu.press("a", settle=60)
    skip_dialog(emu, patience=60)
    s = snapshot(emu)
    return bool(s.party) and s.party[0].hp == s.party[0].max_hp


def buy_pokeballs(emu, count: int) -> int:
    talk_to(emu, *CLERK_TILE, CLERK_FACE, patience=0)
    if not wait_for(emu, lambda rows: _label_starts(rows, "BUY")):
        return _balls(emu)
    emu.press("a", settle=60)
    if not wait_for(
        emu, lambda rows: cursor_label(rows) is not None and "BALL" in "".join("".join(r) for r in rows)
    ):
        return _balls(emu)
    for _ in range(6):
        if _label_starts(rows_of(emu.tilemap()), "POKé BALL"):
            break
        emu.press("down", settle=16)
    emu.press("a", settle=60)
    if not wait_for(emu, lambda rows: any("×0" in "".join(r) for r in rows)):
        return _balls(emu)
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
    emu.press("b", settle=30)
    emu.press("b", settle=30)
    emu.press("b", settle=30)
    return _balls(emu)


def _balls(emu) -> int:
    return sum(item.quantity for item in snapshot(emu).bag if item.name == "POKE BALL")
