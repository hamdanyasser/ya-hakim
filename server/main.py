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
from contextlib import asynccontextmanager
from pathlib import Path

import segno
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Must run before anything reads ANTHROPIC_API_KEY or STRIPE_*. A missing .env
# is not an error; the app runs offline and on the free plan either way.
load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.patient import CASES_DIR, load_case                       # noqa: E402
from server import api_auth, api_org, api_practice, api_prove, db, guard  # noqa: E402
from server import rooms as registry                                   # noqa: E402
from server import ws as sockets                                       # noqa: E402

WEB = Path(__file__).resolve().parent.parent / "web"

@asynccontextmanager
async def lifespan(_app):
    db.init()
    for path in sorted(CASES_DIR.glob("*.json")):
        db.upsert_builtin_case(load_case(path.stem))
    ticker = sockets.start_ticker()
    try:
        yield
    finally:
        ticker.cancel()


app = FastAPI(title="Ya Hakim", docs_url=None, redoc_url=None, lifespan=lifespan)
app.include_router(api_auth.router)
app.include_router(api_practice.router)
app.include_router(api_org.router)
app.include_router(api_prove.router)


@app.middleware("http")
async def _headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    # Pages and their scripts must revalidate: they are not versioned by URL,
    # so a heuristically cached app.js from before an update would keep calling
    # endpoints whose contract has changed. ETag/Last-Modified keep it cheap.
    path = request.url.path
    if path.startswith("/static/") or not path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-cache")
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


@app.get("/prove")
async def prove():
    """The proving ground: the room tries to break the guarantee, live."""
    return FileResponse(WEB / "prove.html")


@app.get("/attack")
async def attack_page():
    return FileResponse(WEB / "attack.html")


@app.get("/api/prove/qr.svg")
async def prove_qr(request: Request):
    host = request.headers.get("host", "localhost")
    buf = io.BytesIO()
    segno.make("http://" + host + "/attack", error="m").save(
        buf, kind="svg", scale=10, border=4, dark="#000000", light="#ffffff")
    return Response(buf.getvalue(), media_type="image/svg+xml",
                    headers={"Cache-Control": "no-store"})


@app.get("/screen")
async def screen():
    return FileResponse(WEB / "screen.html")


@app.get("/play")
async def play():
    return FileResponse(WEB / "play.html")


FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
           '<rect width="32" height="32" rx="8" fill="#5DCAA5"/>'
           '<polyline points="4,18 11,18 14,9 18,24 21,14 28,14" fill="none" stroke="#06201A" '
           'stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/></svg>')


@app.get("/favicon.ico")
def favicon():
    return Response(FAVICON, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/usage")
async def api_usage():
    """What this process has spent. Open it when the credit looks wrong."""
    from engine import llm
    return llm.usage_report()


@app.get("/healthz")
async def healthz():
    return {"ok": True}


app.mount("/static", StaticFiles(directory=str(WEB)), name="static")


# --------------------------------------------------------------- classroom
#
# Phones may join, ask and guess. Everything that drives the round -- start,
# reveal, next, kill, reset -- needs the host key the projector received when
# it claimed the room, so nobody in the audience can end the round for
# everyone else.

_room_asks = guard.RateLimit(40, 10)       # per room: a full room, not a script
_new_rooms = guard.RateLimit(30, 600)      # per address


def _room_or_404(code: str):
    room = registry.get(code)
    if not room:
        return None, JSONResponse({"error": "no such room"}, status_code=404)
    registry.touch(room)
    return room, None


def _host_or_403(request: Request, code: str):
    room, err = _room_or_404(code)
    if err:
        return None, err
    if not registry.is_host(room, request.headers.get("x-host-key")):
        return None, JSONResponse({"error": "only the screen hosting this room can do that"},
                                  status_code=403)
    return room, None


def _make_room(request: Request, code=None, level=1):
    _new_rooms.check(guard.client_ip(request), "Too many new rooms from this network.")
    try:
        return registry.get_or_make(code, level)
    except registry.RoomLimit:
        raise HTTPException(503, "This server is hosting as many rooms as it can. Try again later.")
    except ValueError:
        raise HTTPException(400, "Room codes are 3 to 8 letters or digits.")


@app.post("/api/room")
def api_room(request: Request, payload: dict | None = None):
    payload = payload or {}
    level = int(guard.number(payload, "level", default=1, lo=1, hi=len(registry.LEVELS)))
    code = guard.text(payload, "code", 8) or None
    if code and registry.get(code):
        raise HTTPException(409, "That room already exists.")
    room = _make_room(request, code, level)
    key = registry.claim_host(room, None)
    return {"code": room.room_code, "level": room.level, "card": room.case.get("level_card"),
            "levels": len(registry.LEVELS), "host_key": key}


@app.post("/api/{code}/host")
def api_host(request: Request, code: str, payload: dict | None = None):
    """A projector claims (or re-claims, after a reload) the room it shows.

    Creates the room if the server has none by that code: after a restart the
    projector is the one that brings its room back.
    """
    room = registry.get(code) or _make_room(request, code)
    key = registry.claim_host(room, guard.text(payload or {}, "key", 64) or None)
    if not key:
        return JSONResponse({"error": "another screen is hosting this room"}, status_code=403)
    return {"host_key": key, "code": room.room_code}


@app.get("/api/{code}/card")
def api_card(code: str):
    room, err = _room_or_404(code)
    if err:
        return err
    return {"level": room.level, "levels": len(registry.LEVELS), "card": room.case.get("level_card"),
            "phase": room.phase}


@app.post("/api/{code}/start")
async def api_start(request: Request, code: str):
    room, err = _host_or_403(request, code)
    if err:
        return err
    if room.phase == "lobby":
        room.start()
    await sockets.broadcast(room.room_code)
    return {"ok": True}


@app.post("/api/{code}/join")
async def api_join(code: str, payload: dict):
    room, err = _room_or_404(code)
    if err:
        return err
    player = room.add_player(guard.text(payload, "name", 18) or "Doctor")
    await sockets.broadcast(room.room_code)
    return {"name": player["name"]}


@app.post("/api/{code}/ask")
async def api_ask(code: str, payload: dict):
    room, err = _room_or_404(code)
    if err:
        return err

    name = guard.text(payload, "name", 18) or "Doctor"
    text = guard.text(payload, "text", 200)

    # Say WHY nothing happened. A swallowed question looks like a broken game:
    # you type, you press enter, and the screen does not move.
    if room.phase != "playing":
        return {"reply": None, "reason": "not_playing"}
    if not text:
        return {"reply": None, "reason": "empty"}
    room.add_player(name)
    left = room.cooldown_left(name, room.clock())
    if left > 0:
        return {"reply": None, "reason": "cooldown", "wait": round(left, 1)}
    wait = _room_asks.hit(room.room_code)
    if wait:
        return {"reply": None, "reason": "cooldown", "wait": round(wait, 1)}

    # A live reply is a network call measured in seconds. Off the event loop,
    # so the clock and every other room keep ticking; one question at a time
    # per room, so turns never interleave.
    def run():
        with room.ask_lock:
            return room.ask(name, text)

    reply = await run_in_threadpool(run)
    await sockets.broadcast(room.room_code)
    if reply is None:
        if room.phase != "playing":
            return {"reply": None, "reason": "not_playing"}
        return {"reply": None, "reason": "cooldown",
                "wait": round(room.cooldown_left(name, room.clock()), 1)}
    return {"reply": reply}


@app.post("/api/{code}/guess")
async def api_guess(code: str, payload: dict):
    room, err = _room_or_404(code)
    if err:
        return err
    correct = room.guess(guard.text(payload, "name", 18) or "Doctor", guard.text(payload, "text", 120))
    await sockets.broadcast(room.room_code)
    return {"correct": correct}


@app.post("/api/{code}/reveal")
async def api_reveal(request: Request, code: str):
    room, err = _host_or_403(request, code)
    if err:
        return err
    if room.phase not in ("flatline", "reveal"):
        return JSONResponse({"error": "the round is still running"}, status_code=409)
    room.finish_scoring()
    room.reveal()
    await sockets.broadcast(room.room_code)
    return {"ok": True}


@app.post("/api/{code}/next")
async def api_next(request: Request, code: str):
    room, err = _host_or_403(request, code)
    if err:
        return err
    nxt = registry.advance(code)
    if not nxt:
        return {"done": True}
    await sockets.broadcast(nxt.room_code)
    return {"ok": True, "level": nxt.level, "levels": len(registry.LEVELS), "card": nxt.case.get("level_card")}


@app.post("/api/{code}/kill")
async def api_kill(request: Request, code: str):
    room, err = _host_or_403(request, code)
    if err:
        return err
    if room.phase == "playing":
        room.flatline()
    await sockets.broadcast(room.room_code)
    return {"ok": True}


@app.post("/api/{code}/reset")
async def api_reset(request: Request, code: str):
    room, err = _host_or_403(request, code)
    if err:
        return err
    room = registry.reset(code)
    await sockets.broadcast(room.room_code)
    return {"ok": True, "code": room.room_code, "level": room.level}


@app.get("/api/{code}/qr.svg")
def api_qr(code: str, request: Request):
    if not registry.valid_code(code):
        return JSONResponse({"error": "no such room"}, status_code=404)
    host = request.headers.get("host", "localhost")
    url = "http://" + host + "/play?c=" + code.upper()
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=10, border=4, dark="#000000", light="#ffffff")
    return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@app.websocket("/ws/{code}")
async def websocket_endpoint(websocket: WebSocket, code: str):
    """Watch a room. Rooms are made by the projector, never by a watcher: a
    phone with a mistyped code must not conjure a room into memory."""
    room = registry.get(code)
    await websocket.accept()
    if not room:
        # Accept, then close with a reason the page can read. Refusing the
        # handshake would only surface in the browser as an anonymous 1006.
        await websocket.close(code=4404)
        return
    code = room.room_code
    registry.touch(room)
    sockets.register(code, websocket)
    try:
        current = registry.rooms.get(code)
        if current:
            await websocket.send_json(current.public_state().to_dict())
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        sockets.drop(code, websocket)
