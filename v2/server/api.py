"""Ya Hakim v2 -- a lean API for one screen.

Written fresh. The only things carried over are the case files and the
allowlist persona builder in engine/patient.py, because that is the guarantee
the whole project rests on and it is covered by tests. Rewriting it under time
pressure would risk silently breaking the one claim the demo makes.

One encounter at a time, in memory. No accounts, no database, no rooms.
"""

from __future__ import annotations

import re
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse, JSONResponse

from engine import clinical, patient, scoring, vitals

router = APIRouter(prefix="/api/v2", tags=["v2"])

WEB = Path(__file__).resolve().parent.parent / "web"
ROUND_SECONDS = 150
COOLDOWN = 1.2

CASES = ["kamal", "rita", "georges"]
AVATARS = {"kamal": "🧔", "rita": "👩", "georges": "👴"}

sessions: dict[str, dict] = {}


def _case(case_id: str) -> dict:
    return patient.load_case(case_id if case_id in CASES else CASES[0])


@router.get("/cases")
async def list_cases():
    """Enough to draw the picker. Nothing secret crosses this line."""
    out = []
    for cid in CASES:
        c = _case(cid)
        out.append({
            "id": cid,
            "name": c["name"],
            "age": c["age"],
            "avatar": AVATARS.get(cid, "🧑"),
            "sex": c.get("sex", "male"),
            "setting": c.get("setting", ""),
            "blurb": c.get("description", "")[:150],
            "opening": c["opening_line"],
        })
    return {"cases": out}


@router.post("/start")
async def start(payload: dict):
    case_id = (payload.get("case") or CASES[0]).strip()
    case = _case(case_id)
    sid = secrets.token_urlsafe(9)
    now = time.monotonic()
    sessions[sid] = {
        "case_id": case_id,
        "case": case,
        "started": now,
        "decline": 0.0,
        "last_tick": now,
        "stabilised_until": 0.0,
        "covered": set(),
        "examined": set(),
        "drink_asks": 0,
        "cracked": False,
        "lied_at": None,
        "history": [],
        "log": [],
        "last_ask": 0.0,
        "ever_critical": False,
        "over": False,
        "called": None,
        "correct": False,
        "score": 0,
    }
    s = sessions[sid]
    s["log"].append({"who": case["name"], "text": case["opening_line"], "kind": "him"})
    return {"session": sid, **_view(s)}


def _tick(s: dict):
    now = time.monotonic()
    dt = max(0.0, now - s["last_tick"])
    s["last_tick"] = now
    if s["over"]:
        return
    if now >= s["stabilised_until"]:
        s["decline"] += dt
    if _left(s) <= 0:
        s["over"] = True
    v = _vitals(s)
    if vitals.status_for(v) == "critical":
        s["ever_critical"] = True


def _left(s: dict) -> int:
    return max(0, int(round(ROUND_SECONDS - (time.monotonic() - s["started"]))))


def _vitals(s: dict) -> dict:
    if s["over"]:
        return vitals.dead_vitals()
    since = None if s["lied_at"] is None else max(0.0, time.monotonic() - s["lied_at"])
    return vitals.vitals_at(s["case"], s["decline"], seconds_since_lie=since)


def _mood(s: dict) -> str:
    if s["over"]:
        return "gone"
    if s["cracked"]:
        return "resigned"
    v = _vitals(s)
    st = vitals.status_for(v)
    if st == "critical":
        return "scared"
    if st == "declining":
        return "rattled"
    if len(s["covered"]) >= 2:
        return "defensive"
    return "guarded"


def _view(s: dict) -> dict:
    _tick(s)
    v = _vitals(s)
    return {
        "name": s["case"]["name"],
        "age": s["case"]["age"],
        "avatar": AVATARS.get(s["case_id"], "🧑"),
        "sex": s["case"].get("sex", "male"),
        "vitals": v,
        "status": "flatline" if s["over"] else vitals.status_for(v),
        "mood": _mood(s),
        "seconds_left": _left(s),
        "log": s["log"][-14:],
        "examined": sorted(s["examined"]),
        "over": s["over"],
    }


def _get(sid: str):
    s = sessions.get(sid)
    if not s:
        return None, JSONResponse({"error": "no session"}, status_code=404)
    return s, None


@router.get("/state/{sid}")
async def state(sid: str):
    s, err = _get(sid)
    return err or _view(s)


@router.post("/ask/{sid}")
async def ask(sid: str, payload: dict):
    s, err = _get(sid)
    if err:
        return err
    _tick(s)
    if s["over"]:
        return {"reason": "over", **_view(s)}

    text = (payload.get("text") or "").strip()[:240]
    if not text:
        return {"reason": "empty", **_view(s)}

    now = time.monotonic()
    if now - s["last_ask"] < COOLDOWN:
        return {"reason": "wait", **_view(s)}
    s["last_ask"] = now

    case = s["case"]
    s["log"].append({"who": "You", "text": text, "kind": "you"})

    topic = scoring.covers_key_topic(case, text)
    drink = case["key_questions"][0]
    if topic is None and "wife" in text.lower():
        topic = drink
    if topic is not None:
        if topic not in s["covered"]:
            s["covered"].add(topic)
            s["stabilised_until"] = max(s["stabilised_until"], now) + 45
        if topic == drink:
            s["drink_asks"] += 1
            if s["drink_asks"] >= 2:
                s["cracked"] = True
    if "wife" in text.lower():
        s["cracked"] = True

    reply = patient.ask(case, s["history"], text, cracked=s["cracked"])
    if reply is None:
        cp = patient.CannedPatient(case)
        cp.deflect_i = sum(ord(c) for c in text) % 7
        reply = patient.sanitise(cp.reply(text, cracked=s["cracked"], topic=topic))

    s["history"] += [{"role": "user", "content": text},
                     {"role": "assistant", "content": reply}]
    if reply == case["lie"]:
        s["lied_at"] = now

    s["log"].append({"who": case["name"], "text": reply, "kind": "him"})
    return _view(s)


@router.get("/exams")
async def exams():
    return {"exams": [{"id": e["id"], "name": e["name"]} for e in clinical.EXAMS]}


@router.post("/examine/{sid}")
async def examine(sid: str, payload: dict):
    s, err = _get(sid)
    if err:
        return err
    _tick(s)
    if s["over"]:
        return {"reason": "over", **_view(s)}
    eid = (payload.get("exam") or "").strip()
    exam = clinical.EXAM_BY_ID.get(eid)
    if not exam:
        return {"reason": "unknown", **_view(s)}
    if eid in s["examined"]:
        return {"reason": "already", **_view(s)}
    s["examined"].add(eid)
    finding = clinical.exam_finding(s["case"], eid)
    s["log"].append({"who": exam["name"], "text": finding, "kind": "exam"})
    return _view(s)


@router.post("/diagnose/{sid}")
async def diagnose(sid: str, payload: dict):
    s, err = _get(sid)
    if err:
        return err
    _tick(s)
    text = (payload.get("text") or "").strip()[:160]
    case = s["case"]
    correct = scoring.match_guess(case, text)

    s["called"] = text
    s["correct"] = correct
    s["over"] = True

    score = 0
    if correct:
        score += 100
        score += min(40, _left(s) // 3)            # calling it early is worth something
    score += 6 * len(s["examined"])
    if not s["ever_critical"]:
        score += 25
    s["score"] = score

    return {
        "correct": correct,
        "diagnosis": case["diagnosis"],
        "called": text,
        "note": case.get("reveal_note"),
        "score": score,
        "breakdown": [
            ("Called it right", 100 if correct else 0),
            ("Called it early", min(40, _left(s) // 3) if correct else 0),
            ("Examined him (%d)" % len(s["examined"]), 6 * len(s["examined"])),
            ("Kept him off the edge", 0 if s["ever_critical"] else 25),
        ],
        **_view(s),
    }


@router.get("/proof/{sid}")
async def proof(sid: str):
    """The X-ray: the exact prompt, and the answer searched inside it."""
    s, err = _get(sid)
    if err:
        return err
    case = s["case"]
    prompt = patient.build_persona(case, cracked=s["cracked"])

    terms = sorted(set(case["accepted_answers"]) |
                   {w for w in re.findall(r"[a-z]{4,}", case["diagnosis"].lower())})
    checked = []
    for t in terms:
        n = len(re.findall(r"\b" + re.escape(t) + r"\b", prompt, re.IGNORECASE))
        checked.append({"term": t, "hits": n})

    return {
        "prompt": prompt,
        "chars": len(prompt),
        "terms": checked,
        "withheld": patient.SECRET_FIELDS,
    }


@router.get("/page")
async def page():
    return FileResponse(WEB / "app.html")
