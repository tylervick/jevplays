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


def test_glyphs_survive_run_json_and_the_log_whatever_the_locale_says(tmp_path, monkeypatch):
    monkeypatch.setenv("LC_ALL", "C")
    run = RunDir.create(tmp_path, rom=None, flags={"battle_goal": "catch NIDORAN♂"})
    run.set_model("jev-1.13.0")
    d = decision(1)
    d.state_summary = {"prompt": "give a NICKNAME to POKé BALL?"}
    run.append(d)
    assert run.info()["flags"]["battle_goal"] == "catch NIDORAN♂"
    assert next(run.decisions())["state_summary"]["prompt"] == "give a NICKNAME to POKé BALL?"


def test_a_torn_last_line_is_skipped_with_a_warning_and_repaired_by_the_next_append(tmp_path):
    import pytest

    run = RunDir.create(tmp_path, rom=None, flags={})
    run.append(decision(1))
    with open(run.log_path, "a", encoding="utf-8") as f:
        f.write('{"id": "d2", "kin')  # a crash mid-write: no newline, no closing brace
    assert run.count() == 2
    with pytest.warns(UserWarning, match="decisions.jsonl"):
        assert [d["id"] for d in run.decisions()] == ["d1"]

    assert run.append(decision(3)) == 3
    lines = run.log_path.read_text().splitlines()
    assert lines[1] == '{"id": "d2", "kin' and json.loads(lines[2])["id"] == "d3"
    with pytest.warns(UserWarning):
        assert [d["id"] for d in run.decisions()] == ["d1", "d3"]


def test_a_broken_line_that_is_not_the_last_is_corruption_and_raises(tmp_path):
    import pytest

    run = RunDir.create(tmp_path, rom=None, flags={})
    run.append(decision(1))
    with open(run.log_path, "a", encoding="utf-8") as f:
        f.write("{not json}\n")
    run.append(decision(3))
    with pytest.raises(ValueError, match="line 2"):
        list(run.decisions())


def test_truncate_to_moves_the_decisions_after_a_checkpoint_aside(tmp_path):
    run = RunDir.create(tmp_path, rom=None, flags={})
    for i in range(30):
        run.append(decision(i))
    assert run.truncate_to(25) == 5
    assert run.count() == 25
    assert [d["id"] for d in run.decisions()][-1] == "d24"
    orphaned = (run.path / "decisions.orphaned.jsonl").read_text().splitlines()
    assert [json.loads(line)["id"] for line in orphaned] == ["d25", "d26", "d27", "d28", "d29"]
    assert run.truncate_to(25) == 0 and run.count() == 25


def test_truncate_to_a_count_the_log_has_not_reached_moves_nothing(tmp_path):
    run = RunDir.create(tmp_path, rom=None, flags={})
    run.append(decision(1))
    assert run.truncate_to(5) == 0
    assert not (run.path / "decisions.orphaned.jsonl").exists()


def test_checkpoint_number_reads_the_count_back_out_of_the_name(tmp_path):
    import pytest

    run = RunDir.create(tmp_path, rom=None, flags={})
    path = run.checkpoint(FakeEmulator(), 25)
    assert RunDir.checkpoint_number(path) == 25
    with pytest.raises(ValueError):
        RunDir.checkpoint_number(run.path / "run.json")


def test_mark_resumed_records_the_checkpoint_it_came_from(tmp_path):
    run = RunDir.create(tmp_path, rom=None, flags={})
    run.mark_resumed(now=datetime(2026, 9, 21, 8, 0, 0), from_checkpoint=25, orphaned=5)
    assert run.info()["resumed_at"] == [{"at": "2026-09-21T08:00:00", "from_checkpoint": 25, "orphaned": 5}]


def test_set_model_does_not_rewrite_run_json_when_nothing_changes(tmp_path, monkeypatch):
    run = RunDir.create(tmp_path, rom=None, flags={})
    run.set_model("jev-1.13.0")
    writes = []
    monkeypatch.setattr(RunDir, "_write_info", lambda self, info: writes.append(info))
    run.set_model("jev-1.13.0")
    assert writes == []
    run.set_model("jev-1.14.0")
    assert len(writes) == 1


def test_memory_round_trips_through_the_run_dir(tmp_path):
    run = RunDir.create(tmp_path, rom=None, flags={})
    assert run.load_memory() is None  # nothing written yet
    memory = {"visited_maps": [0, 41], "talked": [[41, 3]], "tried": [[0, "grass"]]}
    run.save_memory(memory)
    assert run.load_memory() == memory
    assert RunDir.open(run.path).load_memory() == memory
    run.save_memory({"visited_maps": [0, 41, 12], "talked": [], "tried": []})
    assert run.load_memory()["visited_maps"] == [0, 41, 12]  # overwritten whole, not appended to


def test_saving_memory_leaves_no_temp_file_behind(tmp_path):
    """It is written through a temp file and a rename, so a crash mid-write leaves the last good
    memory rather than half of the new one."""
    run = RunDir.create(tmp_path, rom=None, flags={})
    run.save_memory({"visited_maps": [1], "talked": [], "tried": []})
    assert [p.name for p in run.path.iterdir() if p.suffix == ".tmp"] == []
    assert run.memory_path.name == "memory.json"


def test_outcomes_are_a_second_stream_beside_the_decisions(tmp_path):
    """A resolved prediction is appended on its own, keyed by the decision it scores: the
    decision line was written turns earlier and is never rewritten."""
    run = RunDir.create(tmp_path / "runs", rom=None, flags={})
    run.append(decision(1))
    run.append_outcome({"decision_id": "d1", "question": "faint", "predicted": 0.7, "observed": True})
    assert run.count() == 1
    assert [o["decision_id"] for o in run.outcomes()] == ["d1"]
    assert run.outcomes_path.read_text(encoding="utf-8").count("\n") == 1


def test_a_torn_outcome_line_is_skipped_rather_than_read_as_a_resolution(tmp_path):
    run = RunDir.create(tmp_path / "runs", rom=None, flags={})
    run.append_outcome({"decision_id": "d1", "question": "faint", "predicted": 0.7, "observed": True})
    with open(run.outcomes_path, "a", encoding="utf-8") as f:
        f.write('{"decision_id": "d2", "question": "fai')
    assert [o["decision_id"] for o in run.outcomes()] == ["d1"]
