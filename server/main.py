"""The server. Serves the projector, the phones, and the state that drives both.

Clients receive GameState and nothing else. There is no endpoint that returns a
case file, and the room object is never serialised.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import segno
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import rooms as registry          # noqa: E402
from server import ws as sockets              # noqa: E402

WEB = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Ya Hakim")


@app.on_event("startup")
async def _startup():
    sockets.start_ticker()


def _room_or_404(code: str):
    room = registry.rooms.get(code.upper())
    if not room:
        return None, JSONResponse({"error": "no such room"}, status_code=404)
    return room, None


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
    room = registry.get_or_make(payload.get("code"), int(payload.get("level", 1)))
    return {
        "code": room.room_code,
        "level": room.level,
        "card": room.case.get("level_card"),
        "levels": len(registry.LEVELS),
    }


@app.get("/api/{code}/card")
async def api_card(code: str):
    """The story card for the round about to start."""
    room, err = _room_or_404(code)
    if err:
        return err
    return {
        "level": room.level,
        "levels": len(registry.LEVELS),
        "card": room.case.get("level_card"),
        "phase": room.phase,
    }


@app.post("/api/{code}/start")
async def api_start(code: str):
    room = registry.get_or_make(code)
    if room.phase == "lobby":
        room.start()
    await sockets.broadcast(room.room_code)
    return {"ok": True}


@app.post("/api/{code}/join")
async def api_join(code: str, payload: dict):
    """Register a player without saying anything.

    Joining used to go through /ask with empty text, which burned the player's
    cooldown and posted a blank line into the feed.
    """
    room, err = _room_or_404(code)
    if err:
        return err
    player = room.add_player(payload.get("name", "Doctor"))
    await sockets.broadcast(room.room_code)
    return {"name": player["name"]}


@app.post("/api/{code}/ask")
async def api_ask(code: str, payload: dict):
    room, err = _room_or_404(code)
    if err:
        return err
    reply = room.ask(payload.get("name", "Doctor"), (payload.get("text") or "")[:200])
    await sockets.broadcast(room.room_code)
    return {"reply": reply}


@app.post("/api/{code}/guess")
async def api_guess(code: str, payload: dict):
    room, err = _room_or_404(code)
    if err:
        return err
    correct = room.guess(payload.get("name", "Doctor"), (payload.get("text") or "")[:120])
    await sockets.broadcast(room.room_code)
    return {"correct": correct}


@app.post("/api/{code}/reveal")
async def api_reveal(code: str):
    room, err = _room_or_404(code)
    if err:
        return err
    room.finish_scoring()
    room.reveal()
    await sockets.broadcast(room.room_code)
    return {"ok": True}


@app.post("/api/{code}/next")
async def api_next(code: str):
    """Advance the campaign, carrying scores forward."""
    room = registry.advance(code)
    if not room:
        return {"done": True}
    await sockets.broadcast(room.room_code)
    return {
        "ok": True,
        "level": room.level,
        "levels": len(registry.LEVELS),
        "card": room.case.get("level_card"),
    }


@app.post("/api/{code}/kill")
async def api_kill(code: str):
    """Debug: trigger the flatline on demand.

    Gate 3 asks for the sequence to land correctly ten times in a row. Without
    this that would mean ten full rounds.
    """
    room, err = _room_or_404(code)
    if err:
        return err
    room.flatline()
    await sockets.broadcast(room.room_code)
    return {"ok": True}


@app.post("/api/{code}/reset")
async def api_reset(code: str):
    room = registry.reset(code)
    await sockets.broadcast(room.room_code)
    return {"ok": True, "code": room.room_code, "level": room.level}


@app.get("/api/{code}/qr.svg")
async def api_qr(code: str, request: Request):
    """The join QR, generated in code, server-side.

    A hand-written encoder lived here first and produced codes that no scanner
    could read -- verified by rendering its output and decoding it. Generating
    it with a correct library is still generating it in code; nothing is
    downloaded at runtime.
    """
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


@app.websocket("/ws/{code}")
async def websocket_endpoint(websocket: WebSocket, code: str):
    code = code.upper()
    await websocket.accept()
    registry.get_or_make(code)
    sockets.register(code, websocket)
    try:
        await websocket.send_json(registry.rooms[code].public_state().to_dict())
        while True:
            await websocket.receive_text()   # keepalive; clients act over REST
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        sockets.drop(code, websocket)
