"""Spec 2026-10-02 dashboard redesign, 3.6: the `view` the server attaches to a decision event,
built from the decision alone, in the words a viewer needs first."""

from jevplays.dashboard.present import present


def choice(choice_, probabilities, *, applied=True, confidence=0.5):
    return {
        "primitive": "choice",
        "choice": choice_,
        "probabilities": probabilities,
        "confidence": confidence,
        "applied": applied,
    }


def noul(p, *, applied=False):
    return {"primitive": "noul", "noul": p, "applied": applied}


def battle_decision():
    return {
        "id": "b1",
        "ts": 1790919701.9,
        "kind": "battle",
        "state_summary": {
            "our_pokemon": {"name": "SQUIRTLE", "level": 9, "types": ["Water"], "hp": "healthy"},
            "enemy_pokemon": {"name": "WEEDLE", "level": 3, "types": ["Bug", "Poison"], "hp": "full"},
            "battle": {"kind": "wild"},
            "bench": [{"name": "PIDGEY", "level": 4, "label": "PIDGEY"}],
            "party": "two",
            "bag": {"poke_balls": True, "potions": False},
            "goal": "Challenge Brock at the Pewter Gym and earn the Boulder Badge. Build a party of three.",
        },
        "questions": {
            "move": {
                "primitive": "choice",
                "instructions": "Which move should `our_pokemon` use?",
                "options": ["TACKLE", "BUBBLE"],
            },
            "switch": {"primitive": "noul", "instructions": "Should we switch out?", "options": []},
            "switch_to": {
                "primitive": "choice",
                "instructions": "If we switch, which?",
                "options": ["PIDGEY"],
            },
            "run": {"primitive": "noul", "instructions": "Should we run?", "options": []},
            "catch": {"primitive": "noul", "instructions": "Should we throw a Poké Ball?", "options": []},
            "faint": {"primitive": "noul", "instructions": "Will `our_pokemon` faint?", "options": []},
        },
        "answers": {
            "move": choice("BUBBLE", {"BUBBLE": 0.76, "TACKLE": 0.24}, applied=False, confidence=0.52),
            "switch": noul(0.12),
            "switch_to": choice("PIDGEY", {"PIDGEY": 1.0}, applied=False, confidence=1.0),
            "run": noul(0.12),
            "catch": noul(0.35, applied=True),
            "faint": noul(0.08),
        },
        "action": "throw a Poké Ball",
        "fallback": False,
        "fallback_reason": "",
        "model": "jev-1.13.0",
        "input_tokens": 886,
        "latency_ms": 123,
    }


def explore_decision():
    return {
        "id": "e1",
        "ts": 1790919655.8,
        "kind": "explore",
        "state_summary": {
            "map": "Viridian City",
            "progress": [],
            "party": [],
            "milestone": "Challenge Brock at the Pewter Gym and earn the Boulder Badge",
            "standing_goal": "Build a party of three and keep them healthy.",
            "options": {
                "milestone": "work on the milestone: Challenge Brock at the Pewter Gym (new)",
                "grass": "train in the tall grass here, with no Poké Balls to catch with (new)",
                "npc_1": "talk to a youngster to the north-west (talked already)",
                "exit_east": "go east to Route 2 (visited)",
            },
        },
        "questions": {
            "explore": {
                "primitive": "choice",
                "instructions": 'Which of "options" should we do next?',
                "options": ["milestone", "grass", "npc_1", "exit_east"],
            },
            "needs_heal": {
                "primitive": "noul",
                "instructions": "Should the party heal first?",
                "options": [],
            },
        },
        "answers": {
            "explore": choice(
                "grass", {"grass": 0.65, "milestone": 0.15, "npc_1": 0.12, "exit_east": 0.07}, confidence=0.56
            ),
            "needs_heal": noul(0.11),
        },
        "action": "explore: train in the tall grass here, with no Poké Balls to catch with",
        "fallback": False,
        "fallback_reason": "",
        "model": "jev-1.13.0",
        "input_tokens": 952,
        "latency_ms": 85,
    }


def test_battle_view_puts_the_acted_on_question_first_and_the_prediction_last():
    view = present(battle_decision())
    assert view["actor"] == "jev" and view["kind"] == "battle"
    assert [q["id"] for q in view["questions"]] == ["catch", "move", "switch", "switch_to", "run", "faint"]
    assert [q["role"] for q in view["questions"]] == [
        "applied",
        "unused",
        "unused",
        "unused",
        "unused",
        "prediction",
    ]
    catch = view["questions"][0]
    assert catch["label"] == "Throw a Poké Ball?" and catch["primitive"] == "noul" and catch["yes"] == 0.35
    assert catch["instructions"] == "Should we throw a Poké Ball?"


def test_choice_options_are_sorted_by_probability_with_the_chosen_one_marked():
    move = present(battle_decision())["questions"][1]
    assert move["label"] == "Which move?" and move["confidence"] == 0.52
    assert [(o["label"], o["p"], o["chosen"]) for o in move["options"]] == [
        ("BUBBLE", 0.76, True),
        ("TACKLE", 0.24, False),
    ]
    assert all(o["memory"] == "" for o in move["options"])


def test_battle_where_names_both_pokemon_and_the_kind_of_battle():
    assert present(battle_decision())["where"] == "SQUIRTLE L9 vs a wild WEEDLE L3"
    d = battle_decision()
    d["state_summary"]["battle"] = {"kind": "trainer"}
    assert present(d)["where"] == "SQUIRTLE L9 vs a trainer's WEEDLE L3"


def test_battle_handoff_goal_and_summary():
    view = present(battle_decision())
    assert view["handoff"] == "code presses: throw a Poké Ball"
    assert (
        view["goal"]
        == "Challenge Brock at the Pewter Gym and earn the Boulder Badge. Build a party of three."
    )
    assert view["summary"] == "throw a Poké Ball · yes 35%"
    assert view["reason"] == ""


def test_explore_options_are_labelled_with_the_text_jev_saw_and_the_memory_word_split_off():
    view = present(explore_decision())
    explore = view["questions"][0]
    assert explore["id"] == "explore" and explore["label"] == "What next?" and explore["role"] == "applied"
    assert [(o["id"], o["label"], o["memory"]) for o in explore["options"]] == [
        ("grass", "train in the tall grass here, with no Poké Balls to catch with", "new"),
        ("milestone", "work on the milestone: Challenge Brock at the Pewter Gym", "new"),
        ("npc_1", "talk to a youngster to the north-west", "talked already"),
        ("exit_east", "go east to Route 2", "visited"),
    ]
    assert explore["options"][0]["chosen"] and not explore["options"][1]["chosen"]


def test_explore_where_goal_handoff_and_summary():
    view = present(explore_decision())
    assert view["where"] == "on Viridian City"
    assert view["goal"] == (
        "Challenge Brock at the Pewter Gym and earn the Boulder Badge. Build a party of three and keep them healthy."
    )
    assert view["handoff"] == "code walks: train in the tall grass here, with no Poké Balls to catch with"
    assert view["summary"] == "train in the tall grass here, with no Poké Balls to catch with · 65%"
    assert view["questions"][1]["label"] == "Heal first?" and view["questions"][1]["role"] == "unused"


def test_a_decision_code_made_on_its_own_has_no_model_and_says_so():
    d = {
        "id": "p1",
        "ts": 1.0,
        "kind": "prompt",
        "state_summary": {"prompt": "give a nickname to PIDGEY?", "goal": "Challenge Brock"},
        "questions": {},
        "answers": {},
        "action": "answer NO",
        "fallback": False,
        "fallback_reason": "policy: never nickname",
        "model": "",
        "input_tokens": 0,
        "latency_ms": 0,
    }
    view = present(d)
    assert view["actor"] == "code"
    assert view["where"] == 'the prompt "give a nickname to PIDGEY?"'
    assert view["questions"] == []
    assert view["handoff"] == "code answers: NO"
    assert view["reason"] == "policy: never nickname"
    assert view["goal"] == "Challenge Brock"
    assert view["summary"] == "answer NO · code: policy: never nickname"


def test_a_prompt_jev_answered_shows_the_yes_share():
    d = {
        "id": "p2",
        "ts": 1.0,
        "kind": "prompt",
        "state_summary": {"prompt": "Would you like to buy?", "goal": "g"},
        "questions": {"prompt": {"primitive": "noul", "instructions": "Would YES help?", "options": []}},
        "answers": {"prompt": noul(0.81, applied=True)},
        "action": "answer YES",
        "fallback": False,
        "fallback_reason": "",
        "model": "jev-1.13.0",
        "input_tokens": 300,
        "latency_ms": 90,
    }
    view = present(d)
    assert view["questions"][0]["label"] == "Answer YES?"
    assert view["summary"] == "answer YES · yes 81%"


def test_starter_and_menu_kinds():
    starter = {
        "id": "s1",
        "ts": 1.0,
        "kind": "starter",
        "state_summary": {"goal": "Challenge Brock"},
        "questions": {
            "starter": {
                "primitive": "choice",
                "instructions": "Which starter?",
                "options": ["BULBASAUR", "CHARMANDER", "SQUIRTLE"],
            }
        },
        "answers": {
            "starter": choice(
                "SQUIRTLE", {"BULBASAUR": 0.26, "CHARMANDER": 0.34, "SQUIRTLE": 0.4}, confidence=0.1
            )
        },
        "action": "take SQUIRTLE",
        "fallback": False,
        "fallback_reason": "",
        "model": "jev-1.13.0",
        "input_tokens": 399,
        "latency_ms": 125,
    }
    view = present(starter)
    assert view["where"] == "at Oak's table"
    assert view["questions"][0]["label"] == "Which starter?"
    assert [o["label"] for o in view["questions"][0]["options"]] == ["SQUIRTLE", "CHARMANDER", "BULBASAUR"]
    assert view["handoff"] == "code takes: SQUIRTLE" and view["summary"] == "take SQUIRTLE · 40%"

    menu = {
        "id": "m1",
        "ts": 1.0,
        "kind": "menu",
        "state_summary": {"menu_items": ["POKéMON", "ITEM", "EXIT"], "screen_text": "", "goal": "g"},
        "questions": {
            "menu": {
                "primitive": "choice",
                "instructions": "Which item?",
                "options": ["POKéMON", "ITEM", "EXIT"],
            },
            "close": {"primitive": "noul", "instructions": "Close it?", "options": []},
        },
        "answers": {
            "menu": choice("ITEM", {"POKéMON": 0.2, "ITEM": 0.7, "EXIT": 0.1}, applied=True),
            "close": noul(0.2),
        },
        "action": "select ITEM",
        "fallback": False,
        "fallback_reason": "",
        "model": "jev-1.13.0",
        "input_tokens": 1,
        "latency_ms": 1,
    }
    view = present(menu)
    assert view["where"] == "a menu: POKéMON / ITEM / EXIT"
    assert [q["label"] for q in view["questions"]] == ["Which item?", "Close the menu?"]
    assert view["handoff"] == "code selects: ITEM"


def test_an_unknown_question_id_is_still_labelled_and_a_bare_decision_still_presents():
    d = {
        "id": "x",
        "ts": 0.0,
        "kind": "battle",
        "state_summary": {},
        "questions": {"use_item": {"primitive": "noul", "instructions": "?", "options": []}},
        "answers": {"use_item": noul(0.5, applied=True)},
        "action": "do a thing",
        "model": "jev-1.13.0",
    }
    view = present(d)
    assert view["where"] == "" and view["goal"] == ""
    assert view["questions"][0]["label"] == "use item"
    assert view["handoff"] == "code presses: do a thing"
    assert view["summary"] == "do a thing · yes 50%"


def test_an_answer_without_a_question_is_skipped_and_a_question_without_an_answer_too():
    d = explore_decision()
    d["answers"]["extra"] = noul(0.5)
    del d["answers"]["needs_heal"]
    assert [q["id"] for q in present(d)["questions"]] == ["explore"]
