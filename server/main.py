"""The server.

Two products share one process:

- /app          solo practice for medical and nursing schools: accounts,
                cohorts, assignments, the encounter, the debrief, dashboards,
                the case editor, billing.
- /screen /play the classroom mode: one projector, a room of phones, one
                patient, one clock.

Clients receive what the engine chooses to send and nothing else. No endpoint
returns a case file to a learner; the encounter and room objects are never
serialised whole.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import segno
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Must run before anything reads ANTHROPIC_API_KEY or STRIPE_*. A missing .env
# is not an error; the app runs offline and on the free plan either way.
load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.patient import CASES_DIR, load_case                       # noqa: E402
from server import api_auth, api_org, api_practice, db                 # noqa: E402
from server import rooms as registry                                   # noqa: E402
from server import ws as sockets                                       # noqa: E402

WEB = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Ya Hakim", docs_url=None, redoc_url=None)
app.include_router(api_auth.router)
app.include_router(api_practice.router)
app.include_router(api_org.router)


@app.on_event("startup")
async def _startup():
    db.init()
    for path in sorted(CASES_DIR.glob("*.json")):
        db.upsert_builtin_case(load_case(path.stem))
    sockets.start_ticker()


@app.middleware("http")
async def _headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return resp


# --------------------------------------------------------------------- pages

@app.get("/")
async def index():
    return FileResponse(WEB / "index.html")


@app.get("/app")
@app.get("/app/{rest:path}")
async def app_shell(rest: str = ""):
    return FileResponse(WEB / "app.html")


@app.get("/practice/{enc_id}")
async def practice_page(enc_id: str):
    return FileResponse(WEB / "practice.html")


@app.get("/screen")
async def screen():
    return FileResponse(WEB / "screen.html")


@app.get("/play")
async def play():
    return FileResponse(WEB / "play.html")


@app.get("/healthz")
async def healthz():
    return {"ok": True}


app.mount("/static", StaticFiles(directory=str(WEB)), name="static")


# --------------------------------------------------------------- classroom

def _room_or_404(code: str):
    room = registry.rooms.get(code.upper())
    if not room:
        return None, JSONResponse({"error": "no such room"}, status_code=404)
    return room, None


@app.post("/api/room")
async def api_room(payload: dict | None = None):
    payload = payload or {}
    room = registry.get_or_make(payload.get("code"), int(payload.get("level", 1)))
    return {"code": room.room_code, "level": room.level, "card": room.case.get("level_card"),
            "levels": len(registry.LEVELS)}


@app.get("/api/{code}/card")
async def api_card(code: str):
    room, err = _room_or_404(code)
    if err:
        return err
    return {"level": room.level, "levels": len(registry.LEVELS), "card": room.case.get("level_card"),
            "phase": room.phase}


@app.post("/api/{code}/start")
async def api_start(code: str):
    room = registry.get_or_make(code)
    if room.phase == "lobby":
        room.start()
    await sockets.broadcast(room.room_code)
    return {"ok": True}


@app.post("/api/{code}/join")
async def api_join(code: str, payload: dict):
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

    name = payload.get("name", "Doctor")
    text = (payload.get("text") or "")[:200]

    # Say WHY nothing happened. A swallowed question looks like a broken game:
    # you type, you press enter, and the screen does not move.
    if room.phase != "playing":
        return {"reply": None, "reason": "not_playing"}
    if not text.strip():
        return {"reply": None, "reason": "empty"}
    room.add_player(name)
    left = room.cooldown_left(name, room.clock())
    if left > 0:
        return {"reply": None, "reason": "cooldown", "wait": round(left, 1)}

    reply = room.ask(name, text)
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
    room = registry.advance(code)
    if not room:
        return {"done": True}
    await sockets.broadcast(room.room_code)
    return {"ok": True, "level": room.level, "levels": len(registry.LEVELS), "card": room.case.get("level_card")}


@app.post("/api/{code}/kill")
async def api_kill(code: str):
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
    host = request.headers.get("host", "localhost")
    url = "http://" + host + "/play?c=" + code.upper()
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=10, border=4, dark="#000000", light="#ffffff")
    return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@app.websocket("/ws/{code}")
async def websocket_endpoint(websocket: WebSocket, code: str):
    code = code.upper()
    await websocket.accept()
    registry.get_or_make(code)
    sockets.register(code, websocket)
    try:
        await websocket.send_json(registry.rooms[code].public_state().to_dict())
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        sockets.drop(code, websocket)
