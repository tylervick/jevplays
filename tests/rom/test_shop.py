from jevplays.emulator.pyboy import Emulator
from jevplays.executor.shop import buy_pokeballs, buy_potions, heal_at_nurse
from jevplays.state.modes import Mode
from jevplays.state.snapshot import snapshot


def test_heal_at_the_viridian_nurse(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("viridian_center"))
        assert heal_at_nurse(emu)
        s = snapshot(emu)
        assert s.party[0].hp == s.party[0].max_hp
        assert s.mode is Mode.OVERWORLD


def test_buy_three_pokeballs(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("mart_dex"))
        before = snapshot(emu).money
        assert buy_pokeballs(emu, 3) >= 3
        s = snapshot(emu)
        assert any(item.name == "POKE BALL" and item.quantity >= 3 for item in s.bag)
        assert s.money == before - 600
        assert s.mode is Mode.OVERWORLD


def test_buy_two_potions_at_the_pewter_mart(rom, state_path):
    """Skips until `states/pewter_mart.state` exists -- no state reaches Pewter yet (#27).

    It is here rather than in a notebook because it is the assertion that settles what the Pewter
    shelf actually holds: the Viridian shelf was read off the ROM and has no Potion, and Pewter's
    was never verified, only assumed. The first developer with a Pewter state finds out here.
    """
    with Emulator(rom) as emu:
        emu.load(state_path("pewter_mart"))
        assert buy_potions(emu, 2) >= 2
        s = snapshot(emu)
        assert any(item.name == "POTION" and item.quantity >= 2 for item in s.bag)
        assert s.mode is Mode.OVERWORLD


def test_restocking_at_viridian_buys_balls_and_finds_no_potion(rom, state_path):
    """The clerk option's macro: balls first, then Potions from what is left. Viridian's shelf has
    no Potion (read off the ROM), which is an ordinary outcome: 0 bought, the run carries on."""
    from jevplays.executor.shop import restock

    with Emulator(rom) as emu:
        emu.load(state_path("mart_dex"))
        before = snapshot(emu)
        bought = restock(emu, before)
        assert bought["POKE BALL"] >= 1 and bought.get("POTION", 0) == 0
        after = snapshot(emu)
        assert after.money < before.money and after.mode is Mode.OVERWORLD
