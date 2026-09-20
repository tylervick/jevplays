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
    assert ram.wPlayerMonNumber == 0xCC2F
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


def test_map_and_sprite_addresses():
    assert ram.wOverworldMap == 0xC6E8 and ram.MAP_BORDER_BLOCKS == 3
    assert (ram.wCurMapWidth, ram.wCurMapHeight) == (0xD369, 0xD368)
    assert ram.wNumberOfWarps == 0xD3AE and ram.wWarpEntries == 0xD3AF and ram.WARP_LAST_MAP == 0xFF
    assert ram.CONNECTION_MAP_ADDRESSES["north"] == 0xD371 and ram.CONNECTION_BITS["north"] == 3
    assert (ram.wTilesetBank, ram.wTilesetBlocksPtr, ram.wTilesetCollisionPtr, ram.wGrassTile) == (
        0xD52B,
        0xD52C,
        0xD530,
        0xD535,
    )
    assert (
        ram.wSpriteStateData1 == 0xC100 and ram.wSpriteStateData2 == 0xC200 and ram.SPRITE_COORD_OFFSET == 4
    )


def test_read_u16le_and_flag_bit():
    mem = FakeMemory()
    mem[0xD52C] = 0x34
    mem[0xD52D] = 0x12
    assert ram.read_u16le(mem, 0xD52C) == 0x1234
    mem[ram.wEventFlags + 4] = 0b0000_0100  # bit index 34 = byte 4, bit 2
    assert ram.flag_bit(mem, 34) is True
    assert ram.flag_bit(mem, 35) is False


def test_fake_memory_serves_rom_reads():
    mem = FakeMemory()
    mem.rom[(25, 0x4000)] = 0x77
    assert mem[25, 0x4000] == 0x77
    assert mem[25, 0x4001] == 0
