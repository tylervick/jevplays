import json
from datetime import datetime

from jevplays.brain.decision import Decision, PromptAction
from jevplays.runlog import CHECKPOINT_EVERY, RunDir, rom_sha256
from tests.support import FakeEmulator


def decision(i: int) -> Decision:
    return Decision(
        id=f"d{i}",
        ts=1000.0 + i,
        kind="prompt",
        state_summary={"prompt": "Yes?"},
        questions={},
        answers={},
        action="answer YES",
        action_value=PromptAction(yes=True),
    )


def test_create_writes_run_json_with_the_rom_hash_flags_and_start_time(tmp_path):
    rom = tmp_path / "game.gb"
    rom.write_bytes(b"not a real rom")
    run = RunDir.create(
        tmp_path / "runs",
        rom=rom,
        flags={"state": "route1.state", "unpaced": True},
        now=datetime(2026, 9, 20, 13, 45, 7),
    )
    assert run.path == tmp_path / "runs" / "20260920-134507"
    info = json.loads((run.path / "run.json").read_text())
    assert info["rom_sha256"] == rom_sha256(rom)
    assert info["flags"] == {"state": "route1.state", "unpaced": True}
    assert info["started_at"] == "2026-09-20T13:45:07"
    assert info["model"] == "" and info["checkpoint_every"] == CHECKPOINT_EVERY
    assert run.count() == 0 and run.last_checkpoint() is None


def test_append_writes_one_decision_per_line_and_reads_them_back(tmp_path):
    run = RunDir.create(tmp_path, rom=None, flags={})
    assert run.append(decision(1)) == 1
    assert run.append(decision(2)) == 2
    lines = (run.path / "decisions.jsonl").read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["id"] == "d1"
    assert [d["action"] for d in run.decisions()] == ["answer YES", "answer YES"]
    assert "action_value" not in json.loads(lines[0])


def test_open_resumes_the_same_directory_and_counts_existing_lines(tmp_path):
    run = RunDir.create(tmp_path, rom=None, flags={})
    run.append(decision(1))
    again = RunDir.open(run.path)
    assert again.count() == 1
    again.append(decision(2))
    assert RunDir.open(run.path).count() == 2


def test_open_a_directory_without_run_json_fails_loudly(tmp_path):
    try:
        RunDir.open(tmp_path)
    except FileNotFoundError as error:
        assert "run.json" in str(error)
    else:
        raise AssertionError("expected FileNotFoundError")


def test_checkpoints_are_numbered_and_the_newest_wins(tmp_path):
    run = RunDir.create(tmp_path, rom=None, flags={})
    emu = FakeEmulator()
    assert run.checkpoint(emu, 25).name == "checkpoint-25.state"
    run.checkpoint(emu, 100)
    run.checkpoint(emu, 50)
    assert run.last_checkpoint().name == "checkpoint-100.state"
    assert (run.path / "checkpoint-25.state").read_bytes() == b"FAKE-STATE:0"
    assert (run.path / "checkpoint-50.state").read_bytes() == b"FAKE-STATE:2"


def test_model_is_recorded_once_and_a_change_is_kept_as_history(tmp_path):
    run = RunDir.create(tmp_path, rom=None, flags={})
    run.set_model("jev-1.13.0")
    run.set_model("jev-1.13.0")
    run.set_model("jev-1.14.0")
    info = run.info()
    assert info["model"] == "jev-1.13.0" and info["models"] == ["jev-1.13.0", "jev-1.14.0"]


def test_mark_resumed_appends_a_timestamp(tmp_path):
    run = RunDir.create(tmp_path, rom=None, flags={})
    run.mark_resumed(now=datetime(2026, 9, 21, 8, 0, 0))
    assert run.info()["resumed_at"] == ["2026-09-21T08:00:00"]
