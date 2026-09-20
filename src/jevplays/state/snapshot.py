"""GameState: everything the loop, the brain, and the dashboard know about the game right now.

snapshot() is a pure function of the emulator's memory. It never presses a button and never
keeps state between calls, which is what lets the brain be tested on recorded snapshots and
what keeps inferred state (later milestones) separate from observed facts (this).
"""

from dataclasses import asdict, dataclass
from typing import Protocol

from jevplays.emulator import ram
from jevplays.emulator.text import ARROW, NON_TEXT, decode_cells, has_text, row_text
from jevplays.state.modes import DIALOG_ROWS, Mode, detect, is_blank
from jevplays.state.names import map_name


class EmulatorLike(Protocol):
    @property
    def mem(self) -> ram.Memory: ...

    def tilemap(self) -> bytes: ...


@dataclass(frozen=True)
class GameState:
    mode: Mode
    map_id: int
    map: str
    tile: tuple[int, int]
    """(x, y) on the current map. For the executor only; never sent to Jev."""
    player_name: str
    party_count: int
    badges: int
    money: int
    bag_count: int
    in_battle: bool
    text: str
    """The dialog box's text, joined into one line, without the ▼ arrow."""
    menu_items: tuple[str, ...]
    cursor: int | None
    """Index of the highlighted item while a menu or prompt is open."""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["mode"] = str(self.mode)
        d["tile"] = list(self.tile)
        d["menu_items"] = list(self.menu_items)
        return d


def rows_of(raw: bytes) -> list[list[str]]:
    return [
        decode_cells(raw[r * ram.TILEMAP_WIDTH : (r + 1) * ram.TILEMAP_WIDTH])
        for r in range(ram.TILEMAP_HEIGHT)
    ]


def dialog_text(rows: list[list[str]]) -> str:
    lines = []
    for r in DIALOG_ROWS:
        cells = [c for c in rows[r] if c != ARROW]
        line = row_text(cells).strip(" " + NON_TEXT)
        if line:
            lines.append(line)
    return " ".join(lines)


def menu_items(rows: list[list[str]], mode: Mode, mem: ram.Memory) -> tuple[str, ...]:
    """The labels of an open menu, top to bottom, read from RAM's menu geometry.

    wMaxMenuItem can overcount by one (the START menu reports 6 for its 6 items, i.e. one past
    the last index), so the scan also stops at the first row with nothing to its right.
    """
    if mode is Mode.PROMPT:
        return ("YES", "NO")
    if mode is not Mode.MENU:
        return ()
    top = mem[ram.wTopMenuItemY]
    col = mem[ram.wTopMenuItemX]
    count = mem[ram.wMaxMenuItem] + 1
    items = []
    for i in range(count):
        r = top + 2 * i
        if r >= ram.TILEMAP_HEIGHT:
            break
        cells = rows[r][col + 1 :]
        if not has_text(cells):
            break
        items.append(row_text(cells).strip(" " + NON_TEXT))
    return tuple(items)


def snapshot(emu: EmulatorLike) -> GameState:
    mem = emu.mem
    raw = emu.tilemap()
    rows = rows_of(raw)
    in_battle = mem[ram.wIsInBattle] != 0
    mode = detect(rows, in_battle=in_battle, blank=is_blank(raw))
    map_id = mem[ram.wCurMap]
    return GameState(
        mode=mode,
        map_id=map_id,
        map=map_name(map_id),
        tile=(mem[ram.wXCoord], mem[ram.wYCoord]),
        player_name=ram.read_name(mem, ram.wPlayerName),
        party_count=mem[ram.wPartyCount],
        badges=mem[ram.wObtainedBadges].bit_count(),
        money=ram.bcd_to_int(ram.read_bytes(mem, ram.wPlayerMoney, 3)),
        bag_count=mem[ram.wNumBagItems],
        in_battle=in_battle,
        text=dialog_text(rows),
        menu_items=menu_items(rows, mode, mem),
        cursor=mem[ram.wCurrentMenuItem] if mode in (Mode.MENU, Mode.PROMPT) else None,
    )
