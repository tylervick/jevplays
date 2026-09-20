from jevplays.brain.decision import BattleAction
from jevplays.emulator import ram
from jevplays.emulator.pyboy import Emulator
from jevplays.executor.battle import apply
from jevplays.state.snapshot import rows_of


def test_apply_move_uses_the_chosen_move(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("battle_trainer"))
        apply(emu, BattleAction(kind="move", move="GROWL"))
        emu.tick(60)
        seen = " ".join("".join(r) for r in rows_of(emu.tilemap())[13:17])
        assert "GROWL" in seen


def test_run_away_from_a_wild_battle(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("battle_wild"))
        apply(emu, BattleAction(kind="run"))
        for _ in range(60):
            if emu.mem[ram.wIsInBattle] == 0:
                break
            emu.press("a", settle=20)
        assert emu.mem[ram.wIsInBattle] == 0
