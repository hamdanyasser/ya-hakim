"""The server. Serves the projector, the phones, and the state that drives both.

Clients receive GameState and nothing else. There is no endpoint that returns a
case file, and the room object is never serialised.
"""

from __future__ import annotations

import asyncio
import os
import random
import string
import sys
from pathlib import Path

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.game import Room                      # noqa: E402
from engine.patient import load_case              # noqa: E402

WEB = Path(__file__).resolve().parent.parent / "web"

# No 0/O and no 1/I/L. Someone is reading this off a projector.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

# The three cases in level order. Level 1 is the trial.
LEVELS = ["kamal"]

app = FastAPI(title="Ya Hakim")

rooms: dict[str, Room] = {}
sockets: dict[str, set[WebSocket]] = {}


def new_code() -> str:
    while True:
        code = "".join(random.choice(CODE_ALPHABET) for _ in range(4))
        if code not in rooms:
            return code


def get_or_make(code: str | None = None, level: int = 1) -> Room:
    if code and code.upper() in rooms:
        return rooms[code.upper()]
    code = (code or new_code()).upper()
    case_id = LEVELS[min(level, len(LEVELS)) - 1]
    room = Room(load_case(case_id), room_code=code, level=level)
    rooms[code] = room
    sockets.setdefault(code, set())
    return room


async def broadcast(code: str):
    """Push state to everyone watching. Dead sockets are reaped, not retried."""
    room = rooms.get(code)
    if not room:
        return
    payload = room.public_state().to_dict()
    dead = []
    for ws in list(sockets.get(code, ())):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        sockets[code].discard(ws)


async def ticker():
    """One task for every room. A phone that walks out cannot stall a round."""
    while True:
        await asyncio.sleep(1.0)
        for code, room in list(rooms.items()):
            before = room.phase
            room.tick()
            if room.phase == "playing" or room.phase != before:
                await broadcast(code)


@app.on_event("startup")
async def _startup():
    asyncio.create_task(ticker())


# --------------------------------------------------------------------- pages

@app.get("/")
async def index():
    return FileResponse(WEB / "screen.html")


@app.get("/screen")
async def screen():
    return FileResponse(WEB / "screen.html")


@app.get("/play")
async def play():
    return FileResponse(WEB / "play.html")


app.mount("/static", StaticFiles(directory=str(WEB)), name="static")


# ----------------------------------------------------------------- the round

@app.post("/api/room")
async def api_room(payload: dict | None = None):
    payload = payload or {}
    room = get_or_make(payload.get("code"), int(payload.get("level", 1)))
    return {"code": room.room_code, "level": room.level}


@app.post("/api/{code}/start")
async def api_start(code: str):
    room = get_or_make(code)
    if room.phase == "lobby":
        room.start()
    await broadcast(room.room_code)
    return {"ok": True}


@app.post("/api/{code}/join")
async def api_join(code: str, payload: dict):
    """Register a player without saying anything.

    Joining used to go through /ask with empty text, which burned the player's
    cooldown and posted a blank line into the feed.
    """
    room = rooms.get(code.upper())
    if not room:
        return JSONResponse({"error": "no such room"}, status_code=404)
    player = room.add_player(payload.get("name", "Doctor"))
    await broadcast(room.room_code)
    return {"name": player["name"]}


@app.post("/api/{code}/ask")
async def api_ask(code: str, payload: dict):
    room = rooms.get(code.upper())
    if not room:
        return JSONResponse({"error": "no such room"}, status_code=404)
    reply = room.ask(payload.get("name", "Doctor"), (payload.get("text") or "")[:200])
    await broadcast(room.room_code)
    return {"reply": reply}


@app.post("/api/{code}/guess")
async def api_guess(code: str, payload: dict):
    room = rooms.get(code.upper())
    if not room:
        return JSONResponse({"error": "no such room"}, status_code=404)
    correct = room.guess(payload.get("name", "Doctor"), (payload.get("text") or "")[:120])
    await broadcast(room.room_code)
    return {"correct": correct}


@app.post("/api/{code}/reveal")
async def api_reveal(code: str):
    room = rooms.get(code.upper())
    if not room:
        return JSONResponse({"error": "no such room"}, status_code=404)
    room.finish_scoring()
    room.reveal()
    await broadcast(room.room_code)
    return {"ok": True}


@app.post("/api/{code}/kill")
async def api_kill(code: str):
    """Debug: trigger the flatline on demand.

    Gate 3 asks for the sequence to land correctly ten times in a row. Without
    this that would mean ten full rounds.
    """
    room = rooms.get(code.upper())
    if not room:
        return JSONResponse({"error": "no such room"}, status_code=404)
    room.flatline()
    await broadcast(room.room_code)
    return {"ok": True}


@app.get("/api/{code}/qr.svg")
async def api_qr(code: str, request: Request):
    """The join QR, generated in code, server-side.

    A hand-written encoder lived here first and produced codes that no scanner
    could read -- verified by decoding them. Generating it with a correct
    library is still generating it in code; nothing is downloaded at runtime.
    """
    import io

    import segno

    host = request.headers.get("host", "localhost")
    url = "http://" + host + "/play?c=" + code.upper()
    buf = io.BytesIO()          # segno writes bytes, not str
    segno.make(url, error="m").save(
        buf, kind="svg", scale=10, border=4, dark="#000000", light="#ffffff",
    )
    return Response(
        buf.getvalue(),
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/{code}/reset")
async def api_reset(code: str):
    code = code.upper()
    level = rooms[code].level if code in rooms else 1
    rooms.pop(code, None)
    room = get_or_make(code, level)
    await broadcast(code)
    return {"ok": True, "code": room.room_code}


@app.websocket("/ws/{code}")
async def ws(websocket: WebSocket, code: str):
    code = code.upper()
    await websocket.accept()
    get_or_make(code)
    sockets.setdefault(code, set()).add(websocket)
    try:
        await websocket.send_json(rooms[code].public_state().to_dict())
        while True:
            await websocket.receive_text()   # keepalive; clients act over REST
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        sockets.get(code, set()).discard(websocket)
