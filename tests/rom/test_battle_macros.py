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


def test_an_open_move_list_reads_as_one_and_b_goes_back_to_the_battle_menu(rom, state_path):
    """#67: the loop presses B on the move list, never A, so a stray A that opened FIGHT costs a
    press instead of using the move under the cursor. Both halves are the real game's screens."""
    from jevplays.state.modes import Mode
    from jevplays.state.snapshot import snapshot

    with Emulator(rom) as emu:
        emu.load(state_path("battle_trainer"))
        assert snapshot(emu).mode is Mode.BATTLE_MENU
        select_command(emu, "FIGHT")
        assert snapshot(emu).mode is Mode.MOVE_LIST
        emu.press("b", settle=20)
        assert snapshot(emu).mode is Mode.BATTLE_MENU
