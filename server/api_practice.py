"""Solo practice: one learner, one patient, one encounter, then the debrief.

Every action loads the encounter row, applies one engine call, saves it. The
engine is pure and the state is a document, so this is the whole
concurrency story: one learner, one encounter, one row.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request

from engine import clinical, grading, llm, patient, practice
from server import auth, db

router = APIRouter(prefix="/api")

MIN_SECONDS_BETWEEN_ASKS = 1.5


def _load(enc_id: str, user: dict) -> tuple:
    enc = db.load_encounter(enc_id)
    if not enc or enc["org_id"] != user["org_id"]:
        raise HTTPException(404, "Encounter not found.")
    if enc["user_id"] != user["id"] and user["role"] == "learner":
        raise HTTPException(403, "That is not your encounter.")
    case = db.load_case_data(enc["case_id"])
    if not case:
        raise HTTPException(410, "The case for this encounter no longer exists.")
    return enc, case


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


@router.get("/catalog")
async def catalog():
    return clinical.public_catalog()


@router.get("/cases")
async def cases(request: Request):
    user = auth.require_user(request)
    rows = db.visible_cases(user["org_id"], include_unpublished=user["role"] != "learner")
    # A learner's own best attempt per case, for the card.
    best = {r["case_id"]: r for r in db.all_(
        "SELECT case_id, MAX(score) AS score, COUNT(*) AS attempts FROM encounters "
        "WHERE user_id=? AND status='complete' GROUP BY case_id", (user["id"],))}
    out = []
    for r in rows:
        data = db.load_case_data(r["id"]) or {}
        out.append({
            "id": r["id"], "title": r["title"], "specialty": r["specialty"], "difficulty": r["difficulty"],
            "published": bool(r["published"]), "builtin": bool(r["builtin"]),
            "name": data.get("name"), "age": data.get("age"), "sex": data.get("sex"),
            "setting": data.get("setting"), "complaint": (data.get("presentation") or {}).get("complaint"),
            "level_card": data.get("level_card"),
            "best_score": (best.get(r["id"]) or {}).get("score"),
            "attempts": (best.get(r["id"]) or {}).get("attempts", 0),
        })
    return {"cases": out}


@router.post("/encounters")
async def start(request: Request, payload: dict):
    user = auth.require_user(request)
    case_id = payload.get("case_id") or ""
    row = db.case_row(case_id)
    if not row or (row["org_id"] and row["org_id"] != user["org_id"]):
        raise HTTPException(404, "Case not found.")
    if not row["published"] and user["role"] == "learner":
        raise HTTPException(403, "That case is not published yet.")
    case = db.load_case_data(case_id)
    assignment_id = payload.get("assignment_id") or None
    if assignment_id:
        a = db.one("SELECT * FROM assignments WHERE id=? AND org_id=?", (assignment_id, user["org_id"]))
        if not a or a["case_id"] != case_id:
            raise HTTPException(400, "Assignment does not match this case.")
    now = time.time()
    enc = {"id": db.new_id("enc_"), "org_id": user["org_id"], "user_id": user["id"], "case_id": case_id,
           "assignment_id": assignment_id, "state": practice.new_state(case, now), "report": None,
           "score": None, "grade": None, "status": "active", "started_at": now, "finished_at": None}
    _save(enc)
    db.audit("encounter.start", org_id=user["org_id"], user_id=user["id"], detail={"case": case_id})
    return _payload(enc, case)


@router.get("/encounters/{enc_id}")
async def get_encounter(request: Request, enc_id: str):
    user = auth.require_user(request)
    enc, case = _load(enc_id, user)
    before = enc["state"]["status"]
    practice.advance(case, enc["state"])
    if enc["state"]["status"] != before:
        _save(enc)
    return _payload(enc, case)


def _action(request, enc_id, fn):
    user = auth.require_user(request)
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
async def ask(request: Request, enc_id: str, payload: dict):
    def fn(enc, case):
        st = enc["state"]
        qs = [m for m in st["messages"] if m["kind"] == "question"]
        if qs and practice.rel(st, time.time()) - qs[-1]["t"] < MIN_SECONDS_BETWEEN_ASKS:
            raise practice.EncounterError("Give the patient a moment to answer.")
        reply = practice.ask(case, st, payload.get("text") or "", _speak_for(case))
        return {"reply": reply}
    return _action(request, enc_id, fn)


@router.post("/encounters/{enc_id}/examine")
async def examine(request: Request, enc_id: str, payload: dict):
    return _action(request, enc_id,
                   lambda enc, case: {"finding": practice.examine(case, enc["state"], payload.get("exam_id") or "")})


@router.post("/encounters/{enc_id}/order")
async def order(request: Request, enc_id: str, payload: dict):
    return _action(request, enc_id,
                   lambda enc, case: {"ordered": practice.order(case, enc["state"], payload.get("test_id") or "")})


@router.post("/encounters/{enc_id}/treat")
async def treat(request: Request, enc_id: str, payload: dict):
    return _action(request, enc_id,
                   lambda enc, case: {"effect": practice.treat(case, enc["state"], payload.get("treatment_id") or "")})


@router.post("/encounters/{enc_id}/notes")
async def notes(request: Request, enc_id: str, payload: dict):
    def fn(enc, case):
        practice.save_notes(enc["state"], payload.get("notes") or "")
        return {}
    return _action(request, enc_id, fn)


@router.post("/encounters/{enc_id}/submit")
async def submit(request: Request, enc_id: str, payload: dict):
    user = auth.require_user(request)
    enc, case = _load(enc_id, user)
    if enc["user_id"] != user["id"]:
        raise HTTPException(403, "Only the learner can submit their own encounter.")
    try:
        practice.submit(case, enc["state"], payload)
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
async def report(request: Request, enc_id: str):
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
async def my_encounters(request: Request):
    user = auth.require_user(request)
    rows = db.all_(
        "SELECT e.id, e.case_id, c.title, c.specialty, e.score, e.grade, e.status, e.started_at, e.finished_at, e.assignment_id "
        "FROM encounters e JOIN cases c ON c.id=e.case_id WHERE e.user_id=? ORDER BY e.started_at DESC LIMIT 200",
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
