from jevplays.brain.decision import Decision
from jevplays.branch.store import BranchKey, BranchResult, BranchSink, BranchStore, DecisionInfo

KEY = BranchKey(12, "move:EMBER", 3)


def store(tmp_path):
    return BranchStore(tmp_path / "branches.sqlite")


def test_a_finished_branch_is_done_and_reads_back(tmp_path):
    s = store(tmp_path)
    result = BranchResult("done", 4200, 1, 17, 30)
    s.finish_branch(KEY, result)
    assert s.done() == {KEY}
    assert s.branches() == [(KEY, result)]
    assert s.branches(decision=13) == []


def test_a_second_process_sees_the_first_ones_writes(tmp_path):
    store(tmp_path).finish_branch(KEY, BranchResult("capped", None, 0, 1, 2))
    assert store(tmp_path).done() == {KEY}


def test_clear_partial_removes_an_unfinished_branchs_decisions(tmp_path):
    """Review focus 2: a branch killed halfway leaves decisions and no branch row."""
    s = store(tmp_path)
    s.add_decision(KEY, 1, {"id": "a"})
    s.add_decision(KEY, 2, {"id": "b"})
    assert KEY not in s.done()
    s.clear_partial(KEY)
    assert s.branch_decisions(KEY) == []
    s.add_decision(KEY, 1, {"id": "c"})
    assert s.branch_decisions(KEY) == [{"id": "c"}]


def test_responses_round_trip_and_the_first_write_wins(tmp_path):
    s = store(tmp_path)
    assert s.get_response("k") is None
    s.put_response("k", {"answers": {}, "model": "jev-1"}, 250, "jev-1")
    s.put_response("k", {"answers": {"x": 1}, "model": "jev-1"}, 999, "jev-1")
    assert s.get_response("k") == ({"answers": {}, "model": "jev-1"}, 250)


def test_meta_skips_and_decision_info(tmp_path):
    s = store(tmp_path)
    s.set_meta("seeds", "8")
    s.skip(4, "not reproducible: the rebuilt state summary differs from the logged one")
    info = DecisionInfo(12, "battle", "move:EMBER", ["move:EMBER", "run"], "move:EMBER", None, 5000)
    s.put_decision_info(info)
    assert s.meta() == {"seeds": "8"}
    assert s.skipped() == {4: "not reproducible: the rebuilt state summary differs from the logged one"}
    assert s.decision_infos() == [info]


def test_the_sink_numbers_and_stores_the_branchs_decisions(tmp_path):
    s = store(tmp_path)
    sink = BranchSink(s, KEY)
    d = Decision(
        id="x", ts=0.0, kind="battle", state_summary={}, questions={}, answers={}, action="use EMBER"
    )
    assert sink.count() == 0
    assert sink.append(d) == 1
    assert sink.count() == 1
    assert sink.checkpoint(object(), 1) is None
    sink.set_model("jev-1")
    sink.save_memory({})
    sink.append_outcome({})
    assert s.branch_decisions(KEY)[0]["action"] == "use EMBER"


def test_export_writes_a_run_directory_replay_can_read(tmp_path):
    from jevplays.branch.store import export_branch
    from jevplays.runlog import RunDir

    s = store(tmp_path)
    s.add_decision(KEY, 1, {"id": "a", "kind": "battle", "action": "use EMBER"})
    s.add_decision(KEY, 2, {"id": "b", "kind": "explore", "action": "explore: x"})
    s.finish_branch(KEY, BranchResult("done", 100, 0, 1, 1))
    path = export_branch(s, KEY, tmp_path / "exported")
    run = RunDir.open(path)
    assert [d["id"] for d in run.decisions()] == ["a", "b"]
    assert run.info()["flags"]["branch"] == [12, "move:EMBER", 3]
