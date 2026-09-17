"""The attending's debrief.

Two layers, deliberately:

1. A DETERMINISTIC mark sheet computed from the encounter state alone -- which
   key topics were covered, what was examined and ordered, what was given,
   whether the diagnosis matched. This is the score of record. It is
   reproducible, explainable line by line, and identical with or without a
   model, so two learners who did the same things get the same mark.

2. A NARRATIVE from the model, written as a senior clinician, grounded in the
   mark sheet and allowed to cite guidelines only by registry id. It can
   re-mark the interpersonal domain (the one thing a checklist scores badly),
   within bounds. Offline, a plain-language template stands in.

The diagnosis and the teaching points reach the learner here and only here --
the encounter is over.
"""

from __future__ import annotations

import json
import re

from engine import clinical, guidelines, llm, scoring
from engine.practice import ENCOUNTER_SECONDS

DOMAINS = [
    ("data_gathering", "Data gathering", 40),
    ("clinical_management", "Clinical management", 40),
    ("interpersonal", "Communication and professionalism", 20),
]

OPEN_STARTS = ("tell me", "can you describe", "describe", "what", "how", "walk me through",
               "could you tell", "talk me through")
EMPATHY = ("sorry", "that sounds", "must be", "i understand", "i can see", "difficult",
           "thank you for", "take your time", "i appreciate", "it's okay", "it is okay")
ICE = ("worried", "worry", "concern", "what do you think", "expect", "hoping", "afraid")
INTRO = ("my name", "i'm dr", "i am dr", "i'm doctor", "i am doctor", "hello", "good morning",
         "good afternoon", "good evening", "hi ")
SUMMARY = ("to summarise", "to summarize", "so far", "let me check", "just to recap",
           "so you're telling me", "so what i'm hearing", "have i got that right")
EXPLAIN = ("i'd like to", "i am going to", "i'm going to", "we're going to", "we need to",
           "the plan", "what happens next", "i want to explain", "let me explain")


def _questions(state):
    return [m["text"] for m in state["messages"] if m["kind"] == "question"]


def _pct(n, d):
    return 0.0 if not d else n / d


# ------------------------------------------------------------- mark sheet

def mark(case: dict, state: dict) -> dict:
    """The deterministic mark sheet. Every point has a line explaining it."""
    qs = _questions(state)
    low_qs = [q.lower() for q in qs]
    sub = state.get("submission") or {}
    plan_text = " ".join([sub.get("plan", ""), sub.get("reasoning", ""), state.get("notes", "")]).lower()

    # ---- data gathering (40)
    kq = case["key_questions"]
    reasons = case.get("key_question_reasons") or [""] * len(kq)
    covered = state["covered_topics"]
    items = []
    for i, q in enumerate(kq):
        items.append({"label": "Asked: " + q, "met": q in covered,
                      "detail": reasons[i] if i < len(reasons) else ""})
    history_pts = 20 * _pct(len(covered), len(kq))
    truth_pts = 5 if state["cracked"] else 0
    items.append({"label": "Got past the front to the real history", "met": bool(state["cracked"]),
                  "detail": "The patient was hiding one thing. Pressing the topic a second time, or asking "
                            "the right person, brings it out."})
    key_ex = case.get("key_exams") or []
    done_ex = {e["id"] for e in state["exams"]}
    for eid in key_ex:
        items.append({"label": "Examined: " + clinical.EXAM_BY_ID[eid]["name"], "met": eid in done_ex, "detail": ""})
    exam_pts = 8 * _pct(len(done_ex & set(key_ex)), len(key_ex))
    key_inv = case.get("key_investigations") or []
    ordered = {o["id"] for o in state["investigations"]}
    for tid in key_inv:
        items.append({"label": "Ordered: " + clinical.INVESTIGATION_BY_ID[tid]["name"], "met": tid in ordered, "detail": ""})
    inv_pts = 7 * _pct(len(ordered & set(key_inv)), len(key_inv))
    data = {"id": "data_gathering", "name": "Data gathering", "max": 40,
            "score": round(history_pts + truth_pts + exam_pts + inv_pts), "items": items}

    # ---- clinical management (40)
    items = []
    dx = sub.get("diagnosis", "")
    correct = scoring.match_guess(case, dx)
    partial = (not correct) and scoring.match_partial(case, dx)
    dx_pts = 15 if correct else (7 if partial else 0)
    items.append({"label": "Working diagnosis: " + (dx or "(none)"),
                  "met": correct, "partial": partial,
                  "detail": "Correct." if correct else
                            ("In the right area, but not the diagnosis." if partial else
                             "The diagnosis was " + case["diagnosis"] + ".")})
    key_tx = case.get("key_treatments") or []
    given = {x["id"] for x in state["treatments"]}
    for tid in key_tx:
        items.append({"label": "Gave: " + clinical.TREATMENT_BY_ID[tid]["name"], "met": tid in given, "detail": ""})
    tx_pts = 12 * _pct(len(given & set(key_tx)), len(key_tx))
    harmful = case.get("harmful_treatments") or {}
    harm_hits = [t for t in given if t in harmful]
    for tid in harm_hits:
        items.append({"label": "Harmful: " + clinical.TREATMENT_BY_ID[tid]["name"], "met": False,
                      "harm": True, "detail": harmful[tid]})
    harm_pts = -5 * len(harm_hits)
    points = case.get("management_points") or []
    kws = case.get("management_keywords") or [[] for _ in points]
    matched = 0
    for i, p in enumerate(points):
        words = kws[i] if i < len(kws) else []
        hit = any(w.lower() in plan_text for w in words)
        matched += hit
        items.append({"label": "Plan: " + p, "met": hit, "detail": ""})
    plan_pts = 10 * _pct(matched, len(points))
    diffs = sub.get("differentials") or []
    diff_pts = 3 if len(diffs) >= 2 else 0
    items.append({"label": "Offered at least two differentials", "met": diff_pts > 0,
                  "detail": ", ".join(diffs) if diffs else ""})
    mgmt_score = max(0, round(dx_pts + tx_pts + harm_pts + plan_pts + diff_pts))
    mgmt = {"id": "clinical_management", "name": "Clinical management", "max": 40,
            "score": min(40, mgmt_score), "items": items}

    # ---- communication (20) -- heuristic; the narrative may re-mark it
    items = []
    intro = any(any(k in q for k in INTRO) for q in low_qs[:2])
    items.append({"label": "Introduced yourself and opened the consultation", "met": intro, "detail": ""})
    opens = sum(1 for q in low_qs if q.startswith(OPEN_STARTS))
    open_ratio = _pct(opens, len(low_qs))
    items.append({"label": "Used open questions", "met": open_ratio >= 0.3,
                  "detail": "%d of %d questions were open." % (opens, len(low_qs))})
    empathy = sum(1 for q in low_qs if any(k in q for k in EMPATHY))
    items.append({"label": "Acknowledged how the patient felt", "met": empathy >= 1, "detail": ""})
    ice = any(any(k in q for k in ICE) for q in low_qs)
    items.append({"label": "Explored ideas, concerns and expectations", "met": ice, "detail": ""})
    summ = any(any(k in q for k in SUMMARY) for q in low_qs)
    items.append({"label": "Summarised back to the patient", "met": summ, "detail": ""})
    expl = any(any(k in q for k in EXPLAIN) for q in low_qs)
    items.append({"label": "Explained what would happen next", "met": expl, "detail": ""})
    comm_score = (3 if intro else 0) + round(6 * min(1.0, open_ratio / 0.5)) + \
                 (4 if empathy else 0) + (3 if ice else 0) + (2 if summ else 0) + (2 if expl else 0)
    comm = {"id": "interpersonal", "name": "Communication and professionalism", "max": 20,
            "score": min(20, comm_score), "items": items}

    total, modifiers = totals([data, mgmt, comm], state)

    return {
        "total": int(total),
        "grade": letter(total),
        "domains": [data, mgmt, comm],
        "modifiers": modifiers,
        "diagnosis": {"submitted": dx, "correct": bool(correct), "partial": bool(partial),
                      "actual": case["diagnosis"]},
        "missed": _missed(case, state, covered, done_ex, ordered, given),
        "timeline": _timeline(case, state),
        "outcome": state["outcome"],
        "duration": state["submission"]["t"] if state.get("submission") else None,
        "question_count": state["question_count"],
        "max_status": state["max_status"],
    }


ARREST_CAP = 59


def totals(domains: list, state: dict) -> tuple:
    """The overall score from the domain scores and the outcome.

    The only place the total is computed, so a re-marked domain goes back
    through the same outcome rules (an arrest still caps the score).
    """
    total = sum(d["score"] for d in domains)
    modifiers = []
    if state["outcome"] == "arrested":
        if total > ARREST_CAP:
            modifiers.append({"label": "The patient arrested", "delta": ARREST_CAP - total})
            total = ARREST_CAP
        else:
            modifiers.append({"label": "The patient arrested", "delta": 0})
    elif state["max_status"] == "critical":
        modifiers.append({"label": "The patient reached a critical state", "delta": -min(5, total)})
        total = max(0, total - 5)
    if state["max_status"] == "stable" and state["outcome"] == "submitted":
        modifiers.append({"label": "Never let the patient deteriorate", "delta": min(3, 100 - total)})
        total = min(100, total + 3)
    return int(total), modifiers


def letter(total: int) -> str:
    return "A" if total >= 85 else "B" if total >= 70 else "C" if total >= 55 else "D" if total >= 40 else "E"


def _missed(case, state, covered, done_ex, ordered, given):
    kq = case["key_questions"]
    reasons = case.get("key_question_reasons") or []
    out = []
    for i, q in enumerate(kq):
        if q not in covered:
            out.append({"kind": "question", "label": q, "why": reasons[i] if i < len(reasons) else ""})
    for eid in case.get("key_exams") or []:
        if eid not in done_ex:
            out.append({"kind": "exam", "label": clinical.EXAM_BY_ID[eid]["name"],
                        "why": clinical.exam_finding(case, eid)})
    for tid in case.get("key_investigations") or []:
        if tid not in ordered:
            out.append({"kind": "investigation", "label": clinical.INVESTIGATION_BY_ID[tid]["name"],
                        "why": clinical.investigation_result(case, tid)["text"]})
    for tid in case.get("key_treatments") or []:
        if tid not in given:
            out.append({"kind": "treatment", "label": clinical.TREATMENT_BY_ID[tid]["name"], "why": ""})
    return out


def _timeline(case, state):
    events = []
    for m in state["messages"]:
        if m["kind"] == "question":
            events.append({"t": m["t"], "kind": "question", "text": m["text"]})
        elif m["kind"] == "system":
            events.append({"t": m["t"], "kind": "system", "text": m["text"]})
    for topic, t in (state.get("topic_first_t") or {}).items():
        events.append({"t": t, "kind": "key", "text": "Covered: " + topic})
    if state.get("cracked_t") is not None:
        events.append({"t": state["cracked_t"], "kind": "key", "text": "The patient told the truth"})
    for e in state["exams"]:
        events.append({"t": e["t"], "kind": "exam", "text": clinical.EXAM_BY_ID[e["id"]]["name"]})
    for o in state["investigations"]:
        events.append({"t": o["t"], "kind": "order", "text": clinical.INVESTIGATION_BY_ID[o["id"]]["name"]})
    for x in state["treatments"]:
        events.append({"t": x["t"], "kind": "treat", "text": clinical.TREATMENT_BY_ID[x["id"]]["name"],
                       "effect": x.get("effect")})
    if state.get("submission"):
        events.append({"t": state["submission"]["t"], "kind": "submit",
                       "text": "Committed: " + state["submission"]["diagnosis"]})
    events.sort(key=lambda e: e["t"])
    return events


# ------------------------------------------------------------- narrative

NARRATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "data_gathering": {"type": "string"},
        "clinical_management": {"type": "string"},
        "interpersonal": {"type": "string"},
        "interpersonal_score": {"type": "integer"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "improvements": {"type": "array", "items": {"type": "string"}},
        "next_time": {"type": "array", "items": {"type": "string"}},
        "guideline_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "data_gathering", "clinical_management", "interpersonal",
                 "interpersonal_score", "strengths", "improvements", "next_time", "guideline_ids"],
    "additionalProperties": False,
}

ATTENDING_SYSTEM = """You are the attending physician debriefing a junior doctor after a simulated
patient encounter. You have the full transcript, everything they examined,
ordered and gave, their written diagnosis and plan, a deterministic mark sheet,
and the case's teaching notes.

Write the way a good senior does at the end of a shift: specific, warm, honest.
Quote the learner's own words where it helps. Praise what was genuinely good.
Name what was missed and say why it mattered for THIS patient. Keep every
section under 120 words. Plain English; no bullet symbols inside strings.

Re-mark the communication domain (0-20) on the transcript: introduction,
open questions, empathy, ideas/concerns/expectations, summarising, explaining
next steps, and tone under pressure.

Cite guidance ONLY by choosing ids from the registry you are given. Choose the
two to four most relevant. Never write a guideline name or URL yourself; if
nothing fits, return an empty list. Do not invent findings that are not in the
record."""


def narrative(case: dict, state: dict, sheet: dict) -> dict | None:
    if not llm.available():
        return None
    reg_ids = guidelines.for_case(case)
    payload = {
        "patient": {"name": case["name"], "age": case["age"], "sex": case.get("sex")},
        "diagnosis": case["diagnosis"],
        "teaching": case.get("teaching"),
        "management_points": case.get("management_points"),
        "transcript": [{"who": m["who"], "text": m["text"], "t": m["t"]} for m in state["messages"]],
        "exams": [{"name": clinical.EXAM_BY_ID[e["id"]]["name"], "finding": e["finding"]} for e in state["exams"]],
        "investigations": [{"name": clinical.INVESTIGATION_BY_ID[o["id"]]["name"],
                            "result": clinical.investigation_result(case, o["id"])["text"]}
                           for o in state["investigations"]],
        "treatments": [{"name": clinical.TREATMENT_BY_ID[x["id"]]["name"], "effect": x["effect"]}
                       for x in state["treatments"]],
        "submission": state.get("submission"),
        "outcome": state["outcome"],
        "mark_sheet": {"total": sheet["total"], "domains": [
            {"name": d["name"], "score": d["score"], "max": d["max"],
             "items": [{"label": i["label"], "met": i["met"]} for i in d["items"]]}
            for d in sheet["domains"]]},
    }
    user = ("ENCOUNTER RECORD\n" + json.dumps(payload, ensure_ascii=False, indent=1) +
            "\n\nGUIDELINE REGISTRY (cite by id only)\nMost relevant to this case:\n" +
            guidelines.registry_text(reg_ids) + "\n\nFull registry:\n" + guidelines.registry_text())
    return llm.json_call(ATTENDING_SYSTEM, user, NARRATIVE_SCHEMA, effort="high", max_tokens=8000)


def template_narrative(case: dict, state: dict, sheet: dict) -> dict:
    """Offline stand-in. Plain, accurate, no pretence of being a clinician."""
    d = {x["id"]: x for x in sheet["domains"]}
    missed_q = [m["label"] for m in sheet["missed"] if m["kind"] == "question"]
    missed_tx = [m["label"] for m in sheet["missed"] if m["kind"] == "treatment"]
    strengths, improvements = [], []
    for dom in sheet["domains"]:
        for item in dom["items"]:
            (strengths if item["met"] else improvements).append(item["label"])
    dx = sheet["diagnosis"]
    return {
        "summary": ("You scored %d/100 (%s). The diagnosis was %s%s." % (
            sheet["total"], sheet["grade"], case["diagnosis"],
            " and you called it" if dx["correct"] else
            (" and you were close" if dx["partial"] else ", which was not reached"))),
        "data_gathering": ("You covered %d of %d key history areas." % (
            len(state["covered_topics"]), len(case["key_questions"])) +
            (" Not asked: " + "; ".join(missed_q) + "." if missed_q else "")),
        "clinical_management": ("Management scored %d/40." % d["clinical_management"]["score"] +
            (" Not given: " + "; ".join(missed_tx) + "." if missed_tx else "")),
        "interpersonal": "Communication scored %d/20 on the checklist." % d["interpersonal"]["score"],
        "interpersonal_score": d["interpersonal"]["score"],
        "strengths": strengths[:6],
        "improvements": improvements[:6],
        "next_time": [m["label"] for m in sheet["missed"]][:5],
        "guideline_ids": [],
    }


def debrief(case: dict, state: dict) -> dict:
    """The full report. Safe to store and to show; the encounter is over."""
    sheet = mark(case, state)
    story = narrative(case, state, sheet) or None
    source = "model"
    if not story:
        story = template_narrative(case, state, sheet)
        source = "checklist"
    else:
        # The model may re-mark communication, within bounds.
        try:
            new = max(0, min(20, int(story.get("interpersonal_score", 0))))
        except (TypeError, ValueError):
            new = None
        if new is not None:
            sheet["domains"][2]["score"] = new
            sheet["total"], sheet["modifiers"] = totals(sheet["domains"], state)
            sheet["grade"] = letter(sheet["total"])
    ids = list(dict.fromkeys(list(story.get("guideline_ids") or []) + guidelines.for_case(case)))
    teaching = case.get("teaching")
    if isinstance(teaching, str):
        teaching = {"summary": teaching, "pearls": []}
    return {
        **sheet,
        "narrative": {k: story.get(k) for k in
                      ("summary", "data_gathering", "clinical_management", "interpersonal",
                       "strengths", "improvements", "next_time")},
        "narrative_source": source,
        "citations": guidelines.resolve(ids),
        "teaching": teaching or {"summary": "", "pearls": []},
        "specialty": case.get("specialty"),
        "title": case.get("title"),
        "encounter_seconds": ENCOUNTER_SECONDS,
    }
