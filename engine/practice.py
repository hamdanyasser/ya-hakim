"""One learner, one patient, one encounter -- the core of the product.

The state is a plain JSON-serialisable dict so it can live in a database row
between requests. Time is wall-clock seconds; everything the monitor shows is
recomputed from timestamps, so there is no background ticker per learner.

What the learner does changes what the patient does:
- a key history topic, first time it is covered, buys a short stabilisation;
- a key treatment stabilises AND claws back some decline -- the monitor
  visibly improves, which is the feedback a real resus room gives you;
- a harmful treatment pushes him further down;
- doing nothing useful long enough and he arrests.

Nothing secret leaves through `public_view()`. Grading reads the full state.
"""

from __future__ import annotations

import time

from engine import clinical
from engine.encounter import land
from engine.mood import mood_for
from engine.vitals import dead_vitals, lie_spike_at, status_for, vitals_at

ENCOUNTER_SECONDS = 12 * 60        # hard stop for one encounter
DECLINE_SCALE = 150.0 / 600.0      # untreated, the case's red state lands near 10 min
ARREST_AT = 185.0                  # case-time seconds of effective decline
HISTORY_STABILISE = 30.0           # real seconds per newly covered key topic
TREAT_STABILISE = 60.0
TREAT_RECOVER = 110.0              # real seconds of decline clawed back
HARM_SETBACK = 90.0
MAX_QUESTIONS = 150
MAX_QUESTION_CHARS = 300


class EncounterError(ValueError):
    """A learner action that is not allowed right now."""


# ------------------------------------------------------------------ lifecycle

def new_state(case: dict, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    return {
        "v": 1,
        "case_id": case["id"],
        "started_at": now,
        "finished_at": None,
        "status": "active",          # active | awaiting_submission | complete
        "outcome": None,             # None | arrested | time_up | submitted
        "messages": [
            {"who": "patient", "text": case["opening_line"], "kind": "reply", "t": 0.0},
        ],
        "question_count": 0,
        "covered_topics": [],
        "topic_first_t": {},
        "lie_asks": 0,
        "cracked": False,
        "cracked_t": None,
        "lied_t": None,
        "deflect_i": 0,
        "stabilised": [],            # [[start, end], ...] relative seconds
        "credit": 0.0,               # real seconds of decline removed (neg = harm)
        "exams": [],
        "investigations": [],
        "treatments": [],
        "max_status": "stable",
        "notes": "",
        "submission": None,
    }


def rel(state: dict, now: float) -> float:
    end = state["finished_at"] or now
    return max(0.0, min(end, now) - state["started_at"])


def _overlap(intervals, t: float) -> float:
    spans = sorted([max(0.0, s), min(e, t)] for s, e in intervals if s < t)
    total, cur_s, cur_e = 0.0, None, None
    for s, e in spans:
        if e <= s:
            continue
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        total += cur_e - cur_s
    return total


def decline_seconds(state: dict, t: float) -> float:
    """Effective case-time decline at relative time t."""
    real = t - _overlap(state["stabilised"], t) - state["credit"]
    return max(0.0, real) * DECLINE_SCALE


def _stabilise(state: dict, t: float, seconds: float):
    start = t
    for s, e in state["stabilised"]:
        if s <= t < e:
            start = max(start, e)
    state["stabilised"].append([start, start + seconds])


def current_vitals(case: dict, state: dict, t: float) -> dict:
    if state["outcome"] == "arrested":
        return dead_vitals()
    since_lie = None if state["lied_t"] is None else t - state["lied_t"]
    return vitals_at(case, decline_seconds(state, t), seconds_since_lie=since_lie)


_RANK = {"stable": 0, "declining": 1, "critical": 2, "flatline": 3}


def advance(case: dict, state: dict, now: float | None = None) -> dict:
    """Bring the state up to `now`: record worst status, arrest, time-up."""
    now = time.time() if now is None else now
    if state["status"] != "active":
        return state
    t = rel(state, now)
    status = status_for(vitals_at(case, decline_seconds(state, t)))
    if _RANK[status] > _RANK[state["max_status"]]:
        state["max_status"] = status

    arrest_t = _arrest_time(state, t)
    if arrest_t is not None and arrest_t <= min(t, ENCOUNTER_SECONDS):
        _finish(state, state["started_at"] + arrest_t, "arrested", "awaiting_submission")
        state["max_status"] = "critical"
        _system(state, arrest_t, "The patient has gone into cardiac arrest.")
    elif t >= ENCOUNTER_SECONDS:
        _finish(state, state["started_at"] + ENCOUNTER_SECONDS, "time_up", "awaiting_submission")
        _system(state, ENCOUNTER_SECONDS, "Time is up. Commit to your diagnosis and plan.")
    return state


def _arrest_time(state: dict, t: float):
    """First relative time <= t at which decline reached ARREST_AT, or None."""
    if decline_seconds(state, t) < ARREST_AT:
        return None
    lo, hi = 0.0, t
    for _ in range(40):
        mid = (lo + hi) / 2
        if decline_seconds(state, mid) >= ARREST_AT:
            hi = mid
        else:
            lo = mid
    return hi


def _finish(state, at, outcome, status):
    state["finished_at"] = at
    state["outcome"] = outcome
    state["status"] = status


def _system(state, t, text):
    state["messages"].append({"who": "system", "text": text, "kind": "system", "t": round(t, 1)})


def _require_active(state):
    if state["status"] != "active":
        raise EncounterError("This encounter has ended.")


# -------------------------------------------------------------------- actions

def mood(case: dict, state: dict, t: float) -> str:
    if state["outcome"] == "arrested":
        return "flatline"
    since_lie = None if state["lied_t"] is None else t - state["lied_t"]
    return mood_for(
        status=status_for(vitals_at(case, decline_seconds(state, t))),
        cracked=state["cracked"],
        pressed=state["lie_asks"],
        telling_lie=lie_spike_at(since_lie) > 0,
        seconds_left=max(0, ENCOUNTER_SECONDS - t),
    )


def history_for_model(state: dict) -> list:
    """Alternating user/assistant turns for the live patient."""
    out = []
    for m in state["messages"]:
        if m["kind"] == "question":
            out.append({"role": "user", "content": m["text"]})
        elif m["kind"] == "reply" and out:
            out.append({"role": "assistant", "content": m["text"]})
    # The opening line has no question before it; drop any leading assistant
    # turns and anything that would break strict alternation.
    clean = []
    for turn in out:
        if clean and clean[-1]["role"] == turn["role"]:
            continue
        clean.append(turn)
    return clean


def ask(case: dict, state: dict, question: str, speak, now: float | None = None) -> str:
    """`speak(question, cracked, topic, mood, history, deflect_i)` returns
    (reply, deflect_i). Injected so this module never imports a network client."""
    now = time.time() if now is None else now
    advance(case, state, now)
    _require_active(state)
    question = (question or "").strip()[:MAX_QUESTION_CHARS]
    if not question:
        raise EncounterError("Ask something.")
    if state["question_count"] >= MAX_QUESTIONS:
        raise EncounterError("Question limit reached for this encounter.")
    t = rel(state, now)

    history = history_for_model(state)
    landing = land(case, question, state["lie_asks"], state["cracked"])
    state["lie_asks"] = landing.lie_asks
    if landing.cracked and not state["cracked"]:
        state["cracked_t"] = round(t, 1)
    state["cracked"] = landing.cracked

    if landing.topic is not None and landing.topic not in state["covered_topics"]:
        state["covered_topics"].append(landing.topic)
        state["topic_first_t"][landing.topic] = round(t, 1)
        _stabilise(state, t, HISTORY_STABILISE)

    current = mood(case, state, t)
    reply, state["deflect_i"] = speak(question, state["cracked"], landing.topic,
                                      current, history, state["deflect_i"])

    if landing.telling_lie:
        state["lied_t"] = t

    state["question_count"] += 1
    state["messages"].append({"who": "learner", "text": question, "kind": "question", "t": round(t, 1)})
    state["messages"].append({"who": "patient", "text": reply, "kind": "reply", "t": round(t, 1)})
    return reply


def examine(case: dict, state: dict, exam_id: str, now: float | None = None) -> str:
    now = time.time() if now is None else now
    advance(case, state, now)
    _require_active(state)
    if exam_id not in clinical.EXAM_BY_ID:
        raise EncounterError("Unknown examination.")
    for e in state["exams"]:
        if e["id"] == exam_id:
            return e["finding"]
    t = rel(state, now)
    finding = clinical.exam_finding(case, exam_id)
    state["exams"].append({"id": exam_id, "t": round(t, 1), "finding": finding})
    return finding


def order(case: dict, state: dict, test_id: str, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    advance(case, state, now)
    _require_active(state)
    item = clinical.INVESTIGATION_BY_ID.get(test_id)
    if not item:
        raise EncounterError("Unknown investigation.")
    for o in state["investigations"]:
        if o["id"] == test_id:
            return o
    t = rel(state, now)
    entry = {"id": test_id, "t": round(t, 1), "ready_t": round(t + item["delay"], 1)}
    state["investigations"].append(entry)
    return entry


def treat(case: dict, state: dict, treatment_id: str, now: float | None = None) -> str:
    now = time.time() if now is None else now
    advance(case, state, now)
    _require_active(state)
    if treatment_id not in clinical.TREATMENT_BY_ID:
        raise EncounterError("Unknown treatment.")
    if any(x["id"] == treatment_id for x in state["treatments"]):
        raise EncounterError("Already given.")
    t = rel(state, now)
    if treatment_id in case.get("key_treatments", []):
        effect = "helped"
        _stabilise(state, t, TREAT_STABILISE)
        state["credit"] += max(0.0, min(TREAT_RECOVER, t - _overlap(state["stabilised"], t) - state["credit"]))
    elif treatment_id in (case.get("harmful_treatments") or {}):
        effect = "harmed"
        state["credit"] -= HARM_SETBACK
    else:
        effect = "neutral"
    state["treatments"].append({"id": treatment_id, "t": round(t, 1), "effect": effect})
    return effect


def save_notes(state: dict, notes: str):
    state["notes"] = (notes or "")[:5000]


def submit(case: dict, state: dict, submission: dict, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    advance(case, state, now)
    if state["status"] == "complete":
        raise EncounterError("Already submitted.")
    diagnosis = (submission.get("diagnosis") or "").strip()[:200]
    if not diagnosis:
        raise EncounterError("Enter your working diagnosis.")
    differentials = [str(d).strip()[:200] for d in (submission.get("differentials") or []) if str(d).strip()][:5]
    state["submission"] = {
        "diagnosis": diagnosis,
        "differentials": differentials,
        "plan": (submission.get("plan") or "").strip()[:4000],
        "reasoning": (submission.get("reasoning") or "").strip()[:4000],
        "t": round(rel(state, now), 1),
    }
    if state["status"] == "active":
        _finish(state, now, "submitted", "complete")
    else:
        state["status"] = "complete"
    return state


# ----------------------------------------------------------------- what leaves

def chart(case: dict) -> dict:
    """What a clinician would have before walking in. No secrets, no results."""
    return {
        "name": case["name"],
        "age": case["age"],
        "sex": case.get("sex"),
        "title": case.get("title"),
        "setting": case.get("setting"),
        "description": case.get("description"),
        "presentation": case.get("presentation") or {},
        "history": case.get("history") or {},
        "vitals_at_triage": vitals_at(case, 0),
    }


def public_view(case: dict, state: dict, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    advance(case, state, now)
    t = rel(state, now)
    vit = current_vitals(case, state, t)
    investigations = []
    for o in state["investigations"]:
        item = clinical.INVESTIGATION_BY_ID[o["id"]]
        ready = t >= o["ready_t"] or state["status"] != "active"
        row = {"id": o["id"], "name": item["name"], "group": item["group"],
               "ordered_t": o["t"], "ready": ready,
               "eta_seconds": max(0, round(o["ready_t"] - t))}
        if ready:
            row.update(clinical.investigation_result(case, o["id"]))
        investigations.append(row)
    return {
        "status": state["status"],
        "outcome": state["outcome"],
        "elapsed": round(t, 1),
        "seconds_left": max(0, round(ENCOUNTER_SECONDS - t)),
        "vitals": vit,
        "monitor": "flatline" if state["outcome"] == "arrested" else status_for(vit),
        "mood": mood(case, state, t),
        "messages": [{"who": m["who"], "text": m["text"], "kind": m["kind"], "t": m["t"]}
                     for m in state["messages"]],
        "exams": [{"id": e["id"], "name": clinical.EXAM_BY_ID[e["id"]]["name"],
                   "finding": e["finding"], "t": e["t"]} for e in state["exams"]],
        "investigations": investigations,
        "treatments": [{"id": x["id"], "name": clinical.TREATMENT_BY_ID[x["id"]]["name"], "t": x["t"]}
                       for x in state["treatments"]],
        "notes": state["notes"],
        "question_count": state["question_count"],
        "submission": state["submission"],
    }
