"""Case authoring: drafting with the model, and validation for every case.

A case is only as safe as its validation. `validate()` is the same bar the
built-in cases pass in CI, applied to anything an instructor writes or the
model drafts: the answer must be absent from the persona, keyword groups must
not collide, every key question must have an offline reply that survives the
output guard, and the vitals must actually pass through all three colours.
"""

from __future__ import annotations

import json
import re

from engine import clinical, guidelines, llm, patient, scoring
from engine.vitals import status_for, vitals_at

ROUND_SECONDS = 150

_ID_ITEM = {"type": "object", "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
            "required": ["id", "text"], "additionalProperties": False}
_STR_LIST = {"type": "array", "items": {"type": "string"}}
_VITALS = {"type": "object",
           "properties": {k: {"type": "number"} for k in ("hr", "spo2", "sys", "dia", "rr")},
           "required": ["hr", "spo2", "sys", "dia", "rr"], "additionalProperties": False}

CASE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "specialty": {"type": "string"},
        "setting": {"type": "string"},
        "name": {"type": "string"},
        "age": {"type": "integer"},
        "sex": {"type": "string", "enum": ["male", "female"]},
        "description": {"type": "string"},
        "presentation": {"type": "object",
                         "properties": {"complaint": {"type": "string"}, "duration": {"type": "string"},
                                        "triage_note": {"type": "string"}},
                         "required": ["complaint", "duration", "triage_note"], "additionalProperties": False},
        "history": {"type": "object",
                    "properties": {k: _STR_LIST for k in ("past_medical", "medications", "allergies", "social", "family")},
                    "required": ["past_medical", "medications", "allergies", "social", "family"],
                    "additionalProperties": False},
        "opening_line": {"type": "string"},
        "personality": {"type": "string"},
        "symptoms": _STR_LIST,
        "lie_topic": {"type": "string"},
        "lie": {"type": "string"},
        "truth": {"type": "string"},
        "cracks_when": {"type": "string"},
        "crack_keywords": _STR_LIST,
        "red_herrings": _STR_LIST,
        "diagnosis": {"type": "string"},
        "accepted_answers": _STR_LIST,
        "partial_answers": _STR_LIST,
        "key_questions": _STR_LIST,
        "key_keywords": {"type": "array", "items": _STR_LIST},
        "key_question_reasons": _STR_LIST,
        "canned": {"type": "array", "items": _ID_ITEM},
        "greeting": {"type": "string"},
        "whats_wrong": {"type": "string"},
        "deflections": _STR_LIST,
        "exam": {"type": "array", "items": _ID_ITEM},
        "investigations": {"type": "array", "items": _ID_ITEM},
        "key_exams": _STR_LIST,
        "key_investigations": _STR_LIST,
        "key_treatments": _STR_LIST,
        "harmful_treatments": {"type": "array", "items": _ID_ITEM},
        "management_points": _STR_LIST,
        "management_keywords": {"type": "array", "items": _STR_LIST},
        "teaching": {"type": "object",
                     "properties": {"summary": {"type": "string"}, "pearls": _STR_LIST},
                     "required": ["summary", "pearls"], "additionalProperties": False},
        "guidelines": _STR_LIST,
        "vitals_start": _VITALS,
        "vitals_decline": _VITALS,
        "level_card": _STR_LIST,
    },
    "required": [
        "title", "specialty", "setting", "name", "age", "sex", "description", "presentation",
        "history", "opening_line", "personality", "symptoms", "lie_topic", "lie", "truth",
        "cracks_when", "crack_keywords", "red_herrings", "diagnosis", "accepted_answers",
        "partial_answers", "key_questions", "key_keywords", "key_question_reasons", "canned",
        "greeting", "whats_wrong", "deflections", "exam", "investigations", "key_exams",
        "key_investigations", "key_treatments", "harmful_treatments", "management_points",
        "management_keywords", "teaching", "guidelines", "vitals_start", "vitals_decline",
        "level_card",
    ],
    "additionalProperties": False,
}

AUTHOR_SYSTEM = """You write patient cases for a clinical-reasoning simulator used by medical
and nursing schools. A learner interviews the patient in plain language,
examines, orders investigations, treats, and commits to a diagnosis and plan.
A senior then debriefs them.

The patient is ONE person hiding ONE thing (the "lie" / "truth" pair), with a
believable life. Everything they say is plain speech -- the words a real
person would use, never textbook words. The patient must never be able to
name their own diagnosis, so no accepted_answer word may appear in
description, history, personality, symptoms, lie, truth, cracks_when,
red_herrings, opening_line, greeting, whats_wrong, deflections or canned.

RULES
- key_questions: 4 to 6 history topics that matter. The FIRST one is the topic
  the patient lies about. key_keywords[i] lists 8-15 lower-case words a
  learner might use to ask about topic i. No word may appear in two groups.
  key_question_reasons[i]: one sentence on why topic i matters clinically.
- canned: one {id, text} per key_question EXCEPT the first (the engine serves
  lie/truth for that one). id = the key question text verbatim.
- deflections: 5 lines the patient says when a question covers nothing.
- crack_keywords: 2-4 phrases (a relative's name, "honest with me") that make
  the patient drop the front at once.
- exam: {id, text} for each examination that is ABNORMAL, id from the exam
  catalog. investigations: {id, text} for each ABNORMAL result, id from the
  catalog, realistic SI values. Do not write the diagnosis name in a result.
- key_exams / key_investigations / key_treatments: catalog ids that a good
  clinician would do. harmful_treatments: {id, text} where text says why it
  harms THIS patient.
- management_points: 5-7 lines a debrief would expect in the plan;
  management_keywords[i]: 3-6 lower-case stems that would match a learner
  writing that point.
- partial_answers: terms that show the right area without being the answer.
- guidelines: ids from the registry only.
- vitals_decline is per minute of case time and MUST take the patient from
  stable to critical (spo2 < 88 or hr > 140) within 150 seconds of case time,
  passing through declining (spo2 < 94 or hr > 115) on the way. Start stable.
- level_card: three short lines shown before the encounter.
- The case must be medically accurate for the stated diagnosis and consistent
  throughout. It is for education; write it as a clinician would.

CATALOG IDS
""" + "Exams: " + ", ".join(e["id"] for e in clinical.EXAMS) + "\nInvestigations: " + \
    ", ".join(i["id"] for i in clinical.INVESTIGATIONS) + "\nTreatments: " + \
    ", ".join(t["id"] for t in clinical.TREATMENTS) + "\n\nGUIDELINE REGISTRY\n" + guidelines.registry_text()


def draft(brief: str, specialty: str = "", difficulty: str = "standard",
          language: str = "English") -> dict | None:
    """Ask the model for a case. Returns a normalised case dict or None."""
    if not llm.available():
        return None
    user = ("Write one case.\nBrief: " + (brief or "an adult presenting to the emergency department") +
            "\nSpecialty: " + (specialty or "acute medicine") +
            "\nDifficulty: " + difficulty +
            "\nLanguage the patient speaks: " + language)
    raw = llm.json_call(AUTHOR_SYSTEM, user, CASE_SCHEMA, effort="xhigh", max_tokens=32000, timeout=300.0)
    if not raw:
        return None
    return normalise(raw)


def normalise(raw: dict) -> dict:
    """The schema uses arrays of {id, text} because structured outputs want
    fixed shapes; the engine wants dicts. Convert, and build `canned`."""
    case = dict(raw)
    case["canned"] = {c["id"]: c["text"] for c in raw.get("canned", []) if isinstance(c, dict)}
    case["canned"]["_greeting"] = raw.get("greeting", "Hello, doctor.")
    case["canned"]["_whats_wrong"] = raw.get("whats_wrong", "I don't know. That's why I'm here.")
    case["canned"]["_deflect"] = list(raw.get("deflections") or ["I couldn't say."])
    for k in ("greeting", "whats_wrong", "deflections"):
        case.pop(k, None)
    case["exam"] = {e["id"]: e["text"] for e in raw.get("exam", []) if isinstance(e, dict)}
    case["investigations"] = {e["id"]: e["text"] for e in raw.get("investigations", []) if isinstance(e, dict)}
    case["harmful_treatments"] = {e["id"]: e["text"] for e in raw.get("harmful_treatments", []) if isinstance(e, dict)}
    case["key_keywords"] = [[str(w).lower().strip() for w in g] for g in raw.get("key_keywords", [])]
    case["accepted_answers"] = [str(a).lower().strip() for a in raw.get("accepted_answers", [])]
    case["partial_answers"] = [str(a).lower().strip() for a in raw.get("partial_answers", [])]
    case.setdefault("id", slug(case.get("title") or case.get("name") or "case"))
    return case


def slug(text) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:48] or "case"


REQUIRED = [
    "name", "age", "description", "personality", "symptoms", "lie", "truth", "cracks_when",
    "red_herrings", "opening_line", "diagnosis", "accepted_answers", "key_questions",
    "key_keywords", "canned", "vitals_start", "vitals_decline", "level_card",
]


TYPES = {
    "name": str, "age": int, "description": str, "personality": str, "symptoms": list,
    "lie": str, "truth": str, "cracks_when": str, "red_herrings": list, "opening_line": str,
    "diagnosis": str, "accepted_answers": list, "key_questions": list, "key_keywords": list,
    "canned": dict, "vitals_start": dict, "vitals_decline": dict, "level_card": list,
}
OPTIONAL_TYPES = {
    "partial_answers": list, "key_question_reasons": list, "crack_keywords": list,
    "history": dict, "presentation": dict, "exam": dict, "investigations": dict,
    "key_exams": list, "key_investigations": list, "key_treatments": list,
    "harmful_treatments": dict, "management_points": list, "management_keywords": list,
    "teaching": (dict, str), "guidelines": list, "title": str, "sex": str, "lie_topic": str,
}


def validate(case) -> list:
    """Everything that would make this case unsafe or unplayable. Empty = ok.

    Never raises. The editor calls this on arbitrary JSON an instructor typed,
    so a wrong type must come back as a problem to fix, not a server error.
    """
    if not isinstance(case, dict):
        return ["the case must be a JSON object"]
    problems = []
    for f, t in TYPES.items():
        if f in case and case[f] not in ("", [], {}, None) and not isinstance(case[f], t):
            problems.append("%s has the wrong type (expected %s)" % (f, t.__name__))
    for f, t in OPTIONAL_TYPES.items():
        if case.get(f) is not None and not isinstance(case[f], t):
            problems.append("%s has the wrong type" % f)
    if isinstance(case.get("age"), bool):
        problems.append("age has the wrong type (expected int)")
    if problems:
        return problems
    try:
        return _validate(case)
    except Exception as e:                     # malformed nested content
        return ["the case is malformed (%s: %s)" % (type(e).__name__, str(e)[:120])]


def _validate(case: dict) -> list:
    problems = []
    for f in REQUIRED:
        if f not in case or case[f] in ("", [], {}, None):
            problems.append("missing field: " + f)
    if problems:
        return problems

    kq, kk = case["key_questions"], case["key_keywords"]
    if len(kq) != len(kk):
        problems.append("key_keywords must have one group per key question")
    if len(kq) < 3:
        problems.append("at least three key questions are needed")
    if not all(g for g in kk):
        problems.append("a keyword group is empty")
    reasons = case.get("key_question_reasons") or []
    if reasons and len(reasons) != len(kq):
        problems.append("key_question_reasons must match key_questions")

    seen = {}
    for i, group in enumerate(kk):
        for kw in group:
            kw = kw.lower()
            if kw in seen and seen[kw] != i:
                problems.append("keyword '%s' is in groups %d and %d" % (kw, seen[kw], i))
            seen[kw] = i
    for q in kq:
        if scoring.covers_key_topic(case, q) != q:
            problems.append("asking '%s' verbatim does not select its own topic" % q)

    canned = case.get("canned") or {}
    for q in kq[1:]:
        if not canned.get(q):
            problems.append("no canned reply for key question: " + q)
    for k in ("_whats_wrong", "_deflect"):
        if not canned.get(k):
            problems.append("canned." + k + " is missing")

    # The answer must be absent from everything the model or the offline voice
    # could ever say.
    try:
        bad = patient.forbidden_pattern(case)
    except re.error:
        return problems + ["accepted_answers contain an unusable pattern"]
    lines = [case["opening_line"], case["lie"], case["truth"]]
    for v in canned.values():
        lines.extend(v if isinstance(v, list) else [v])
    for ln in lines:
        if bad.search(ln):
            problems.append("offline line leaks the answer: " + ln[:60])
        if patient.clinical_hit(ln):
            problems.append("offline line uses a textbook word: " + ln[:60])
    for cracked in (False, True):
        persona = patient.build_persona(case, cracked=cracked).lower()
        if bad.search(persona):
            m = bad.search(persona)
            problems.append("persona leaks the answer (%s) -- check description, history, "
                            "symptoms, lie, truth, red_herrings" % m.group(0))
        for w in re.findall(r"[a-z]{4,}", case["diagnosis"].lower()):
            if re.search(r"\b" + re.escape(w) + r"\b", persona):
                problems.append("diagnosis word '%s' appears in the persona" % w)
        for q in kq:
            if q.lower() in persona:
                problems.append("key question text appears in the persona: " + q)

    for f in ("key_exams",):
        for x in case.get(f) or []:
            if x not in clinical.EXAM_BY_ID:
                problems.append("unknown exam id: " + x)
    for x in case.get("exam") or {}:
        if x not in clinical.EXAM_BY_ID:
            problems.append("unknown exam id: " + x)
    for x in list(case.get("key_investigations") or []) + list(case.get("investigations") or {}):
        if x not in clinical.INVESTIGATION_BY_ID:
            problems.append("unknown investigation id: " + x)
    for x in list(case.get("key_treatments") or []) + list(case.get("harmful_treatments") or {}):
        if x not in clinical.TREATMENT_BY_ID:
            problems.append("unknown treatment id: " + x)
    for g in case.get("guidelines") or []:
        if g not in guidelines.BY_ID:
            problems.append("unknown guideline id: " + g)
    mp, mk = case.get("management_points") or [], case.get("management_keywords") or []
    if mp and len(mk) != len(mp):
        problems.append("management_keywords must match management_points")

    try:
        seen_status = {status_for(vitals_at(case, t)) for t in range(ROUND_SECONDS + 1)}
        if status_for(vitals_at(case, 0)) != "stable":
            problems.append("the patient must start stable")
        if seen_status != {"stable", "declining", "critical"}:
            problems.append("vitals must pass through stable, declining and critical within "
                            "%d seconds; saw %s" % (ROUND_SECONDS, sorted(seen_status)))
    except (KeyError, TypeError):
        problems.append("vitals_start / vitals_decline are malformed")
    return sorted(set(problems))


def to_json(case: dict) -> str:
    return json.dumps(case, ensure_ascii=False, indent=2)
