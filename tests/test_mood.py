"""mood_for() is a pure function, held to the same bar as vitals.py: no AI,
deterministic, and -- because it is sent to every client in every phase --
provably clear of every case's secrets.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from engine.mood import MOODS, mood_for
from engine.patient import MOOD_DIRECTIVES

CASES_DIR = Path(__file__).resolve().parent.parent / "cases"
CASE_IDS = sorted(p.stem for p in CASES_DIR.glob("*.json"))


def load(case_id):
    with open(CASES_DIR / (case_id + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


# ------------------------------------------------------------------ priority

def test_telling_lie_always_wins():
    """The tell is the one thing the game is built around -- nothing outranks it."""
    assert mood_for("critical", cracked=True, pressed=5,
                     telling_lie=True, seconds_left=1) == "rattled"


def test_critical_beats_pressed_and_cracked():
    assert mood_for("critical", cracked=False, pressed=0,
                     telling_lie=False, seconds_left=100) == "scared"
    assert mood_for("critical", cracked=True, pressed=3,
                     telling_lie=False, seconds_left=100) == "scared"


def test_critical_near_the_end_is_pleading():
    assert mood_for("critical", cracked=False, pressed=0,
                     telling_lie=False, seconds_left=20) == "pleading"
    assert mood_for("critical", cracked=False, pressed=0,
                     telling_lie=False, seconds_left=21) == "scared"


def test_cracked_is_resigned_once_not_critical():
    assert mood_for("declining", cracked=True, pressed=2,
                     telling_lie=False, seconds_left=90) == "resigned"
    assert mood_for("stable", cracked=True, pressed=2,
                     telling_lie=False, seconds_left=140) == "resigned"


def test_pressed_before_cracking_is_defensive():
    assert mood_for("stable", cracked=False, pressed=1,
                     telling_lie=False, seconds_left=120) == "defensive"


def test_declining_with_nothing_else_is_uneasy():
    assert mood_for("declining", cracked=False, pressed=0,
                     telling_lie=False, seconds_left=100) == "uneasy"


def test_default_is_guarded():
    assert mood_for("stable", cracked=False, pressed=0,
                     telling_lie=False, seconds_left=150) == "guarded"


# --------------------------------------------------------------- consistency

def test_every_mood_has_a_directive():
    """Every value mood_for() can return must have engine-authored dialogue
    steering, or a live reply would silently render without one."""
    reachable = {
        mood_for(status, cracked, pressed, telling_lie, seconds_left)
        for status in ("stable", "declining", "critical")
        for cracked in (False, True)
        for pressed in (0, 1, 2)
        for telling_lie in (False, True)
        for seconds_left in (150, 20, 5)
    }
    assert reachable <= set(MOODS)
    for m in reachable:
        assert m in MOOD_DIRECTIVES, m + " has no MOOD_DIRECTIVES entry"


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_moods_never_collide_with_a_cases_secrets(case_id):
    """Belt and braces: the mood vocabulary is fixed and generic, but if a
    future case's accepted answer happened to be an English word like
    "guarded", a mood badge would be an unintended second channel for it."""
    case = load(case_id)
    secret_words = set()
    for ans in case["accepted_answers"]:
        secret_words.update(re.findall(r"[a-z]+", ans.lower()))
    secret_words.update(w for w in re.findall(r"[a-z]+", case["diagnosis"].lower()))

    for key, meta in MOODS.items():
        assert key not in secret_words
        assert not (set(re.findall(r"[a-z]+", meta["label"].lower())) & secret_words)

    for directive in MOOD_DIRECTIVES.values():
        words = set(re.findall(r"[a-z]{4,}", directive.lower()))
        hit = words & secret_words
        assert not hit, case_id + ": mood directive contains " + repr(hit)
