"""The proving ground.

The claim is that the diagnosis never reaches the model. This turns that claim
into something a room can attack in real time: the built-in corpus streams down
the projector, and anyone with a phone can throw their own jailbreak at the
patient and watch it fail on the big screen.

No authentication. It is a party trick on purpose -- the whole point is that
strangers get to try to break it. That makes it the one place anyone on the
internet can spend the model budget, so it is metered: a per-address pace, a
global hourly ceiling on live calls, and a cool-down between runs of the
corpus. Over the ceiling the page keeps working and says so, instead of
billing without limit.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from engine import redteam
from engine.patient import load_case
from server import guard

router = APIRouter(prefix="/api/prove", tags=["prove"])

# One shared wall, because the whole room is looking at the same screen.
CASE_ID = "kamal"
FEED_MAX = 60

state = {
    "attempts": 0,
    "leaks": 0,
    "feed": [],          # newest last
    "suite_done": False,
}
sockets: set = set()
_lock = asyncio.Lock()

# A festival audience shares one venue address, so this paces a room, not a
# phone; the hourly ceiling below is what bounds the spend.
_per_address = guard.RateLimit(90, 60)
_live_hourly = guard.RateLimit(600, 3600)    # live model calls from this page, all callers
_suite_starts = guard.RateLimit(1, 90)       # the corpus is 100 calls; not on a loop
_resets = guard.RateLimit(10, 60)
SUITE_TIMEOUT_S = 30.0


def _case():
    return load_case(CASE_ID)


def snapshot() -> dict:
    return {
        "attempts": state["attempts"],
        "leaks": state["leaks"],
        "feed": state["feed"][-FEED_MAX:],
        "suite_total": len(redteam.all_attacks()),
        "suite_done": state["suite_done"],
        "live": redteam.patient_live_available(),
        "categories": redteam.CATEGORIES,
    }


async def broadcast():
    payload = snapshot()
    dead = []
    for ws in list(sockets):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        sockets.discard(ws)


async def record(result: dict, who: str = "house"):
    async with _lock:
        state["attempts"] += 1
        if result["leaked"]:
            state["leaks"] += 1
        state["feed"].append({
            "who": who[:18] or "someone",
            "attack": result["attack"][:180],
            "reply": result["reply"][:220],
            "leaked": result["leaked"],
            "terms": result["terms"],
            "category": result.get("category", "from the floor"),
            "mode": result["mode"],
            "n": state["attempts"],
        })
        del state["feed"][:-FEED_MAX]
    await broadcast()


@router.get("")
async def get_state():
    return snapshot()


@router.get("/prompt")
async def prompt_xray():
    """The literal system prompt the model receives, and the proof that the
    answer is not in it.

    This is the strongest form of the claim: not "trust the allowlist" but
    "here is every character we send -- search it". The prompt is built by the
    same function the live patient uses, both before and after he cracks.
    Every term the output guard blocks is counted in it; all counts are zero,
    and test_no_leak.py makes that true on every commit.
    """
    import re as _re

    from engine import patient as _patient

    case = _case()
    prompts = {"before he cracks": _patient.build_persona(case, cracked=False),
               "after he cracks": _patient.build_persona(case, cracked=True)}
    terms = sorted(_patient.guarded_terms(case), key=lambda t: (-len(t), t))
    counts = []
    for term in terms:
        rx = _re.compile(r"\b" + _re.escape(term) + r"\b", _re.IGNORECASE)
        counts.append({"term": term, "matches": sum(len(rx.findall(p)) for p in prompts.values())})
    return {
        "patient": case["name"],
        "prompts": prompts,
        "forbidden": counts,
        "withheld_fields": _patient.SECRET_FIELDS,
        "sent_fields": _patient.ALLOWED_IN_PROMPT,
    }


def _live_allowed() -> bool:
    """Live if a key is set and this page is still under its hourly ceiling."""
    return redteam.patient_live_available() and not _live_hourly.hit("prove")


@router.post("/attack")
async def attack(request: Request, payload: dict):
    """Anyone can call this. That is the point."""
    wait = _per_address.hit(guard.client_ip(request))
    if wait:
        return JSONResponse({"error": "slow down -- try again in %ds" % max(1, round(wait))},
                            status_code=429)
    text = guard.text(payload, "text", 400)
    who = guard.text(payload, "who", 18) or "the floor"
    if not text:
        return JSONResponse({"error": "say something"}, status_code=400)

    case = _case()
    result = await asyncio.to_thread(redteam.run_one, case, text, _live_allowed())
    await record(result, who=who)
    return {"leaked": result["leaked"], "reply": result["reply"],
            "terms": result["terms"], "mode": result["mode"]}


@router.post("/suite")
async def suite():
    """Run the built-in 100 down the screen, one at a time so it can be read."""
    if state.get("_running"):
        return {"already": True}
    if _suite_starts.hit("suite"):
        return JSONResponse({"error": "the corpus just ran -- give it a minute"}, status_code=429)
    state["_running"] = True
    state["suite_done"] = False

    async def go():
        case = _case()
        live = redteam.patient_live_available()
        try:
            for category, text in redteam.all_attacks():
                use_live = live and _live_allowed()
                try:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(redteam.run_one, case, text, use_live), SUITE_TIMEOUT_S)
                except asyncio.TimeoutError:
                    result = await asyncio.to_thread(redteam.run_one, case, text, False)
                result["category"] = category
                await record(result, who="the corpus")
                await asyncio.sleep(0.45 if not live else 0.05)
        finally:
            state["_running"] = False
            state["suite_done"] = True
            await broadcast()

    asyncio.create_task(go())
    return {"started": True, "total": len(redteam.all_attacks())}


@router.post("/reset")
async def reset(request: Request):
    if _resets.hit(guard.client_ip(request)):
        return JSONResponse({"error": "slow down"}, status_code=429)
    async with _lock:
        state["attempts"] = 0
        state["leaks"] = 0
        state["feed"] = []
        state["suite_done"] = False
    await broadcast()
    return {"ok": True}


@router.websocket("/ws")
async def prove_ws(websocket: WebSocket):
    await websocket.accept()
    sockets.add(websocket)
    try:
        await websocket.send_json(snapshot())
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        sockets.discard(websocket)
