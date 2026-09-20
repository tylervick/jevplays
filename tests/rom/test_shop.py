from jevplays.emulator.pyboy import Emulator
from jevplays.executor.shop import buy_pokeballs, heal_at_nurse
from jevplays.state.snapshot import snapshot


def test_heal_at_the_viridian_nurse(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("viridian_center"))
        assert heal_at_nurse(emu)
        s = snapshot(emu)
        assert s.party[0].hp == s.party[0].max_hp


def test_buy_three_pokeballs(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("mart_dex"))
        before = snapshot(emu).money
        assert buy_pokeballs(emu, 3) >= 3
        s = snapshot(emu)
        assert any(item.name == "POKE BALL" and item.quantity >= 3 for item in s.bag)
        assert s.money == before - 600
