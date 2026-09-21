"""The item and switch macros, driven against the real game.

`battle_items.state` is a wild battle with 5 POKé BALLs and 3 POTIONs in the bag;
`battle_two.state` is a later wild battle with a second Pokémon on the bench.
"""

from jevplays.emulator import ram
from jevplays.emulator.pyboy import Emulator
from jevplays.executor.battle import switch_to, throw_ball, use_potion
from jevplays.state.snapshot import snapshot

HURT_HP = 5


def balls(state) -> int:
    return next((i.quantity for i in state.bag if i.name == "POKE BALL"), 0)


def hurt_the_lead(emu: Emulator) -> None:
    """Put the lead on `HURT_HP`, in both records: the battle copy is what `snapshot` reads
    while a battle is running, and the party record is what the game's own item code checks
    before it decides a Potion "won't have any effect"."""
    for addr in (ram.wBattleMonHP, ram.wPartyMons + ram.MON_HP):
        emu.mem[addr] = HURT_HP >> 8
        emu.mem[addr + 1] = HURT_HP & 0xFF


def test_throwing_a_ball_spends_one(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("battle_items"))
        before = balls(snapshot(emu))
        throw_ball(emu)
        for _ in range(12):
            emu.press("a", settle=40)
        assert balls(snapshot(emu)) == before - 1


def test_a_potion_heals_the_lead(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("battle_items"))
        hurt_the_lead(emu)
        use_potion(emu, 0)
        for _ in range(8):
            emu.press("a", settle=40)
        assert ram.read_u16(emu.mem, ram.wBattleMonHP) > HURT_HP
        assert ram.read_u16(emu.mem, ram.wPartyMons + ram.MON_HP) > HURT_HP


def test_switching_brings_the_bench_pokemon_in(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("battle_two"))
        assert snapshot(emu).active_slot == 0
        switch_to(emu, 1)
        for _ in range(12):
            emu.press("a", settle=40)
            if snapshot(emu).active_slot == 1:
                break
        assert snapshot(emu).active_slot == 1
