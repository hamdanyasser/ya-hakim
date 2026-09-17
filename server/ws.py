"""Sockets and the tick.

Clients receive GameState and nothing else. The room object is never
serialised -- `public_state()` builds the payload field by field.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket

from server import rooms as room_registry

sockets: dict[str, set] = {}
log = logging.getLogger("yahakim.ws")


def register(code: str, socket: WebSocket):
    sockets.setdefault(code.upper(), set()).add(socket)


def drop(code: str, socket: WebSocket):
    sockets.get(code.upper(), set()).discard(socket)


async def broadcast(code: str):
    """Push state to everyone watching.

    A phone that locks its screen, walks out of range, or backgrounds Safari
    will drop. Dead sockets are reaped here rather than retried, so one lost
    phone cannot stall the round for the room.
    """
    code = code.upper()
    room = room_registry.rooms.get(code)
    if not room:
        return
    payload = room.public_state().to_dict()
    dead = []
    for socket in list(sockets.get(code, ())):
        try:
            await socket.send_json(payload)
        except Exception:
            dead.append(socket)
    for socket in dead:
        sockets[code].discard(socket)


def watched(code: str) -> bool:
    return bool(sockets.get(code.upper()))


async def ticker():
    """One task for every room, once a second.

    The clock is authoritative here; the projector interpolates between these
    broadcasts so it can render a smooth countdown at 60fps without the server
    sending 60 messages a second. Once a minute, rooms idle for hours with
    nobody watching are dropped, so the registry cannot grow without bound.
    """
    n = 0
    while True:
        await asyncio.sleep(1.0)
        n += 1
        for code, room in list(room_registry.rooms.items()):
            try:
                before = room.phase
                room.tick()
                if room.phase == "playing" or room.phase != before:
                    await broadcast(code)
            except Exception:
                # One broken room must never stop the clock for every other room.
                log.exception("tick failed for room %s", code)
        if n % 60 == 0:
            room_registry.reap(has_watchers=watched)
            for code in [c for c, s in sockets.items() if not s]:
                sockets.pop(code, None)


def start_ticker():
    return asyncio.create_task(ticker())
