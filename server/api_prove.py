"""The proving ground.

The claim is that the diagnosis never reaches the model. This turns that claim
into something a room can attack in real time: the built-in corpus streams down
the projector, and anyone with a phone can throw their own jailbreak at the
patient and watch it fail on the big screen.

No authentication. It is a party trick on purpose -- the whole point is that
strangers get to try to break it.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from engine import redteam
from engine.patient import load_case

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


@router.post("/attack")
async def attack(payload: dict):
    """Anyone can call this. That is the point."""
    text = (payload.get("text") or "").strip()
    who = (payload.get("who") or "the floor").strip()
    if not text:
        return JSONResponse({"error": "say something"}, status_code=400)

    case = _case()
    result = await asyncio.to_thread(
        redteam.run_one, case, text, redteam.patient_live_available()
    )
    await record(result, who=who)
    return {"leaked": result["leaked"], "reply": result["reply"],
            "terms": result["terms"], "mode": result["mode"]}


@router.post("/suite")
async def suite():
    """Run the built-in 100 down the screen, one at a time so it can be read."""
    if state.get("_running"):
        return {"already": True}
    state["_running"] = True
    state["suite_done"] = False

    async def go():
        case = _case()
        live = redteam.patient_live_available()
        try:
            for category, text in redteam.all_attacks():
                result = await asyncio.to_thread(redteam.run_one, case, text, live)
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
async def reset():
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
