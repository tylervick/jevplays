"""GameState: everything the loop, the brain, and the dashboard know about the game right now.

snapshot() is a pure function of the emulator's memory. It never presses a button and never
keeps state between calls, which is what lets the brain be tested on recorded snapshots and
what keeps inferred state (later milestones) separate from observed facts (this).
"""

from dataclasses import asdict, dataclass
from typing import Protocol

from jevplays.emulator import ram
from jevplays.emulator.text import ARROW, NON_TEXT, decode_cells, has_text, row_text
from jevplays.state.events import flags_set
from jevplays.state.modes import DIALOG_ROWS, Mode, detect, is_blank
from jevplays.state.names import item_name, map_name, move_data, species_name, trainer_class_name, type_name


class EmulatorLike(Protocol):
    @property
    def mem(self) -> ram.Memory: ...

    def tilemap(self) -> bytes: ...


@dataclass(frozen=True)
class Move:
    name: str
    type: str
    power: int
    pp: int
    max_pp: int


@dataclass(frozen=True)
class Mon:
    name: str
    nickname: str
    level: int
    types: tuple[str, ...]
    hp: int
    max_hp: int
    status: str
    moves: tuple[Move, ...]


@dataclass(frozen=True)
class Battle:
    kind: str
    trainer_class: str | None


@dataclass(frozen=True)
class Sprite:
    slot: int
    picture: int
    x: int
    y: int


@dataclass(frozen=True)
class BagItem:
    name: str
    quantity: int


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
    bag: tuple[BagItem, ...]
    in_battle: bool
    text: str
    """The dialog box's text, joined into one line, without the ▼ arrow."""
    menu_items: tuple[str, ...]
    cursor: int | None
    """Index of the highlighted item while a menu or prompt is open."""
    party: tuple[Mon, ...]
    active: Mon | None
    """The battle Pokémon while in battle."""
    active_slot: int | None
    """Index into `party` of the Pokémon currently out in battle. None outside battle."""
    enemy: Mon | None
    battle: Battle | None
    flags: frozenset[str]
    sprites: tuple[Sprite, ...]
    map_size: tuple[int, int]

    def to_dict(self) -> dict:
        d = _listify(asdict(self))
        d["mode"] = str(self.mode)
        d["flags"] = sorted(self.flags)
        return d


def _listify(value):
    if isinstance(value, dict):
        return {k: _listify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_listify(v) for v in value]
    return value


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


# In-battle records (wBattleMon*, wEnemyMon*) are laid out differently from party records:
# the offsets below are relative to the species byte.
_BATTLE_OFFSETS = dict(hp=1, status=4, type1=5, type2=6, moves=8, level=14, max_hp=15, pp=25)
_PARTY_OFFSETS = dict(
    hp=ram.MON_HP,
    status=ram.MON_STATUS,
    type1=ram.MON_TYPE1,
    type2=ram.MON_TYPE2,
    moves=ram.MON_MOVES,
    level=ram.MON_LEVEL,
    max_hp=ram.MON_MAX_HP,
    pp=ram.MON_PP,
)


def read_mon(mem: ram.Memory, base: int, nick_addr: int, *, in_battle_layout: bool) -> Mon:
    off = _BATTLE_OFFSETS if in_battle_layout else _PARTY_OFFSETS
    t1, t2 = mem[base + off["type1"]], mem[base + off["type2"]]
    types = (type_name(t1),) if t1 == t2 else (type_name(t1), type_name(t2))
    moves = []
    for i in range(4):
        move_id = mem[base + off["moves"] + i]
        data = move_data(move_id)
        if move_id == 0 or data is None:
            continue
        moves.append(
            Move(
                name=data.name,
                type=data.type,
                power=data.power,
                pp=ram.pp_current(mem[base + off["pp"] + i]),
                max_pp=data.pp,
            )
        )
    return Mon(
        name=species_name(mem[base]),
        nickname=ram.read_name(mem, nick_addr),
        level=mem[base + off["level"]],
        types=types,
        hp=ram.read_u16(mem, base + off["hp"]),
        max_hp=ram.read_u16(mem, base + off["max_hp"]),
        status=ram.status_name(mem[base + off["status"]]),
        moves=tuple(moves),
    )


def read_party(mem: ram.Memory) -> tuple[Mon, ...]:
    """The party, stopping at the first slot whose species byte is 0.

    Mid-catch, the game bumps wPartyCount before it writes the new record, so for one frame
    the last slot up to that count is a species-0 placeholder. Stopping there (rather than
    skipping a zero wherever it appears) never shifts the index of a real, already-written
    slot, which is what active_slot (from wPlayerMonNumber) indexes into.
    """
    count = min(mem[ram.wPartyCount], 6)
    mons = []
    for i in range(count):
        base = ram.wPartyMons + i * ram.PARTY_MON_SIZE
        if mem[base] == 0:
            break
        mons.append(
            read_mon(
                mem,
                base,
                ram.wPartyMonNicks + i * ram.NAME_LENGTH,
                in_battle_layout=False,
            )
        )
    return tuple(mons)


def read_bag(mem: ram.Memory) -> tuple[BagItem, ...]:
    items = []
    addr = ram.wBagItems
    for _ in range(min(mem[ram.wNumBagItems], 20)):
        item_id = mem[addr]
        if item_id in (0, ram.BAG_END):  # 0 is an empty slot (a fake or a fresh game), 0xFF the terminator
            break
        items.append(BagItem(name=item_name(item_id), quantity=mem[addr + 1]))
        addr += 2
    return tuple(items)


def read_sprites(mem: ram.Memory) -> tuple[Sprite, ...]:
    out = []
    for slot in range(1, ram.SPRITE_SLOTS + 1):
        picture = mem[ram.wSpriteStateData1 + ram.SPRITE_SLOT_SIZE * slot]
        if picture == 0:
            continue
        base = ram.wSpriteStateData2 + ram.SPRITE_SLOT_SIZE * slot
        out.append(
            Sprite(
                slot=slot,
                picture=picture,
                x=mem[base + 5] - ram.SPRITE_COORD_OFFSET,
                y=mem[base + 4] - ram.SPRITE_COORD_OFFSET,
            )
        )
    return tuple(out)


def snapshot(emu: EmulatorLike) -> GameState:
    mem = emu.mem
    raw = emu.tilemap()
    rows = rows_of(raw)
    in_battle = mem[ram.wIsInBattle] != 0
    mode = detect(rows, in_battle=in_battle, blank=is_blank(raw))
    map_id = mem[ram.wCurMap]
    party = read_party(mem)
    battle = active = enemy = active_slot = None
    if in_battle:
        kind = "trainer" if mem[ram.wIsInBattle] == 2 else "wild"
        trainer = trainer_class_name(mem[ram.wTrainerClass]) if kind == "trainer" else None
        battle = Battle(kind=kind, trainer_class=trainer)
        active = read_mon(mem, ram.wBattleMonSpecies, ram.wBattleMonNick, in_battle_layout=True)
        enemy = read_mon(mem, ram.wEnemyMonSpecies, ram.wEnemyMonNick, in_battle_layout=True)
        active_slot = mem[ram.wPlayerMonNumber]
        if active_slot >= len(party):
            active_slot = 0
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
        bag=read_bag(mem),
        in_battle=in_battle,
        text=dialog_text(rows),
        menu_items=menu_items(rows, mode, mem),
        cursor=mem[ram.wCurrentMenuItem] if mode in (Mode.MENU, Mode.PROMPT) else None,
        party=party,
        active=active,
        active_slot=active_slot,
        enemy=enemy,
        battle=battle,
        flags=flags_set(mem),
        sprites=read_sprites(mem),
        map_size=(mem[ram.wCurMapWidth] * 2, mem[ram.wCurMapHeight] * 2),
    )
