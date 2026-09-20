from jevplays.brain.decision import BattleAction
from jevplays.emulator import ram
from jevplays.emulator.pyboy import Emulator
from jevplays.executor.battle import apply, select_command, select_move
from jevplays.state.snapshot import rows_of


def test_apply_move_uses_the_chosen_move(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("battle_trainer"))
        apply(emu, BattleAction(kind="move", move="GROWL"))
        emu.tick(60)
        seen = " ".join("".join(r) for r in rows_of(emu.tilemap())[13:17])
        assert "GROWL" in seen


def test_apply_move_selects_the_first_move_from_a_lower_cursor(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("battle_trainer"))
        select_command(emu, "FIGHT")
        emu.press("down", settle=16)  # cursor is now on the second move, not the first
        select_move(emu, "SCRATCH")
        emu.tick(60)
        seen = " ".join("".join(r) for r in rows_of(emu.tilemap())[13:17])
        assert "SCRATCH" in seen


def test_run_away_from_a_wild_battle(rom, state_path):
    with Emulator(rom) as emu:
        emu.load(state_path("battle_wild"))
        apply(emu, BattleAction(kind="run"))
        for _ in range(60):
            if emu.mem[ram.wIsInBattle] == 0:
                break
            emu.press("a", settle=20)
        assert emu.mem[ram.wIsInBattle] == 0
