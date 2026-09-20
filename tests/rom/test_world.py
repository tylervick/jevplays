from jevplays.emulator import ram
from jevplays.emulator.pyboy import Emulator
from jevplays.state.events import flags_set


def test_route1_map_header_and_connections(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("route1"))
        m = emu.mem
        assert (m[ram.wCurMapWidth], m[ram.wCurMapHeight]) == (10, 18)
        assert m[ram.wNumberOfWarps] == 0
        flags = m[ram.wMapConnections]
        assert flags & (1 << ram.CONNECTION_BITS["north"]) and m[ram.CONNECTION_MAP_ADDRESSES["north"]] == 1
        assert flags & (1 << ram.CONNECTION_BITS["south"]) and m[ram.CONNECTION_MAP_ADDRESSES["south"]] == 0
        assert emu.rom(m[ram.wTilesetBank], ram.read_u16le(m, ram.wTilesetBlocksPtr)) is not None


def test_bedroom_warp_table_and_flags(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("overworld"))
        m = emu.mem
        assert m[ram.wNumberOfWarps] == 1
        y, x, _, dest = ram.read_bytes(m, ram.wWarpEntries, 4)
        assert (x, y, dest) == (7, 1, 37)
        assert flags_set(m) == frozenset()


def test_route1_flags(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("route1"))
        assert flags_set(emu.mem) >= {"got_starter", "battled_rival_in_oaks_lab", "oak_appeared_in_pallet"}
