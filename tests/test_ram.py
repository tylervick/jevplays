from jevplays.emulator import ram
from jevplays.emulator.text import encode
from tests.support import FakeMemory, write_tilemap


def test_addresses_are_the_documented_wram_locations():
    assert ram.wTileMap == 0xC3A0
    assert ram.TILEMAP_SIZE == 360
    assert ram.wCurrentMenuItem == 0xCC26
    assert ram.wMaxMenuItem == 0xCC28
    assert ram.wFontLoaded == 0xCFC4
    assert ram.wIsInBattle == 0xD057
    assert ram.wPlayerName == 0xD158
    assert ram.wPartyCount == 0xD163
    assert ram.wPlayerMoney == 0xD347
    assert ram.wObtainedBadges == 0xD356
    assert ram.wCurMap == 0xD35E
    assert (ram.wYCoord, ram.wXCoord) == (0xD361, 0xD362)


def test_bcd_to_int_reads_big_endian_packed_decimal():
    assert ram.bcd_to_int([0x00, 0x30, 0x00]) == 3000
    assert ram.bcd_to_int([0x99, 0x99, 0x99]) == 999999
    assert ram.bcd_to_int([0x00, 0x00, 0x00]) == 0


def test_read_name_decodes_until_terminator():
    mem = FakeMemory()
    mem[ram.wPlayerName : ram.wPlayerName + 4] = encode("RED") + [ram.TERMINATOR]
    assert ram.read_name(mem, ram.wPlayerName) == "RED"


def test_read_tilemap_returns_the_whole_buffer():
    mem = FakeMemory()
    write_tilemap(mem, ["▶NEW GAME"])
    raw = ram.read_tilemap(mem)
    assert len(raw) == 360
    assert raw[0] == 0xED


def test_battle_and_party_addresses():
    assert ram.wBattleMonSpecies == 0xD014 and ram.wBattleMonHP == 0xD015 and ram.wBattleMonPP == 0xD02D
    assert ram.wEnemyMonSpecies == 0xCFE5 and ram.wEnemyMonHP == 0xCFE6 and ram.wEnemyMonLevel == 0xCFF3
    assert ram.wPartyMons == 0xD16B and ram.PARTY_MON_SIZE == 0x2C and ram.wPartyMonNicks == 0xD2B5
    assert (ram.MON_HP, ram.MON_MOVES, ram.MON_PP, ram.MON_LEVEL, ram.MON_MAX_HP) == (1, 8, 29, 33, 34)


def test_read_u16_is_big_endian():
    mem = FakeMemory()
    mem[0xD015] = 0x01
    mem[0xD016] = 0x2C
    assert ram.read_u16(mem, 0xD015) == 300


def test_status_name_and_pp_current():
    assert ram.status_name(0) == "none"
    assert ram.status_name(0b0000_0011) == "asleep"
    assert ram.status_name(0b0000_1000) == "poisoned"
    assert ram.status_name(0b0001_0000) == "burned"
    assert ram.status_name(0b0010_0000) == "frozen"
    assert ram.status_name(0b0100_0000) == "paralyzed"
    assert ram.pp_current(35) == 35
    assert ram.pp_current(0b1100_0000 | 20) == 20
