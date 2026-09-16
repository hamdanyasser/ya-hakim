"""The diagnosis never reaches the model, and never reaches a client.

These tests do not call the API. They are fast, they run in CI, and they are the
guarantee the whole project is built on.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from engine import patient
from engine.patient import ALLOWED_IN_PROMPT, SECRET_FIELDS, build_persona
from engine.state import GameState

CASES_DIR = Path(__file__).resolve().parent.parent / "cases"
CASE_FILES = sorted(CASES_DIR.glob("*.json"))
CASE_IDS = [p.stem for p in CASE_FILES]


def load(case_id: str) -> dict:
    with open(CASES_DIR / (case_id + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def words(text: str) -> set:
    return set(re.findall(r"[a-z]+", text.lower()))


assert CASE_FILES, "no case files found -- these tests would pass vacuously"


# ------------------------------------------------------------ the allowlist

def test_allowlist_and_secrets_are_disjoint():
    assert not set(ALLOWED_IN_PROMPT) & set(SECRET_FIELDS)


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_every_case_has_every_secret_field(case_id):
    case = load(case_id)
    for f in SECRET_FIELDS:
        assert f in case, case_id + " is missing " + f


@pytest.mark.parametrize("case_id", CASE_IDS)
@pytest.mark.parametrize("cracked", [False, True])
def test_diagnosis_absent_from_persona(case_id, cracked):
    case = load(case_id)
    persona = build_persona(case, cracked=cracked).lower()

    assert case["diagnosis"].lower() not in persona

    # Stronger than the substring check: no distinctive word of the diagnosis
    # may appear either. "liver" leaking on its own is still a leak.
    for w in words(case["diagnosis"]):
        if len(w) > 3:
            assert not re.search(r"\b" + re.escape(w) + r"\b", persona), (
                "diagnosis word " + repr(w) + " leaked into the persona"
            )


@pytest.mark.parametrize("case_id", CASE_IDS)
@pytest.mark.parametrize("cracked", [False, True])
def test_accepted_answers_absent_from_persona(case_id, cracked):
    case = load(case_id)
    persona = build_persona(case, cracked=cracked).lower()
    for ans in case["accepted_answers"]:
        assert not re.search(r"\b" + re.escape(ans.lower()) + r"\b", persona), (
            "accepted answer " + repr(ans) + " leaked into the persona"
        )


@pytest.mark.parametrize("case_id", CASE_IDS)
@pytest.mark.parametrize("cracked", [False, True])
def test_key_questions_absent_from_persona(case_id, cracked):
    case = load(case_id)
    persona = build_persona(case, cracked=cracked).lower()
    for q in case["key_questions"]:
        assert q.lower() not in persona, (
            "key question " + repr(q) + " leaked into the persona"
        )


# ------------------------------------------- the structural guarantee itself

@pytest.mark.parametrize("case_id", CASE_IDS)
def test_a_new_secret_field_cannot_leak(case_id):
    """This is the real test.

    A future case file grows a field nobody thought about. Because the persona
    is built by copying allowlisted fields IN, the new field is not copied and
    cannot leak. A denylist implementation fails this test; an allowlist passes
    it without anyone touching this file.
    """
    case = load(case_id)
    canary = "XYZZY-CANARY-a7f3e9"
    case["some_field_invented_next_week"] = canary
    case["notes_for_the_game_master"] = {"nested": [canary]}

    for cracked in (False, True):
        assert canary not in build_persona(case, cracked=cracked)


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_persona_only_contains_allowlisted_content(case_id):
    """Every secret field's content is absent, whole and in part."""
    case = load(case_id)
    for cracked in (False, True):
        persona = build_persona(case, cracked=cracked).lower()
        for fname in SECRET_FIELDS:
            value = case[fname]
            chunks = value if isinstance(value, list) else [value]
            for chunk in chunks:
                assert str(chunk).lower() not in persona, (
                    fname + " content " + repr(chunk) + " leaked into the persona"
                )


# ------------------------------------------------------ what clients receive

def _sample_state(case: dict, phase: str = "playing") -> GameState:
    return GameState(
        room_code="WXYZ",
        phase=phase,
        patient_name=case["name"],
        patient_age=case["age"],
        vitals={"hr": 96, "spo2": 97, "bp": "104/68", "rr": 18},
        status="stable",
        seconds_left=120,
        messages=[
            {"who": "Sara", "text": "how much do you drink", "kind": "question"},
            {"who": case["name"], "text": case["lie"], "kind": "reply"},
        ],
        players=[{"name": "Sara", "score": 0, "guessed": False}],
        reveal=None,
    )


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_diagnosis_absent_from_gamestate_json(case_id):
    case = load(case_id)
    blob = json.dumps(_sample_state(case).to_dict()).lower()

    assert case["diagnosis"].lower() not in blob
    for ans in case["accepted_answers"]:
        assert not re.search(r"\b" + re.escape(ans.lower()) + r"\b", blob), (
            "accepted answer " + repr(ans) + " leaked into GameState"
        )
    for q in case["key_questions"]:
        assert q.lower() not in blob


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_gamestate_has_no_field_beyond_the_contract(case_id):
    """The dataclass is fixed. If someone adds a field, this test makes them
    think about whether a player may see it."""
    import dataclasses

    expected = {
        "room_code", "phase", "patient_name", "patient_age", "vitals", "status",
        "seconds_left", "messages", "players", "reveal",
    }
    actual = {f.name for f in dataclasses.fields(GameState)}
    assert actual == expected, "GameState contract changed: " + str(actual ^ expected)


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_reveal_is_empty_outside_the_reveal_phase(case_id):
    case = load(case_id)
    for phase in ("lobby", "playing", "flatline"):
        state = _sample_state(case, phase=phase)
        assert state.reveal is None, "reveal populated during " + phase


# -------------------------------------------------------- the output guard

@pytest.mark.parametrize("case_id", CASE_IDS)
def test_output_guard_catches_every_accepted_answer(case_id):
    """If the model ever says the answer, the guard must catch it."""
    case = load(case_id)
    bad = patient.forbidden_pattern(case)
    for ans in case["accepted_answers"]:
        assert bad.search("I think it is my " + ans + ", doctor.")
    assert bad.search(case["diagnosis"])


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_output_guard_does_not_trip_on_innocent_speech(case_id):
    """Word boundaries, not raw substrings. 'delivered' must not read as 'liver'."""
    case = load(case_id)
    bad = patient.forbidden_pattern(case)
    for line in [
        "My wife delivered the news herself.",
        "It was a sliver of glass, nothing more.",
        "I feel worn out, that is all.",
        "Ask my wife, she dragged me here.",
    ]:
        assert not bad.search(line), "guard tripped on innocent line: " + line
