import json
import re

from jevplays.brain.battle import battle_questions, battle_state, decide_battle
from jevplays.brain.decision import BattleAction
from jevplays.brain.policy import choose_battle_action
from jevplays.state.modes import Mode
from jevplays.state.snapshot import BagItem, Battle, GameState, Mon, Move

SCRATCH = Move(name="SCRATCH", type="Normal", power=40, pp=35, max_pp=35)
GROWL = Move(name="GROWL", type="Normal", power=0, pp=40, max_pp=40)
EMBER = Move(name="EMBER", type="Fire", power=40, pp=0, max_pp=25)
CHARMANDER = Mon(
    name="CHARMANDER",
    nickname="CHARMANDER",
    level=8,
    types=("Fire",),
    hp=8,
    max_hp=23,
    status="none",
    moves=(SCRATCH, GROWL, EMBER),
)
PIDGEY = Mon(
    name="PIDGEY",
    nickname="PIDGEY",
    level=4,
    types=("Normal", "Flying"),
    hp=17,
    max_hp=17,
    status="none",
    moves=(Move(name="GUST", type="Normal", power=40, pp=35, max_pp=35),),
)
BULBASAUR = Mon(
    name="BULBASAUR",
    nickname="BULBASAUR",
    level=5,
    types=("Grass", "Poison"),
    hp=15,
    max_hp=20,
    status="none",
    moves=(),
)
CHARMANDER_TWIN = Mon(
    name="CHARMANDER",
    nickname="CHARMANDER",
    level=8,
    types=("Fire",),
    hp=23,
    max_hp=23,
    status="none",
    moves=(SCRATCH, GROWL, EMBER),
)


def make_state(*, kind="wild", bench=(), bag=()):
    return GameState(
        mode=Mode.BATTLE_MENU,
        map_id=12,
        map="Route 1",
        tile=(9, 28),
        player_name="RED",
        party_count=1 + len(bench),
        badges=0,
        money=3000,
        bag_count=len(bag),
        in_battle=True,
        text="",
        menu_items=(),
        cursor=None,
        party=(CHARMANDER, *bench),
        active=CHARMANDER,
        active_slot=0,
        enemy=BULBASAUR,
        battle=Battle(kind=kind, trainer_class=None if kind == "wild" else "RIVAL1"),
        bag=tuple(bag),
    )


def test_state_json_uses_words_not_numbers_for_hp_and_pp():
    s = battle_state(
        make_state(bag=(BagItem("POKE BALL", 3), BagItem("POTION", 1)), bench=(PIDGEY,)),
        goal="Reach Viridian City",
    )
    assert s["our_pokemon"]["hp"] == "hurt" and s["our_pokemon"]["level"] == 8
    assert s["our_pokemon"]["moves"][2] == {
        "name": "EMBER",
        "type": "Fire",
        "kind": "attack",
        "power": "weak",
        "pp": "out",
    }
    assert s["our_pokemon"]["moves"][1]["kind"] == "status"
    assert s["enemy_pokemon"] == {
        "name": "BULBASAUR",
        "level": 5,
        "types": ["Grass", "Poison"],
        "hp": "healthy",
    }
    assert (
        s["battle"] == {"kind": "wild"}
        and s["bag"] == {"poke_balls": True, "potions": True}
        and s["goal"] == "Reach Viridian City"
    )
    numbers = re.findall(r"\d+", json.dumps({k: v for k, v in s.items()}, ensure_ascii=False))
    assert set(numbers) == {"8", "5", "4"}  # the two levels plus the bench Pokémon's level

    qs = battle_questions(s)
    q_numbers = re.findall(r"\d+", json.dumps(qs, ensure_ascii=False))
    assert set(q_numbers) == {"4"}  # only PIDGEY's level, from switch_to's criteria


def test_questions_include_only_what_can_apply():
    wild_alone = battle_questions(battle_state(make_state(), goal="g"))
    assert set(wild_alone) == {"move", "run"}  # no balls, no potions, no bench
    assert wild_alone["move"]["type"] == "choice"
    assert list(wild_alone["move"]["criteria"]) == ["SCRATCH", "GROWL"]  # EMBER is out of PP
    trainer_full = battle_questions(
        battle_state(
            make_state(kind="trainer", bench=(PIDGEY,), bag=(BagItem("POKE BALL", 1), BagItem("POTION", 1))),
            goal="g",
        )
    )
    assert set(trainer_full) == {"move", "switch", "switch_to", "heal"}  # no run/catch in a trainer battle
    assert list(trainer_full["switch_to"]["criteria"]) == ["PIDGEY"]


def test_bench_keeps_a_same_species_twin():
    s = battle_state(make_state(bench=(CHARMANDER_TWIN,)), goal="g")
    assert len(s["bench"]) == 1
    assert s["bench"][0]["name"] == "CHARMANDER"


def answers(**kw):
    out = {}
    for k, v in kw.items():
        if isinstance(v, dict):
            out[k] = {"type": "choice", "choice": max(v, key=v.get), "probabilities": v, "confidence": 0.5}
        else:
            out[k] = {"type": "noul", "noul": v}
    return out


def test_policy_order_heal_catch_run_switch_move():
    sj = {"our_pokemon": {"hp": "low"}, "battle": {"kind": "wild"}}
    a = answers(
        move={"SCRATCH": 0.9, "GROWL": 0.1},
        heal=0.9,
        catch=0.9,
        run=0.9,
        switch=0.9,
        switch_to={"PIDGEY": 1.0},
    )
    assert choose_battle_action(a, sj)[0] == BattleAction(kind="heal")
    a["heal"]["noul"] = 0.2
    assert choose_battle_action(a, sj)[0] == BattleAction(kind="catch")
    a["catch"]["noul"] = 0.2
    assert choose_battle_action(a, sj)[0] == BattleAction(kind="run")
    a["run"]["noul"] = 0.2
    assert choose_battle_action(a, sj)[0] == BattleAction(kind="switch", target="PIDGEY")
    a["switch"]["noul"] = 0.2
    action, used = choose_battle_action(a, sj)
    assert action == BattleAction(kind="move", move="SCRATCH") and used == ["move"]


def test_heal_needs_low_hp_not_just_a_yes():
    sj = {"our_pokemon": {"hp": "healthy"}, "battle": {"kind": "wild"}}
    a = answers(move={"SCRATCH": 1.0}, heal=0.95)
    assert choose_battle_action(a, sj)[0].kind == "move"


def test_policy_without_a_move_answer_returns_none():
    sj = {"our_pokemon": {"hp": "healthy"}, "battle": {"kind": "wild"}}
    assert choose_battle_action({}, sj) == (None, [])


def test_switch_needs_a_choice_answer_for_switch_to():
    sj = {"our_pokemon": {"hp": "healthy"}, "battle": {"kind": "wild"}}
    a = answers(move={"SCRATCH": 1.0}, switch=0.9)
    a["switch_to"] = {"type": "noul", "noul": 0.9}  # not a choice answer
    action, used = choose_battle_action(a, sj)
    assert action == BattleAction(kind="move", move="SCRATCH") and used == ["move"]


def test_decide_battle_marks_applied_answers_and_falls_back_for_unsupported_actions():
    state = make_state(kind="trainer", bench=(PIDGEY,))
    sj = battle_state(state, goal="g")
    qs = battle_questions(sj)
    response = {
        "model": "jev-1.13.0",
        "usage": {"input_tokens": 700, "output_tokens": 50},
        "answers": answers(move={"SCRATCH": 0.7, "GROWL": 0.3}, switch=0.9, switch_to={"PIDGEY": 1.0}),
    }
    d = decide_battle(sj, qs, response, model="jev-1.13.0", input_tokens=700, latency_ms=400)
    assert d.kind == "battle" and d.model == "jev-1.13.0" and d.input_tokens == 700 and d.latency_ms == 400
    assert d.fallback is True and "switch" in d.fallback_reason
    assert d.action == "use SCRATCH"
    assert (
        d.answers["switch"]["applied"] is True
        and d.answers["switch_to"]["applied"] is True
        and d.answers["move"]["applied"] is True
    )
    assert d.questions["move"]["options"] == ["SCRATCH", "GROWL"]
    assert d.to_dict()["answers"]["move"]["probabilities"]["SCRATCH"] == 0.7


def test_decide_battle_plain_move():
    state = make_state()
    sj = battle_state(state, goal="g")
    qs = battle_questions(sj)
    response = {
        "model": "m",
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "answers": answers(move={"SCRATCH": 0.6, "GROWL": 0.4}, run=0.1),
    }
    d = decide_battle(sj, qs, response, model="m", input_tokens=1, latency_ms=1)
    assert d.fallback is False and d.action == "use SCRATCH"
    assert d.answers["run"]["applied"] is False
