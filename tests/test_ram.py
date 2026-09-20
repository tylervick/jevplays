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
