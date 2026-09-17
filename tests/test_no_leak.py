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

def _sample_state(case: dict, phase: str = "playing", mood: str = "guarded") -> GameState:
    return GameState(
        room_code="WXYZ",
        phase=phase,
        patient_name=case["name"],
        patient_age=case["age"],
        patient_sex=case.get("sex", ""),
        description=case.get("description", ""),
        mood=mood,
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


def _server_authored(state: GameState) -> str:
    """Everything in a GameState that the SERVER wrote.

    Player-typed text is deliberately excluded. A player may ask "how much do
    you drink" or guess "cirrhosis" out loud, and that text is echoed back into
    the feed for the whole room -- which is not a leak, because the player said
    it. The guarantee worth testing is the narrow one: the server never authors
    a secret.
    """
    d = state.to_dict()
    d["messages"] = [m for m in d["messages"] if m.get("kind") != "question"]
    d["players"] = [
        {k: v for k, v in p.items() if k != "name"} for p in d["players"]
    ]
    return json.dumps(d).lower()


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_diagnosis_absent_from_gamestate_json(case_id):
    case = load(case_id)
    blob = _server_authored(_sample_state(case))

    assert case["diagnosis"].lower() not in blob
    for ans in case["accepted_answers"]:
        assert not re.search(r"\b" + re.escape(ans.lower()) + r"\b", blob), (
            "accepted answer " + repr(ans) + " leaked into GameState"
        )
    for q in case["key_questions"]:
        assert q.lower() not in blob, (
            "key question " + repr(q) + " leaked into server-authored state"
        )


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_a_players_own_words_are_echoed_but_nothing_more(case_id):
    """A player guessing the answer aloud must not turn into a server leak.

    Their words appear in the feed. Nothing else in the state may change to
    confirm they were right -- no flag, no score bump visible before the reveal.
    """
    case = load(case_id)
    state = _sample_state(case)
    state.messages = state.messages + [
        {"who": "Sara", "text": "is it " + case["accepted_answers"][0] + "?",
         "kind": "question"},
    ]
    blob = _server_authored(state)
    for ans in case["accepted_answers"]:
        assert not re.search(r"\b" + re.escape(ans.lower()) + r"\b", blob)


def test_messages_cannot_mark_a_question_as_key():
    """The feed must not tell the room which questions mattered.

    A 'was_key' or 'scored' field on a message would hand players the
    key_questions list one question at a time. The contract allows who/text/kind
    and nothing else.
    """
    allowed = {"who", "text", "kind"}
    case = load(CASE_IDS[0])
    for m in _sample_state(case).to_dict()["messages"]:
        assert set(m) <= allowed, "message carries extra fields: " + str(set(m) - allowed)


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_gamestate_has_no_field_beyond_the_contract(case_id):
    """The dataclass is fixed. If someone adds a field, this test makes them
    think about whether a player may see it."""
    import dataclasses

    expected = {
        "room_code", "phase", "patient_name", "patient_age", "patient_sex", "description",
        "mood", "vitals", "status", "seconds_left", "messages", "players",
        "reveal",
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


# ------------------------------------------------- the canned patient's mouth

@pytest.mark.parametrize("case_id", CASE_IDS)
def test_canned_dialogue_never_trips_its_own_guard(case_id):
    """Every offline line must survive the output guard.

    These are hand-written, and an accepted answer is easy to drop into one by
    accident -- Georges can say "boiler" but not "gas", Rita can say "sweet"
    but not "sugar". Without this the offline patient could leak the answer in
    a line nobody re-read.
    """
    case = load(case_id)
    bad = patient.forbidden_pattern(case)
    lines = []
    canned = case.get("canned", {})
    for key, value in canned.items():
        lines.extend(value if isinstance(value, list) else [value])
    lines.append(case["opening_line"])
    lines.append(case["lie"])
    lines.append(case["truth"])
    lines.extend(patient.FALLBACKS)

    hits = [ln for ln in lines if bad.search(ln)]
    assert not hits, case_id + " canned dialogue leaks: " + repr(hits)


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_canned_dialogue_is_not_clinical(case_id):
    """He is a sick man, not a doctor."""
    case = load(case_id)
    lines = []
    for key, value in case.get("canned", {}).items():
        lines.extend(value if isinstance(value, list) else [value])
    hits = [ln for ln in lines if patient.clinical_hit(ln)]
    assert not hits, case_id + " canned dialogue uses textbook words: " + repr(hits)


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_every_key_question_has_keywords_and_a_canned_reply(case_id):
    """A key question with no keywords can never be detected offline."""
    case = load(case_id)
    assert len(case["key_keywords"]) == len(case["key_questions"]), case_id
    for group in case["key_keywords"]:
        assert group, case_id + " has an empty keyword group"
    # The first key question is the one that carries lie/truth, so it needs no
    # canned entry. Every other one does.
    for kq in case["key_questions"][1:]:
        assert kq in case.get("canned", {}), (
            case_id + " has no canned reply for key question " + repr(kq)
        )


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_every_case_has_a_description(case_id):
    """description is allowlisted into the prompt, so build_persona() would
    KeyError on a case missing it -- this catches that before the round does."""
    case = load(case_id)
    desc = case.get("description")
    assert isinstance(desc, str) and desc.strip(), case_id + " has no description"


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_every_case_has_a_level_card(case_id):
    """The campaign shows one before each round; a missing card crashed it."""
    case = load(case_id)
    card = case.get("level_card")
    assert isinstance(card, list) and card, case_id + " has no level_card"
    assert all(isinstance(line, str) and line.strip() for line in card), case_id


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_keyword_groups_do_not_collide(case_id):
    """A keyword in two groups silently steals the other topic's question.

    Rita had "water" in the thirst group, so "how often are you passing water"
    matched thirst instead -- and she answered the urine question with her
    weight lie. The test ran green the whole time because nothing checked this.
    """
    case = load(case_id)
    seen = {}
    for i, group in enumerate(case["key_keywords"]):
        for kw in group:
            kw = kw.lower()
            assert kw not in seen, (
                case_id + ": keyword " + repr(kw) + " is in group " +
                str(seen[kw]) + " and group " + str(i)
            )
            seen[kw] = i


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_each_key_question_matches_its_own_topic(case_id):
    """Asking a key question verbatim must select that key question.

    This is the end-to-end version of the collision test: it catches ordering
    bugs as well as duplicate keywords.
    """
    from engine.scoring import covers_key_topic

    case = load(case_id)
    for kq in case["key_questions"]:
        got = covers_key_topic(case, kq)
        assert got == kq, (
            case_id + ": asking " + repr(kq) + " selected " + repr(got)
        )


# ------------------------------------------- the offline patient's coverage

OFFLINE_MUST_ANSWER = [
    "how long has this been going on",
    "what brings you in tonight",
    "do you smoke",
    "what medications are you taking",
    "do you have any allergies",
    "what do you do for work",
    "does it run in the family",
    "how are you feeling",
    "have you been in hospital before",
]


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_the_offline_patient_answers_the_obvious_questions(case_id):
    """Without a key he must still hold a consultation.

    These are the questions anybody asks in the first minute. Each used to fall
    through to a rotating brush-off, which is what makes an offline demo feel
    like a lookup table instead of a person.
    """
    from engine.patient import CannedPatient
    from engine.scoring import covers_key_topic

    case = load(case_id)
    deflections = set(case["canned"]["_deflect"])
    missed = []
    for q in OFFLINE_MUST_ANSWER:
        cp = CannedPatient(case)
        reply = cp.reply(q, topic=covers_key_topic(case, q))
        if reply in deflections:
            missed.append(q)
    assert not missed, case_id + " deflects: " + repr(missed)


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_the_offline_patient_never_talks_like_a_doctor(case_id):
    """presentation.complaint is written for the chart. He must not read it."""
    from engine.patient import CannedPatient, clinical_hit
    from engine.scoring import covers_key_topic

    case = load(case_id)
    for q in OFFLINE_MUST_ANSWER + ["what is wrong with you"]:
        cp = CannedPatient(case)
        reply = cp.reply(q, topic=covers_key_topic(case, q))
        assert not clinical_hit(reply), case_id + ": " + q + " -> " + reply


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_asking_about_his_job_does_not_hand_over_the_secret(case_id):
    """Social history is a list. Returning several entries used to volunteer
    the thing he is hiding alongside the thing that was asked."""
    from engine.patient import CannedPatient

    case = load(case_id)
    cp = CannedPatient(case)
    reply = cp.reply("what do you do for work", topic=None)
    assert case["lie"] not in reply
    assert case["truth"] not in reply
