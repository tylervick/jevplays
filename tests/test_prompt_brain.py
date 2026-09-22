import json
import re
from dataclasses import replace

from jevplays.brain.decision import MenuAction, PromptAction
from jevplays.brain.policy import choose_menu, choose_prompt, settled_prompt
from jevplays.brain.prompt import (
    decide_menu,
    decide_prompt,
    menu_questions,
    menu_state,
    prompt_questions,
    prompt_state,
)
from tests.support import overworld_state


def answers(**kw):
    out = {}
    for k, v in kw.items():
        if isinstance(v, dict):
            out[k] = {"type": "choice", "choice": max(v, key=v.get), "probabilities": v, "confidence": 0.5}
        else:
            out[k] = {"type": "noul", "noul": v}
    return out


# --- prompt --------------------------------------------------------------------------------


def test_prompt_state_is_the_text_and_the_goal():
    state = replace(overworld_state(), text="TEACH CHARMANDER SURF?")
    sj = prompt_state(state, "Cross the sea")
    assert sj == {"prompt": "TEACH CHARMANDER SURF?", "goal": "Cross the sea"}


def test_prompt_questions_ask_one_noul():
    qs = prompt_questions({"prompt": "x", "goal": "y"})
    assert set(qs) == {"prompt"}
    assert qs["prompt"]["type"] == "noul"


def test_policy_prompt_yes_above_threshold_else_no():
    assert choose_prompt(answers(prompt=0.6), "SAVE THE GAME?") == (True, ["prompt"])
    assert choose_prompt(answers(prompt=0.4), "SAVE THE GAME?") == (False, ["prompt"])
    assert choose_prompt({}, "SAVE THE GAME?") == (False, [])


def test_policy_never_nicknames_without_consulting_the_answer():
    # A near-certain yes is ignored: the guard fires before the answer is read.
    assert choose_prompt(answers(prompt=0.99), "NICKNAME CHARMANDER?") == (False, [])
    assert choose_prompt(answers(prompt=0.99), "give a nickname?") == (False, [])  # case-insensitive


def test_decide_prompt_marks_applied_and_answers_yes():
    sj = {"prompt": "SAVE THE GAME?", "goal": "Beat Brock"}
    qs = prompt_questions(sj)
    response = {
        "model": "m",
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "answers": answers(prompt=0.9),
    }
    d = decide_prompt(sj, qs, response, model="m", input_tokens=1, latency_ms=1)
    assert d.kind == "prompt" and d.action == "answer YES"
    assert d.action_value == PromptAction(yes=True)
    assert d.fallback is False and d.fallback_reason == ""
    assert d.answers["prompt"]["applied"] is True
    assert "policy_note" not in d.state_summary


def test_decide_prompt_never_nicknames_and_records_the_policy_note():
    sj = {"prompt": "WOULD YOU LIKE TO GIVE A NICKNAME?", "goal": "Get a starter Pokémon"}
    qs = prompt_questions(sj)
    response = {
        "model": "m",
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "answers": answers(prompt=0.95),
    }
    d = decide_prompt(sj, qs, response, model="m", input_tokens=1, latency_ms=1)
    assert d.action == "answer NO"
    assert d.action_value == PromptAction(yes=False)
    assert d.fallback is False and d.fallback_reason == "policy: never nickname"
    assert d.state_summary["policy_note"] == "policy: never nickname"
    assert d.answers["prompt"]["applied"] is False  # the answer was never consulted
    assert "policy_note" not in sj  # the original state summary is untouched


# --- menu ------------------------------------------------------------------------------------


def test_menu_state_lists_items_screen_text_and_goal():
    state = replace(overworld_state(), menu_items=("POTION", "PARCEL", "CANCEL"), text="ITEM")
    sj = menu_state(state, "Buy some Poké Balls")
    assert sj == {
        "menu_items": ["POTION", "PARCEL", "CANCEL"],
        "screen_text": "ITEM",
        "goal": "Buy some Poké Balls",
    }
    numbers = re.findall(r"\d+", json.dumps(sj, ensure_ascii=False))
    assert numbers == []  # menu_state has no levels, so no digits at all are allowed


def test_menu_questions_offer_the_items_and_a_close_noul():
    sj = {"menu_items": ["POTION", "PARCEL"], "screen_text": "x", "goal": "y"}
    qs = menu_questions(sj)
    assert set(qs) == {"menu", "close"}
    assert qs["menu"]["type"] == "choice" and list(qs["menu"]["criteria"]) == ["POTION", "PARCEL"]
    assert qs["close"]["type"] == "noul"


def test_policy_menu_close_above_threshold_else_the_choice():
    a = answers(close=0.7, menu={"POTION": 0.9, "PARCEL": 0.1})
    assert choose_menu(a) == (None, ["close"])
    a["close"]["noul"] = 0.2
    assert choose_menu(a) == ("POTION", ["menu"])
    assert choose_menu({}) == (None, [])


def test_decide_menu_selects_an_item():
    sj = {"menu_items": ["POTION", "PARCEL"], "screen_text": "x", "goal": "y"}
    qs = menu_questions(sj)
    response = {
        "model": "m",
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "answers": answers(close=0.1, menu={"POTION": 0.8, "PARCEL": 0.2}),
    }
    d = decide_menu(sj, qs, response, model="m", input_tokens=1, latency_ms=1)
    assert d.kind == "menu" and d.action == "select POTION"
    assert d.action_value == MenuAction(item="POTION")
    assert d.answers["menu"]["applied"] is True and d.answers["close"]["applied"] is False


def test_decide_menu_closes():
    sj = {"menu_items": ["POTION", "PARCEL"], "screen_text": "x", "goal": "y"}
    qs = menu_questions(sj)
    response = {
        "model": "m",
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "answers": answers(close=0.9, menu={"POTION": 0.8, "PARCEL": 0.2}),
    }
    d = decide_menu(sj, qs, response, model="m", input_tokens=1, latency_ms=1)
    assert d.action == "close the menu"
    assert d.action_value == MenuAction(item=None)
    assert d.answers["close"]["applied"] is True and d.answers["menu"]["applied"] is False


def test_decide_menu_falls_back_when_the_model_picks_an_item_not_on_screen():
    sj = {"menu_items": ["POTION", "PARCEL"], "screen_text": "x", "goal": "y"}
    qs = menu_questions(sj)
    response = {
        "model": "m",
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "answers": answers(close=0.1, menu={"ANTIDOTE": 0.8}),  # not one of sj["menu_items"]
    }
    d = decide_menu(sj, qs, response, model="m", input_tokens=1, latency_ms=1)
    assert d.fallback is True and d.fallback_reason == "menu: model chose an item not on screen"
    assert d.action == "close the menu"
    assert d.action_value == MenuAction(item=None)
    assert d.answers["menu"]["applied"] is False  # the invalid choice was not the one used


def test_decide_menu_falls_back_when_the_menu_question_is_missing():
    sj = {"menu_items": ["POTION", "PARCEL"], "screen_text": "x", "goal": "y"}
    qs = menu_questions(sj)
    response = {
        "model": "m",
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "answers": answers(close=0.1),  # no "menu" answer at all
    }
    d = decide_menu(sj, qs, response, model="m", input_tokens=1, latency_ms=1)
    assert d.fallback is True and d.fallback_reason == "menu: model chose an item not on screen"
    assert d.action == "close the menu"
    assert d.action_value == MenuAction(item=None)


def test_decide_prompt_marks_a_missing_prompt_answer_as_a_fallback():
    """Spec 12: NO with no answer to go on is code's default, not Jev's judgment."""
    sj = {"prompt": "SAVE THE GAME?", "goal": "Beat Brock"}
    qs = prompt_questions(sj)
    response = {"model": "m", "usage": {"input_tokens": 1, "output_tokens": 1}, "answers": {}}
    d = decide_prompt(sj, qs, response, model="m", input_tokens=1, latency_ms=1)
    assert d.action == "answer NO" and d.action_value == PromptAction(yes=False)
    assert d.fallback is True and "no usable prompt answer" in d.fallback_reason
    assert "policy_note" not in d.state_summary


def test_settled_prompt_answers_the_boxes_that_are_not_judgment_calls():
    """A nickname is not a judgment, and neither is the move-learning ring: NO to "make room"
    leads to "Abandon learning X?" and NO to that leads back, so no NO path leaves it (#55)."""
    assert settled_prompt("Do you want to give a NICKNAME to it?") == (False, "never nickname")
    assert settled_prompt("Abandon learning RAGE?") == (True, "never learn a fifth move")
    assert settled_prompt("Delete an older move to make room for RAGE?") == (
        False,
        "never learn a fifth move",
    )


def test_settled_prompt_leaves_an_ordinary_question_to_jev():
    assert settled_prompt("Do you want to go to the next floor?") is None
