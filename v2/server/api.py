"""Ya Hakim v2 -- a lean API for one screen.

Written fresh. The only things carried over are the case files and the
allowlist persona builder in engine/patient.py, because that is the guarantee
the whole project rests on and it is covered by tests. Rewriting it under time
pressure would risk silently breaking the one claim the demo makes.

One encounter at a time, in memory. No accounts, no database, no rooms. The
player's level and history live in their own browser, which is the only kind of
persistence a thing with no accounts is entitled to.
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from engine import authoring, clinical, llm, patient, redteam, scoring, vitals

router = APIRouter(prefix="/api/v2", tags=["v2"])

WEB = Path(__file__).resolve().parent.parent / "web"
ROUND_SECONDS = 240
COOLDOWN = 1.2

# How many times you may call it. One shot made the whole round a coin flip on
# a single sentence; five lets you narrow it down and still rewards getting
# there first, because a later call is worth fewer marks.
MAX_GUESSES = 5
CALL_MARKS = [50, 42, 34, 26, 18]

# Ordered easiest first, so the picker reads as a ladder.
CASES = ["kamal", "nadia", "rita", "samir", "farida", "omar", "georges", "elias", "hana"]
AVATARS = {
    "kamal": "🧔", "rita": "👩", "georges": "👴",
    "nadia": "👩‍🎓", "samir": "🧑", "farida": "👵",
    "omar": "👨‍✈️", "elias": "🧓", "hana": "👩‍💼",
}

# The ladder. Difficulty is a property of the case, so it is stated here rather
# than guessed in the browser: a case whose answer is one question away is not
# worth the same as one where every sign points somewhere else first.
TIERS = {
    "kamal":   {"tier": 1, "rank": "Intern",    "xp": 100},
    "nadia":   {"tier": 1, "rank": "Intern",    "xp": 110},
    "rita":    {"tier": 2, "rank": "Resident",  "xp": 150},
    "samir":   {"tier": 2, "rank": "Resident",  "xp": 165},
    "farida":  {"tier": 2, "rank": "Resident",  "xp": 170},
    "omar":    {"tier": 2, "rank": "Resident",  "xp": 180},
    "georges": {"tier": 3, "rank": "Attending", "xp": 210},
    "elias":   {"tier": 3, "rank": "Attending", "xp": 225},
    "hana":    {"tier": 3, "rank": "Attending", "xp": 240},
}
DEFAULT_TIER = {"tier": 2, "rank": "Resident", "xp": 170}

# Five bodies, because one 54-year-old man wearing three different hair
# colours is not three patients. Build and frame are multipliers on the torso;
# they are kept inside a narrow band on purpose, since the arms are not part
# of the chest group and a wide frame would pull the shoulders off them.
MODELS = {
    "man_middle":  {"build": 1.10, "frame": 1.06, "head": 1.00, "beard": True,  "longHair": False},
    "man_old":     {"build": 0.90, "frame": 0.95, "head": 0.98, "beard": True,  "longHair": False},
    "man_young":   {"build": 0.99, "frame": 1.04, "head": 1.00, "beard": False, "longHair": False},
    "woman_young": {"build": 0.90, "frame": 0.93, "head": 0.95, "beard": False, "longHair": True},
    "woman_old":   {"build": 0.88, "frame": 0.92, "head": 0.95, "beard": False, "longHair": True},
}

GOWNS = {"man_middle": 0x4C7A8E, "man_old": 0x57896E, "man_young": 0x4C7A8E,
         "woman_young": 0x6E7FA8, "woman_old": 0x7A6E97}

# Skin and hair for the written three. Everything else comes from the model.
LOOKS = {
    "kamal":   {"skin": 0x8E5A34, "hair": 0x2C2320},
    "rita":    {"skin": 0xA97247, "hair": 0x332620},
    "georges": {"skin": 0x9C6A44, "hair": 0x8A8680},
}


def _model_for(sex: str, age: int) -> str:
    female = (sex or "").lower().startswith("f")
    if female:
        return "woman_old" if age >= 60 else "woman_young"
    if age >= 60:
        return "man_old"
    return "man_middle" if age >= 45 else "man_young"

sessions: dict[str, dict] = {}

# Cases the model wrote this run. They live and die with the process, which is
# the same promise the sessions make.
generated: dict[str, dict] = {}
jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

MAX_GENERATED = 8


def _case(case_id: str) -> dict:
    if case_id in generated:
        return generated[case_id]
    return patient.load_case(case_id if case_id in CASES else CASES[0])


def _tier(case_id: str) -> dict:
    if case_id in generated:
        return generated[case_id].get("_tier") or DEFAULT_TIER
    return TIERS.get(case_id, DEFAULT_TIER)


def _look(case_id: str, case: dict) -> dict:
    """Which of the five bodies this patient is, and what colour."""
    age = case.get("age") or 50
    model = _model_for(case.get("sex") or "male", age)
    look = dict(MODELS[model])
    look["model"] = model
    look["gown"] = GOWNS.get(model, 0x4C7A8E)

    if case_id in LOOKS:
        look.update(LOOKS[case_id])
    else:
        # generated: a plausible colouring from the two things we are told
        look["skin"] = 0x97613A
        look["hair"] = 0x8A8680 if age >= 60 else 0x2C2320
    return look


def _blurb(text: str, limit: int = 150) -> str:
    """Cut to length on a word, not mid-syllable.

    A hard slice left the picker reading "married thirty years... His wif",
    which looks like a broken page rather than a trimmed one.
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:.") + "…"


def _card(case_id: str) -> dict:
    """Enough to draw the picker. Nothing secret crosses this line."""
    c = _case(case_id)
    t = _tier(case_id)
    return {
        "id": case_id,
        "name": c["name"],
        "age": c["age"],
        "avatar": AVATARS.get(case_id, "🧑"),
        "sex": c.get("sex", "male"),
        "setting": c.get("setting", ""),
        "title": c.get("title", ""),
        "blurb": _blurb(c.get("description", "")),
        "opening": c["opening_line"],
        "tier": t["tier"],
        "rank": t["rank"],
        "xp": t["xp"],
        "topics": len(c.get("key_questions") or []),
        "generated": case_id in generated,
        "look": _look(case_id, c),
    }


@router.get("/cases")
async def list_cases():
    out = [_card(cid) for cid in CASES]
    out += [_card(cid) for cid in generated]
    return {"cases": out, "can_generate": llm.available()}


# --------------------------------------------------------------- generation

def _run_generate(job_id: str, brief: str, specialty: str, difficulty: str):
    """Draft a case on a worker thread and park it in `generated`.

    Turned down from the editor's settings: the instructor's tool is allowed to
    take five minutes over a case that will be taught from for a year, a player
    waiting on a progress bar is not.
    """
    try:
        case = authoring.draft(brief, specialty, difficulty,
                               effort="high", max_tokens=20000, timeout=180.0)
        if not case:
            _finish(job_id, error="The model did not return a usable case. Try again.")
            return

        problems = authoring.validate(case)
        if problems:
            _finish(job_id, error="The drafted case did not validate: " + "; ".join(problems[:3]))
            return

        cid = "gen-" + authoring.slug(case.get("title") or case.get("name") or "case")[:28]
        n, base = 2, cid
        while cid in generated or cid in CASES:
            cid = base + "-" + str(n)
            n += 1

        case["_tier"] = {
            "tier": {"easy": 1, "standard": 2, "hard": 3}.get(difficulty, 2),
            "rank": {"easy": "Intern", "standard": "Resident", "hard": "Attending"}.get(difficulty, "Resident"),
            "xp": {"easy": 120, "standard": 180, "hard": 260}.get(difficulty, 180),
        }

        if len(generated) >= MAX_GENERATED:
            generated.pop(next(iter(generated)))
        generated[cid] = case
        _finish(job_id, case_id=cid)
    except Exception as e:                                  # a worker thread must never die silently
        _finish(job_id, error="%s: %s" % (type(e).__name__, str(e)[:160]))


def _finish(job_id: str, case_id: str | None = None, error: str | None = None):
    with _jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return
        job["state"] = "error" if error else "done"
        job["error"] = error
        job["case"] = case_id
        job["finished"] = time.time()


@router.post("/generate")
async def generate(payload: dict):
    """Start drafting a case. Returns a job to poll, because this takes a while."""
    if not llm.available():
        return JSONResponse(
            {"error": "no_key",
             "message": "Case generation needs ANTHROPIC_API_KEY in the server's .env. "
                        "The three written cases play fully without it."},
            status_code=503)

    with _jobs_lock:
        running = [j for j in jobs.values() if j["state"] == "working"]
        if running:
            return JSONResponse({"error": "busy", "message": "A case is already being written."},
                                status_code=429)
        if len(generated) >= MAX_GENERATED:
            return JSONResponse({"error": "full", "message": "That is as many new cases as one run holds."},
                                status_code=429)
        job_id = secrets.token_urlsafe(8)
        jobs[job_id] = {"state": "working", "started": time.time(), "case": None, "error": None}

    brief = (payload.get("brief") or "").strip()[:300]
    specialty = (payload.get("specialty") or "").strip()[:60]
    difficulty = (payload.get("difficulty") or "standard").strip().lower()
    if difficulty not in ("easy", "standard", "hard"):
        difficulty = "standard"

    threading.Thread(target=_run_generate, daemon=True,
                     args=(job_id, brief, specialty, difficulty)).start()
    return {"job": job_id}


@router.get("/generate/{job_id}")
async def generate_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "no job"}, status_code=404)
    out = {"state": job["state"], "error": job["error"],
           "elapsed": int(time.time() - job["started"])}
    if job["state"] == "done" and job["case"]:
        out["case"] = _card(job["case"])
    return out


# ---------------------------------------------------------------- encounter

@router.post("/start")
async def start(payload: dict):
    case_id = (payload.get("case") or CASES[0]).strip()
    if case_id not in generated and case_id not in CASES:
        case_id = CASES[0]
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
        "pressed": {},        # topic -> how many times it has been asked about
        "examined": set(),
        "guesses": [],        # every call made, in order
        "resolved": False,
        "cracked": False,
        "lied_at": None,
        "history": [],
        "log": [],
        "asked": 0,
        "last_ask": 0.0,
        "ever_critical": False,
        "over": False,
        "called": None,
        "correct": False,
        "score": 0,
    }
    s = sessions[sid]
    s["log"].append({"who": case["name"], "text": case["opening_line"], "kind": "him"})
    return {"session": sid, "case": _card(case_id), **_view(s)}


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
        # Counts only. How many threads there are to pull is a game mechanic;
        # what they are is in SECRET_FIELDS and never crosses this line.
        "topics_covered": len(s["covered"]),
        "topics_total": len(s["case"].get("key_questions") or []),
        "exams_total": len(clinical.EXAMS),
        "tries": len(s["guesses"]),
        "tries_left": max(0, MAX_GUESSES - len(s["guesses"])),
        "tries_allowed": MAX_GUESSES,
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


def _cracks(case: dict, text: str, topic, pressed: dict) -> bool:
    """Has this question broken him?

    Every case ships `cracks_when` in prose and `crack_keywords` as the stems
    that mean it. v2 used to hardcode Kamal's: the literal word "wife", which
    meant Rita and Georges could not be cracked at all and a case the model
    wrote five seconds ago certainly could not. Both halves of the written rule
    are honoured here -- the cue, or pressing the same thread a second time.
    """
    low = text.lower()
    for kw in (case.get("crack_keywords") or []):
        kw = str(kw).lower().strip()
        if not kw:
            continue
        if " " in kw:
            if kw in low:
                return True
        elif re.search(r"\b" + re.escape(kw) + r"\b", low):
            return True
    return topic is not None and pressed.get(topic, 0) >= 2


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
    s["asked"] += 1

    case = s["case"]
    s["log"].append({"who": "You", "text": text, "kind": "you"})

    topic = scoring.covers_key_topic(case, text)
    if topic is not None:
        s["pressed"][topic] = s["pressed"].get(topic, 0) + 1
        if topic not in s["covered"]:
            s["covered"].add(topic)
            s["stabilised_until"] = max(s["stabilised_until"], now) + 45

    if not s["cracked"] and _cracks(case, text, topic, s["pressed"]):
        s["cracked"] = True

    reply = patient.ask(case, s["history"], text, cracked=s["cracked"]) \
        if llm.available() else None
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


def _accuracy(s: dict, correct: bool) -> list:
    """The mark sheet, as four things worth a stated number out of a hundred.

    Deliberately explainable: a player who is told they scored 64% should be
    able to read the rows and see exactly which 36 they did not get.
    """
    total_topics = len(s["case"].get("key_questions") or []) or 1
    covered = min(len(s["covered"]), total_topics)
    exams = len(s["examined"])
    tries = len(s["guesses"])

    if correct and tries:
        call_pts = CALL_MARKS[min(tries, len(CALL_MARKS)) - 1]
        call_note = "first try" if tries == 1 else "on try %d of %d" % (tries, MAX_GUESSES)
    else:
        call_pts = 0
        call_note = "you did not get there"

    topic_pts = round(30 * covered / total_topics)
    exam_pts = round(10 * min(1.0, exams / 4.0))
    safe_pts = 0 if s["ever_critical"] else 10

    return [
        {"label": "Called it right", "got": call_pts, "of": CALL_MARKS[0], "note": call_note},
        {"label": "History taken", "got": topic_pts, "of": 30,
         "note": "%d of %d threads pulled" % (covered, total_topics)},
        {"label": "Examined him", "got": exam_pts, "of": 10,
         "note": "%d examination%s" % (exams, "" if exams == 1 else "s")},
        {"label": "Kept him off the edge", "got": safe_pts, "of": 10,
         "note": "he never went critical" if safe_pts else "he went critical"},
    ]


def _debrief(case: dict) -> dict:
    """What the case file already knows, for after the answer is out.

    All of this names the diagnosis, so it may only ever be built here --
    _resolve is the one function that closes an encounter, and nothing else
    calls this. It is not in _view(), so no amount of polling /state reaches
    it while the round is live.

    None of it is new content: every field below was already written in
    cases/*.json and, until now, never shown to anyone.
    """
    threads = []
    for q, why in zip(case.get("key_questions") or [],
                      case.get("key_question_reasons") or []):
        threads.append({"question": q, "why": why})

    traps = [{"what": k.replace("_", " "), "why": v}
             for k, v in (case.get("harmful_treatments") or {}).items()]

    teaching = case.get("teaching") or {}
    return {
        "summary": teaching.get("summary"),
        "pearls": list(teaching.get("pearls") or []),
        "threads": threads,
        "management": list(case.get("management_points") or []),
        "traps": traps,
        "guidelines": list(case.get("guidelines") or []),
    }


def _resolve(s: dict, correct: bool, reason: str) -> dict:
    """End the round and mark it. The only place that closes an encounter."""
    case = s["case"]
    seconds_left = _left(s)
    s["correct"] = correct
    s["resolved"] = True
    s["over"] = True

    rows = _accuracy(s, correct)
    accuracy = sum(r["got"] for r in rows)
    tier = _tier(s["case_id"])
    speed = round(min(30, seconds_left // 8)) if correct else 0
    xp = round(tier["xp"] * accuracy / 100) + speed

    return {
        "resolved": True,
        "reason": reason,
        "correct": correct,
        "partial": False,
        "diagnosis": case["diagnosis"],
        "called": s["called"],
        "guesses": list(s["guesses"]),
        "note": case.get("reveal_note"),
        "debrief": _debrief(case),
        "accuracy": accuracy,
        "rows": rows,
        "xp": xp,
        "speed_bonus": speed,
        "tier": tier,
        "stats": {
            "asked": s["asked"],
            "examined": len(s["examined"]),
            "topics_covered": min(len(s["covered"]), len(case.get("key_questions") or [])),
            "topics_total": len(case.get("key_questions") or []),
            "seconds_used": ROUND_SECONDS - seconds_left,
            "ever_critical": s["ever_critical"],
            "cracked": s["cracked"],
            "tries": len(s["guesses"]),
            "tries_allowed": MAX_GUESSES,
        },
        "score": accuracy,
        "breakdown": [(r["label"], r["got"]) for r in rows],
        **_view(s),
    }


@router.post("/diagnose/{sid}")
async def diagnose(sid: str, payload: dict):
    """A call. You get MAX_GUESSES of them.

    A wrong one no longer ends the round -- it costs you a mark band and one
    of your tries, and the encounter carries on with the clock running, which
    is the whole point of having more than one.

    `final` is the caller saying stop regardless: the clock ran out, or the
    player gave up.
    """
    s, err = _get(sid)
    if err:
        return err
    _tick(s)

    if s["resolved"]:
        return _resolve(s, s["correct"], "already")

    text = (payload.get("text") or "").strip()[:160]
    final = bool(payload.get("final"))
    case = s["case"]

    if final or not text:
        return _resolve(s, False, "gave_up" if final else "no_call")

    correct = scoring.match_guess(case, text)
    partial = (not correct) and scoring.match_partial(case, text)
    s["guesses"].append(text)
    s["called"] = text

    if correct or len(s["guesses"]) >= MAX_GUESSES:
        return _resolve(s, correct, "called" if correct else "out_of_tries")

    # Still in it. Put the miss in the thread so the room can see it happen.
    left = MAX_GUESSES - len(s["guesses"])
    s["log"].append({
        "who": "Your call",
        "kind": "call",
        "text": '"%s" — %s. %d tr%s left.' % (
            text,
            "right area, but that is not the answer" if partial else "no",
            left, "y" if left == 1 else "ies"),
    })

    return {
        "resolved": False,
        "correct": False,
        "partial": partial,
        "called": text,
        "tries": len(s["guesses"]),
        "tries_left": left,
        "tries_allowed": MAX_GUESSES,
        **_view(s),
    }


_REDTEAM_CACHE: dict[str, dict] = {}


def _redteam(case_id: str, case: dict) -> dict:
    """Run the whole attack corpus against this patient, once, and keep it.

    The room deserves a number, not an adjective. This is the same corpus
    tests/test_injection.py runs in CI -- 100 attacks over ten categories --
    scored by the same guard, so the figure on screen is the figure that
    gates the build rather than one typed into the HTML.

    Offline by design: the guard is what stands between a jailbroken model
    and the player, and firing a hundred live calls every time someone opens
    the sheet would cost real money and take a minute. `mode` says so on
    screen; a number whose provenance is hidden is worth nothing.
    """
    hit = _REDTEAM_CACHE.get(case_id)
    if hit:
        return hit

    leaks = []
    total = 0
    for r in redteam.run_suite(case, live=False):
        total += 1
        if r["leaked"]:
            leaks.append({"category": r["category"],
                          "attack": r["attack"],
                          "terms": r["terms"]})

    out = {
        "attacks": total,
        "categories": len(redteam.CATEGORIES),
        "category_names": list(redteam.CATEGORIES),
        "leaks": len(leaks),
        "examples": leaks[:3],
        "mode": "offline",
    }
    _REDTEAM_CACHE[case_id] = out
    return out


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
        "redteam": _redteam(s["case_id"], case),
    }


@router.get("/page")
async def page():
    return FileResponse(WEB / "app.html")
