"""Solo practice: one learner, one patient, one encounter, then the debrief.

Every action loads the encounter row, applies one engine call, saves it.

Two rules keep that correct:

- Endpoints are plain `def`, so FastAPI runs them in its threadpool. A live
  patient reply, an attending debrief or a scrypt hash can take seconds; in an
  `async def` that would stall every other request and the classroom ticker.
- Every load-modify-save of one encounter holds that encounter's lock. Without
  it, an examination clicked while the patient is still answering is read from
  the old state and then overwritten when the answer is saved, and a
  double-clicked submit grades (and bills the model) twice.

The locks are per process, matching the single-process deployment.
"""

from __future__ import annotations

import threading
import time
import weakref
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Request

from engine import authoring, clinical, grading, llm, patient, practice
from server import auth, db, guard

router = APIRouter(prefix="/api")

MIN_SECONDS_BETWEEN_ASKS = 1.5
ENCOUNTERS_PER_HOUR = 30            # per learner; each one can spend model calls
_starts = guard.RateLimit(ENCOUNTERS_PER_HOUR, 3600)


# ------------------------------------------------------------------ locking

class _Lock:
    __slots__ = ("lock", "__weakref__")

    def __init__(self):
        self.lock = threading.Lock()


_locks: "weakref.WeakValueDictionary[str, _Lock]" = weakref.WeakValueDictionary()
_locks_guard = threading.Lock()


@contextmanager
def encounter_lock(enc_id: str):
    with _locks_guard:
        holder = _locks.get(enc_id)
        if holder is None:
            holder = _Lock()
            _locks[enc_id] = holder
    with holder.lock:
        yield


# ------------------------------------------------------------------ loading

def _case_for(enc: dict) -> dict:
    """The case as it was when the encounter started.

    An instructor may edit or delete a case while learners are mid-attempt;
    the encounter keeps grading against the version it was played on.
    """
    snap = enc["state"].get("case_snapshot")
    if snap:
        return snap
    case = db.load_case_data(enc["case_id"])          # encounters from before snapshots
    if not case:
        raise HTTPException(410, "The case for this encounter no longer exists.")
    return case


def _load(enc_id: str, user: dict) -> tuple:
    enc = db.load_encounter(enc_id)
    if not enc or enc["org_id"] != user["org_id"]:
        raise HTTPException(404, "Encounter not found.")
    if enc["user_id"] != user["id"] and user["role"] == "learner":
        raise HTTPException(403, "That is not your encounter.")
    return enc, _case_for(enc)


def _save(enc: dict):
    st = enc["state"]
    enc["status"] = st["status"]
    enc["finished_at"] = st.get("finished_at")
    db.save_encounter(enc)


def _payload(enc: dict, case: dict, extra: dict | None = None) -> dict:
    out = {"id": enc["id"], "case_id": enc["case_id"], "assignment_id": enc.get("assignment_id"),
           "chart": practice.chart(case), "view": practice.public_view(case, enc["state"])}
    if enc.get("report"):
        out["report"] = enc["report"]
    if extra:
        out.update(extra)
    return out


def _speak_for(case: dict):
    """The engine asks for a reply through this so it never sees a client."""
    def speak(question, cracked, topic, mood, history, deflect_i):
        if llm.available():
            reply = patient.ask(case, history, question, cracked=cracked, mood=mood)
            if reply:
                return reply, deflect_i
            # fall through to the offline voice rather than a bland fallback
        cp = patient.CannedPatient(case)
        cp.deflect_i = deflect_i
        reply = cp.reply(question, cracked=cracked, topic=topic, mood=mood)
        return reply, cp.deflect_i
    return speak


def _card(row: dict, data: dict, best: dict) -> dict:
    """A library card. Tolerates half-written drafts: one malformed case must
    not take the whole library down with it."""
    pres = data.get("presentation")
    complaint = pres.get("complaint") if isinstance(pres, dict) else None
    mine = best.get(row["id"]) or {}
    return {
        "id": row["id"], "title": row["title"], "specialty": row["specialty"], "difficulty": row["difficulty"],
        "published": bool(row["published"]), "builtin": bool(row["builtin"]),
        "name": data.get("name"), "age": data.get("age"), "sex": data.get("sex"),
        "setting": data.get("setting"), "complaint": complaint,
        "level_card": data.get("level_card"),
        "best_score": mine.get("score"),
        "attempts": mine.get("attempts", 0),
    }


# ---------------------------------------------------------------- endpoints

@router.get("/catalog")
def catalog():
    return clinical.public_catalog()


@router.get("/cases")
def cases(request: Request):
    user = auth.require_user(request)
    rows = db.visible_cases(user["org_id"], include_unpublished=user["role"] != "learner")
    best = {r["case_id"]: r for r in db.all_(
        "SELECT case_id, MAX(score) AS score, COUNT(*) AS attempts FROM encounters "
        "WHERE user_id=? AND status='complete' GROUP BY case_id", (user["id"],))}
    out = []
    for r in rows:
        data = db.load_case_data(r["id"])
        out.append(_card(r, data if isinstance(data, dict) else {}, best))
    return {"cases": out}


@router.post("/encounters")
def start(request: Request, payload: dict):
    user = auth.require_user(request)
    case_id = guard.text(payload, "case_id", 200)
    row = db.case_row(case_id)
    if not row or (row["org_id"] and row["org_id"] != user["org_id"]):
        raise HTTPException(404, "Case not found.")
    if not row["published"] and user["role"] == "learner":
        raise HTTPException(403, "That case is not published yet.")
    case = db.load_case_data(case_id)
    problems = authoring.validate(case)
    if problems:
        # Only reachable for staff test-driving a draft; published cases are
        # validated on publish and built-ins in CI.
        raise HTTPException(400, "This case cannot be played until its checks pass: " + "; ".join(problems[:3]))
    assignment_id = guard.text(payload, "assignment_id", 200) or None
    if assignment_id:
        a = db.one("SELECT * FROM assignments WHERE id=? AND org_id=?", (assignment_id, user["org_id"]))
        if not a or a["case_id"] != case_id:
            raise HTTPException(400, "Assignment does not match this case.")
    _starts.check(user["id"], "You have started a lot of encounters this hour. Take a break and try again later.")
    now = time.time()
    state = practice.new_state(case, now)
    state["case_snapshot"] = case
    enc = {"id": db.new_id("enc_"), "org_id": user["org_id"], "user_id": user["id"], "case_id": case_id,
           "assignment_id": assignment_id, "state": state, "report": None,
           "score": None, "grade": None, "status": "active", "started_at": now, "finished_at": None}
    _save(enc)
    db.audit("encounter.start", org_id=user["org_id"], user_id=user["id"], detail={"case": case_id})
    return _payload(enc, case)


@router.get("/encounters/{enc_id}")
def get_encounter(request: Request, enc_id: str):
    user = auth.require_user(request)
    with encounter_lock(enc_id):
        enc, case = _load(enc_id, user)
        before = enc["state"]["status"]
        practice.advance(case, enc["state"])
        if enc["state"]["status"] != before:
            _save(enc)
        return _payload(enc, case)


def _action(request, enc_id, fn):
    user = auth.require_user(request)
    with encounter_lock(enc_id):
        enc, case = _load(enc_id, user)
        if enc["user_id"] != user["id"]:
            raise HTTPException(403, "Only the learner can act in their own encounter.")
        try:
            extra = fn(enc, case)
        except practice.EncounterError as e:
            practice.advance(case, enc["state"])
            _save(enc)
            raise HTTPException(409, str(e))
        _save(enc)
        return _payload(enc, case, extra)


@router.post("/encounters/{enc_id}/ask")
def ask(request: Request, enc_id: str, payload: dict):
    text = guard.text(payload, "text", practice.MAX_QUESTION_CHARS)

    def fn(enc, case):
        st = enc["state"]
        qs = [m for m in st["messages"] if m["kind"] == "question"]
        if qs and practice.rel(st, time.time()) - qs[-1]["t"] < MIN_SECONDS_BETWEEN_ASKS:
            raise practice.EncounterError("Give the patient a moment to answer.")
        reply = practice.ask(case, st, text, _speak_for(case))
        return {"reply": reply}
    return _action(request, enc_id, fn)


@router.post("/encounters/{enc_id}/examine")
def examine(request: Request, enc_id: str, payload: dict):
    exam_id = guard.text(payload, "exam_id", 60)
    return _action(request, enc_id,
                   lambda enc, case: {"finding": practice.examine(case, enc["state"], exam_id)})


@router.post("/encounters/{enc_id}/order")
def order(request: Request, enc_id: str, payload: dict):
    test_id = guard.text(payload, "test_id", 60)
    return _action(request, enc_id,
                   lambda enc, case: {"ordered": practice.order(case, enc["state"], test_id)})


@router.post("/encounters/{enc_id}/treat")
def treat(request: Request, enc_id: str, payload: dict):
    treatment_id = guard.text(payload, "treatment_id", 60)
    return _action(request, enc_id,
                   lambda enc, case: {"effect": practice.treat(case, enc["state"], treatment_id)})


@router.post("/encounters/{enc_id}/notes")
def notes(request: Request, enc_id: str, payload: dict):
    text = guard.text(payload, "notes", 5000)

    def fn(enc, case):
        practice.save_notes(enc["state"], text)
        return {}
    return _action(request, enc_id, fn)


@router.post("/encounters/{enc_id}/submit")
def submit(request: Request, enc_id: str, payload: dict):
    user = auth.require_user(request)
    if not isinstance(payload, dict):
        raise HTTPException(400, "Send a JSON object.")
    diffs = payload.get("differentials") or []
    if not isinstance(diffs, list):
        raise HTTPException(400, "'differentials' must be a list.")
    submission = {
        "diagnosis": guard.text(payload, "diagnosis", 200),
        "differentials": [str(d) for d in diffs if isinstance(d, (str, int, float))],
        "plan": guard.text(payload, "plan", 4000),
        "reasoning": guard.text(payload, "reasoning", 4000),
    }
    with encounter_lock(enc_id):
        enc, case = _load(enc_id, user)
        if enc["user_id"] != user["id"]:
            raise HTTPException(403, "Only the learner can submit their own encounter.")
        try:
            practice.submit(case, enc["state"], submission)
        except practice.EncounterError as e:
            raise HTTPException(409, str(e))
        report = grading.debrief(case, enc["state"])
        enc["report"] = report
        enc["score"] = report["total"]
        enc["grade"] = report["grade"]
        _save(enc)
    db.audit("encounter.submit", org_id=user["org_id"], user_id=user["id"],
             detail={"case": enc["case_id"], "score": report["total"]})
    return _payload(enc, case)


@router.get("/encounters/{enc_id}/report")
def report(request: Request, enc_id: str):
    user = auth.require_user(request)
    enc, case = _load(enc_id, user)
    if not enc.get("report"):
        raise HTTPException(409, "This encounter has not been submitted yet.")
    who = db.user_by_id(enc["user_id"]) or {}
    return {"id": enc["id"], "case_id": enc["case_id"], "learner": {"name": who.get("name"), "id": who.get("id")},
            "started_at": enc["started_at"], "finished_at": enc.get("finished_at"),
            "chart": practice.chart(case), "report": enc["report"],
            "transcript": enc["state"]["messages"]}


@router.get("/my/encounters")
def my_encounters(request: Request):
    user = auth.require_user(request)
    rows = db.all_(
        "SELECT e.id, e.case_id, c.title, c.specialty, e.score, e.grade, e.status, e.started_at, e.finished_at, e.assignment_id "
        "FROM encounters e LEFT JOIN cases c ON c.id=e.case_id WHERE e.user_id=? ORDER BY e.started_at DESC LIMIT 200",
        (user["id"],))
    done = [r for r in rows if r["status"] == "complete" and r["score"] is not None]
    summary = {
        "attempts": len(rows),
        "completed": len(done),
        "average": round(sum(r["score"] for r in done) / len(done)) if done else None,
        "best": max((r["score"] for r in done), default=None),
        "trend": [r["score"] for r in reversed(done[:12])],
    }
    return {"encounters": rows, "summary": summary}
