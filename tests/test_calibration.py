"""The scored prediction: when the game has answered it, and what the answers add up to."""

from dataclasses import replace

from jevplays.calibration import Pending, brier, buckets, resolve_prediction
from jevplays.state.modes import Mode
from jevplays.state.snapshot import Mon, Move
from tests.support import overworld_state

SCRATCH = Move(name="SCRATCH", type="Normal", power=40, pp=35, max_pp=35)


def mon(hp: int) -> Mon:
    return Mon(
        name="CHARMANDER",
        nickname="CHARMANDER",
        level=8,
        types=("Fire",),
        hp=hp,
        max_hp=23,
        status="none",
        moves=(SCRATCH,),
    )


PENDING = Pending(decision_id="d1", slot=0, predicted=0.7)


def battling(hp: int, mode: Mode = Mode.BATTLE_MENU):
    return replace(overworld_state(party=(mon(hp),)), mode=mode, in_battle=True)


def test_mid_turn_the_question_is_not_answered_yet():
    """Between the press and the next menu the animation is still playing: asking the party now
    would score the prediction against a Pokémon that has not been hit yet."""
    assert resolve_prediction(PENDING, battling(23, mode=Mode.BATTLE_WAIT), ts=1.0) is None


def test_back_at_the_battle_menu_a_zeroed_slot_is_a_faint():
    out = resolve_prediction(PENDING, battling(0), ts=5.0)
    assert out == {"decision_id": "d1", "question": "faint", "predicted": 0.7, "observed": True, "ts": 5.0}


def test_back_at_the_battle_menu_with_hp_left_the_prediction_was_wrong():
    assert resolve_prediction(PENDING, battling(4), ts=5.0)["observed"] is False


def test_a_battle_that_ended_resolves_too():
    """Ran, caught it, or blacked out: our Pokémon never gets another turn, so the question is
    answered by the party as it stands."""
    assert resolve_prediction(PENDING, overworld_state(party=(mon(0),)), ts=5.0)["observed"] is True
    assert resolve_prediction(PENDING, overworld_state(party=(mon(11),)), ts=5.0)["observed"] is False


def test_a_slot_that_is_no_longer_there_is_left_unresolved():
    assert resolve_prediction(Pending(decision_id="d1", slot=3, predicted=0.7), battling(0), ts=5.0) is None


def test_brier_is_the_mean_square_error_of_the_probabilities():
    assert brier([(1.0, True), (0.0, False)]) == 0.0
    assert brier([(0.0, True)]) == 1.0
    assert brier([(0.5, True), (0.5, False)]) == 0.25
    assert brier([]) is None


def test_buckets_group_by_predicted_probability_and_report_the_observed_rate():
    rows = buckets([(0.05, False), (0.15, True), (0.95, True), (0.9, True)], width=0.5)
    assert [(r["low"], r["high"], r["n"]) for r in rows] == [(0.0, 0.5, 2), (0.5, 1.0, 2)]
    assert rows[0]["predicted"] == 0.1 and rows[0]["observed"] == 0.5
    assert rows[1]["observed"] == 1.0
