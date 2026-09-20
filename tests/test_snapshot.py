from jevplays.emulator import ram
from jevplays.emulator.text import encode
from jevplays.state.modes import Mode
from jevplays.state.snapshot import BagItem, Battle, GameState, Mon, Move, dialog_text, menu_items, snapshot
from tests.support import FakeEmulator, FakeMemory, rows_from, write_mon


def bedroom(emu: FakeEmulator) -> None:
    emu.mem[ram.wCurMap] = 38
    emu.mem[ram.wXCoord] = 3
    emu.mem[ram.wYCoord] = 7
    emu.mem[ram.wPlayerName : ram.wPlayerName + 4] = encode("RED") + [ram.TERMINATOR]
    emu.mem[ram.wPlayerMoney : ram.wPlayerMoney + 3] = [0x00, 0x30, 0x00]
    emu.mem[ram.wObtainedBadges] = 0b00000101
    emu.mem[ram.wNumBagItems] = 2


def test_snapshot_in_the_overworld():
    emu = FakeEmulator()
    bedroom(emu)
    state = snapshot(emu)
    assert isinstance(state, GameState)
    assert state.mode is Mode.OVERWORLD
    assert state.map_id == 38 and state.map == "Red's House 2F"
    assert state.tile == (3, 7)
    assert state.player_name == "RED"
    assert state.money == 3000
    assert state.badges == 2
    assert state.bag_count == 2
    assert state.party_count == 0
    assert state.in_battle is False
    assert state.text == ""
    assert state.menu_items == ()
    assert state.cursor is None


def test_snapshot_reads_menu_items_and_cursor():
    emu = FakeEmulator()
    bedroom(emu)
    emu.set_rows(
        [
            "····················",
            "···········        ·",
            "···········▶POKéMON·",
            "···········        ·",
            "··········· ITEM   ·",
            "···········        ·",
            "··········· RED    ·",
            "···········        ·",
            "··········· SAVE   ·",
            "···········        ·",
            "··········· OPTION ·",
            "···········        ·",
            "··········· EXIT   ·",
        ]
    )
    emu.mem[ram.wCurrentMenuItem] = 3
    emu.mem[ram.wTopMenuItemY] = 2
    emu.mem[ram.wTopMenuItemX] = 11
    emu.mem[ram.wMaxMenuItem] = 6  # the real game overcounts the START menu by one
    state = snapshot(emu)
    assert state.mode is Mode.MENU
    assert state.menu_items == ("POKéMON", "ITEM", "RED", "SAVE", "OPTION", "EXIT")
    assert state.cursor == 3


def test_menu_items_ignore_boxes_outside_the_menu():
    emu = FakeEmulator()
    bedroom(emu)
    emu.set_rows(
        [
            "···········¥3000····",  # a money box, not part of the menu's scanned rows
            "····················",
            "···········▶POKéMON·",
            "····················",
            "··········· ITEM····",
            "····················",
            "··········· RED·····",
            "····················",
            "··········· SAVE····",
            "····················",
            "··········· OPTION··",
            "····················",
            "··········· EXIT····",
            "····················",
            "Wild PIDGEY··········",  # a dialog line at the overcounted 7th row
        ]
    )
    emu.mem[ram.wTopMenuItemY] = 2
    emu.mem[ram.wTopMenuItemX] = 11
    emu.mem[ram.wMaxMenuItem] = 6  # overcounts: count == 7, so row 14 is also scanned
    state = snapshot(emu)
    assert state.menu_items == ("POKéMON", "ITEM", "RED", "SAVE", "OPTION", "EXIT")


def test_snapshot_reads_dialog_text_without_the_arrow():
    emu = FakeEmulator()
    bedroom(emu)
    emu.set_rows(
        [""] * 12
        + [
            "····················",
            "·                  ·",
            "·Hello there!      ·",
            "·                  ·",
            "·Welcome to the   ▼·",
            "····················",
        ]
    )
    state = snapshot(emu)
    assert state.mode is Mode.DIALOG
    assert state.text == "Hello there! Welcome to the"


def test_prompt_items_are_yes_and_no():
    rows = rows_from(["·▶YES·", "·    ·", "· NO ·"])
    assert menu_items(rows, Mode.PROMPT, FakeMemory()) == ("YES", "NO")


def test_dialog_text_joins_only_the_text_rows():
    rows = rows_from([""] * 13 + ["·First, what is    ·", "·                  ·", "·your name?        ·"])
    assert dialog_text(rows) == "First, what is your name?"


def test_to_dict_is_json_ready():
    emu = FakeEmulator()
    bedroom(emu)
    d = snapshot(emu).to_dict()
    assert d["mode"] == "overworld"
    assert d["tile"] == [3, 7]
    assert d["menu_items"] == []


def charmander(emu, *, in_battle=False):
    write_mon(
        emu.mem,
        ram.wPartyMons,
        ram.wPartyMonNicks,
        species=176,
        level=5,
        hp=19,
        max_hp=19,
        types=(20, 20),
        moves=(10, 45),
        pps=(35, 40),
        nickname="CHARMANDER",
    )
    emu.mem[ram.wPartyCount] = 1
    if in_battle:
        write_mon(
            emu.mem,
            ram.wBattleMonSpecies,
            ram.wBattleMonNick,
            species=176,
            level=5,
            hp=12,
            max_hp=19,
            types=(20, 20),
            moves=(10, 45),
            pps=(34, 40),
            nickname="CHARMANDER",
            layout="battle",
        )
        write_mon(
            emu.mem,
            ram.wEnemyMonSpecies,
            ram.wEnemyMonNick,
            species=177,
            level=5,
            hp=20,
            max_hp=20,
            types=(21, 21),
            moves=(33, 39),
            pps=(35, 30),
            nickname="SQUIRTLE",
            layout="battle",
        )


def test_party_is_parsed_from_the_party_records():
    emu = FakeEmulator()
    bedroom(emu)
    charmander(emu)
    state = snapshot(emu)
    assert state.party == (
        Mon(
            name="CHARMANDER",
            nickname="CHARMANDER",
            level=5,
            types=("Fire",),
            hp=19,
            max_hp=19,
            status="none",
            moves=(
                Move(name="SCRATCH", type="Normal", power=40, pp=35, max_pp=35),
                Move(name="GROWL", type="Normal", power=0, pp=40, max_pp=40),
            ),
        ),
    )
    assert state.active is None and state.enemy is None and state.battle is None


def test_battle_fields_when_in_a_trainer_battle():
    emu = FakeEmulator()
    bedroom(emu)
    charmander(emu, in_battle=True)
    emu.mem[ram.wIsInBattle] = 2
    emu.mem[ram.wTrainerClass] = 25
    emu.set_rows([""] * 14 + ["·       ·▶FIGHT PK·", "", "·       · ITEM RUN·"])
    state = snapshot(emu)
    assert state.mode is Mode.BATTLE_MENU
    assert state.battle == Battle(kind="trainer", trainer_class="RIVAL1")
    assert state.active.hp == 12 and state.active.moves[0].pp == 34
    assert state.enemy.name == "SQUIRTLE" and state.enemy.types == ("Water",)


def test_wild_battle_has_no_trainer():
    emu = FakeEmulator()
    bedroom(emu)
    charmander(emu, in_battle=True)
    emu.mem[ram.wIsInBattle] = 1
    assert snapshot(emu).battle == Battle(kind="wild", trainer_class=None)


def test_bag_items_are_parsed_until_the_terminator():
    emu = FakeEmulator()
    bedroom(emu)
    emu.mem[ram.wNumBagItems] = 2
    emu.mem[ram.wBagItems : ram.wBagItems + 5] = [4, 5, 20, 2, ram.BAG_END]  # 5 POKE BALL, 2 POTION
    state = snapshot(emu)
    assert state.bag == (BagItem(name="POKE BALL", quantity=5), BagItem(name="POTION", quantity=2))
    assert state.bag_count == 2


def test_to_dict_serializes_nested_records():
    emu = FakeEmulator()
    bedroom(emu)
    charmander(emu)
    d = snapshot(emu).to_dict()
    assert d["party"][0]["moves"][0] == {
        "name": "SCRATCH",
        "type": "Normal",
        "power": 40,
        "pp": 35,
        "max_pp": 35,
    }
    assert d["active"] is None and d["bag"] == []
