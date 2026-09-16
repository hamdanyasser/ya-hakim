"""Solo practice: the encounter engine, the mark sheet, and the leak guarantee
for everything a learner can see before the debrief. Offline, no key."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from engine import clinical, grading, practice, patient
from engine.patient import CannedPatient

CASES_DIR = Path(__file__).resolve().parent.parent / "cases"
CASE_IDS = sorted(p.stem for p in CASES_DIR.glob("*.json"))


def load(case_id):
    with open(CASES_DIR / (case_id + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(params=CASE_IDS)
def case(request):
    return load(request.param)


def canned_speaker(case):
    def speak(question, cracked, topic, mood, history, deflect_i):
        cp = CannedPatient(case)
        cp.deflect_i = deflect_i
        return cp.reply(question, cracked=cracked, topic=topic, mood=mood), cp.deflect_i
    return speak


def secrets_of(case):
    words = set(case["accepted_answers"]) | set(case.get("partial_answers", []))
    words |= {w for w in re.findall(r"[a-z]{4,}", case["diagnosis"].lower())}
    return {w.lower() for w in words}


def assert_no_secret(case, blob: str, where: str):
    low = blob.lower()
    assert case["diagnosis"].lower() not in low, where + " contains the diagnosis"
    for ans in case["accepted_answers"]:
        assert not re.search(r"\b" + re.escape(ans.lower()) + r"\b", low), where + " leaks " + repr(ans)
    for q in case["key_questions"]:
        assert q.lower() not in low, where + " leaks key question " + repr(q)


# ---------------------------------------------------------------- the leak

def test_chart_has_no_secrets(case):
    assert_no_secret(case, json.dumps(practice.chart(case)), "chart")


def test_public_view_has_no_secrets_before_submission(case):
    """Everything a learner sees WITHOUT earning it: the patient's words,
    the monitor, the mood, the timers. Exam findings and results are excluded
    on purpose -- they are revealed by an action and are supposed to point at
    the answer (that is the clinical process); what they may never do is name
    it, which test_results_never_name_the_diagnosis covers."""
    t = {"now": 1000.0}
    st = practice.new_state(case, t["now"])
    speak = canned_speaker(case)
    for q in case["key_questions"]:
        t["now"] += 5
        practice.ask(case, st, q, speak, now=t["now"])
    t["now"] += 5
    practice.ask(case, st, "what's wrong with you?", speak, now=t["now"])
    t["now"] += 120
    view = practice.public_view(case, st, now=t["now"])
    # Player-typed questions echo back; strip them, they are the player's words.
    view["messages"] = [m for m in view["messages"] if m["kind"] != "question"]
    assert_no_secret(case, json.dumps(view), "public_view")


def test_catalog_is_case_independent():
    cat = clinical.public_catalog()
    assert {"exams", "investigations", "treatments"} <= set(cat)
    assert "normal" not in json.dumps(cat)


# ------------------------------------------------------------- mechanics

def test_key_history_stabilises_and_truth_comes_out(case):
    t = {"now": 0.0}
    st = practice.new_state(case, 0.0)
    speak = canned_speaker(case)
    first = case["key_questions"][0]
    practice.ask(case, st, first, speak, now=5.0)
    assert st["lie_asks"] == 1 and not st["cracked"]
    assert st["lied_t"] == pytest.approx(5.0)
    assert st["stabilised"], "a key topic should buy time"
    practice.ask(case, st, "and again, " + first, speak, now=8.0)
    assert st["cracked"]
    replies = [m["text"] for m in st["messages"] if m["kind"] == "reply"]
    assert case["lie"] in replies and case["truth"] in replies


def test_results_arrive_after_turnaround(case):
    st = practice.new_state(case, 0.0)
    tid = case["key_investigations"][0]
    delay = clinical.INVESTIGATION_BY_ID[tid]["delay"]
    practice.order(case, st, tid, now=1.0)
    before = practice.public_view(case, st, now=1.0 + delay / 2)["investigations"][0]
    after = practice.public_view(case, st, now=2.0 + delay)["investigations"][0]
    assert not before["ready"] and "text" not in before
    assert after["ready"] and after["text"]


def test_untreated_patient_arrests_and_can_still_submit(case):
    st = practice.new_state(case, 0.0)
    practice.advance(case, st, now=practice.ENCOUNTER_SECONDS + 1)
    assert st["outcome"] in ("arrested", "time_up")
    assert st["status"] == "awaiting_submission"
    with pytest.raises(practice.EncounterError):
        practice.ask(case, st, "hello", canned_speaker(case), now=practice.ENCOUNTER_SECONDS + 2)
    practice.submit(case, st, {"diagnosis": "unsure"}, now=practice.ENCOUNTER_SECONDS + 3)
    assert st["status"] == "complete"


def test_key_treatment_improves_the_monitor(case):
    st = practice.new_state(case, 0.0)
    now = 300.0
    practice.advance(case, st, now)
    hr_before = practice.current_vitals(case, st, now)["hr"]
    practice.treat(case, st, case["key_treatments"][0], now=now)
    hr_after = practice.current_vitals(case, st, now)["hr"]
    assert hr_after < hr_before, "a key treatment must visibly help"


def test_harmful_treatment_sets_him_back(case):
    harmful = list(case.get("harmful_treatments") or {})
    if not harmful:
        pytest.skip("case has no harmful treatments")
    st = practice.new_state(case, 0.0)
    now = 120.0
    hr_before = practice.current_vitals(case, st, now)["hr"]
    practice.treat(case, st, harmful[0], now=now)
    assert practice.current_vitals(case, st, now)["hr"] > hr_before


# ------------------------------------------------------------ the mark sheet

def perfect_run(case):
    st = practice.new_state(case, 0.0)
    speak = canned_speaker(case)
    now = 1.0
    practice.ask(case, st, "Hello, my name is Dr Sara. What has been worrying you most?", speak, now=now)
    for q in case["key_questions"]:
        now += 3
        practice.ask(case, st, "Could you tell me, " + q + "?", speak, now=now)
    now += 3
    practice.ask(case, st, "and again, " + case["key_questions"][0] + "? I'm sorry, that sounds hard.", speak, now=now)
    for eid in case.get("key_exams", []):
        practice.examine(case, st, eid, now=now)
    for tid in case.get("key_investigations", []):
        practice.order(case, st, tid, now=now)
    for tid in case.get("key_treatments", []):
        practice.treat(case, st, tid, now=now)
    practice.ask(case, st, "So far you've told me a lot. I'm going to explain what happens next.", speak, now=now + 3)
    plan = " ".join(" ".join(g) for g in case.get("management_keywords", []))
    practice.submit(case, st, {"diagnosis": case["accepted_answers"][0], "differentials": ["a", "b"],
                               "plan": plan, "reasoning": "because"}, now=now + 10)
    return st


def test_perfect_run_scores_high_and_nothing_scores_low(case):
    good = grading.mark(case, perfect_run(case))
    assert good["total"] >= 85, json.dumps(good["domains"], indent=1)
    assert good["diagnosis"]["correct"]

    st = practice.new_state(case, 0.0)
    practice.submit(case, st, {"diagnosis": "no idea"}, now=5.0)
    bad = grading.mark(case, st)
    assert bad["total"] <= 20
    assert not bad["diagnosis"]["correct"]
    assert bad["missed"], "everything should be listed as missed"


def test_partial_diagnosis_gets_partial_credit(case):
    if not case.get("partial_answers"):
        pytest.skip("no partial answers")
    st = practice.new_state(case, 0.0)
    practice.submit(case, st, {"diagnosis": "possibly " + case["partial_answers"][0]}, now=5.0)
    sheet = grading.mark(case, st)
    assert sheet["diagnosis"]["partial"] and not sheet["diagnosis"]["correct"]


def test_offline_debrief_is_complete_and_cites_only_registry(case):
    rep = grading.debrief(case, perfect_run(case))
    assert rep["narrative_source"] == "checklist"
    assert rep["narrative"]["summary"]
    assert rep["teaching"]["summary"]
    for c in rep["citations"]:
        assert c["url"].startswith("http")
    assert {c["id"] for c in rep["citations"]} == set(case.get("guidelines", []))


def test_arrest_caps_the_score(case):
    st = perfect_run(case)
    st["outcome"] = "arrested"
    assert grading.mark(case, st)["total"] <= 59


# ------------------------------------------------------------ the catalog

def test_every_case_only_references_catalog_ids(case):
    for eid in list(case.get("exam", {})) + list(case.get("key_exams", [])):
        assert eid in clinical.EXAM_BY_ID, eid
    for tid in list(case.get("investigations", {})) + list(case.get("key_investigations", [])):
        assert tid in clinical.INVESTIGATION_BY_ID, tid
    for tid in list(case.get("key_treatments", [])) + list(case.get("harmful_treatments", {})):
        assert tid in clinical.TREATMENT_BY_ID, tid


def test_results_never_name_the_diagnosis(case):
    words = secrets_of(case)
    for tid, res in (case.get("investigations") or {}).items():
        text = res if isinstance(res, str) else res["result"]
        assert case["diagnosis"].lower() not in text.lower(), tid
    for eid, text in (case.get("exam") or {}).items():
        assert case["diagnosis"].lower() not in text.lower(), eid


def test_secret_split_is_disjoint():
    assert not set(patient.SECRET_FIELDS) & set(patient.ENGINE_ONLY_FIELDS)
    assert not set(patient.ALLOWED_IN_PROMPT) & set(patient.ENGINE_ONLY_FIELDS)
