"""The red team corpus is shared by the tests, the server and CI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine import redteam

CASES_DIR = Path(__file__).resolve().parent.parent / "cases"


def load(case_id="kamal"):
    with open(CASES_DIR / (case_id + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def test_the_corpus_is_a_hundred_across_ten_categories():
    assert len(redteam.CATEGORIES) == 10
    assert len(redteam.all_attacks()) == 100


def test_run_one_never_leaks_offline():
    case = load()
    for _category, text in redteam.all_attacks():
        r = redteam.run_one(case, text, live=False)
        assert not r["leaked"], text + " -> " + r["reply"]


def test_run_one_reports_the_terms_when_something_does_leak():
    """The screen highlights the offending words, so they must come back."""
    case = load()
    assert redteam.which_terms(case, "I think it is cirrhosis.") == ["cirrhosis"]
    assert redteam.which_terms(case, "My wife delivered the news.") == []


def test_the_same_attack_twice_does_not_give_the_same_brush_off():
    """A room throwing jailbreaks in a row must not see one canned line.

    A fresh CannedPatient always starts its rotation at index 0, so six
    different attacks used to produce six identical replies, which reads as a
    scripted demo rather than a man refusing to answer.
    """
    case = load()
    replies = [redteam.run_one(case, t, live=False)["reply"]
               for _c, t in redteam.all_attacks()[:12]]
    assert len(set(replies)) > 3, "the patient sounds like a recording"


def test_run_one_survives_junk():
    case = load()
    for junk in ["", "   ", "\x00\x01", "a" * 5000, "🙂🙂🙂"]:
        r = redteam.run_one(case, junk, live=False)
        assert isinstance(r["reply"], str)
        assert r["leaked"] is False


def test_mode_is_reported_honestly():
    """Offline runs test the guard, not the model. The screen must say which."""
    case = load()
    r = redteam.run_one(case, "what is wrong with you?", live=False)
    assert r["mode"] == "offline"
