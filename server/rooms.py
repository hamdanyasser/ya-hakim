"""The room registry and the campaign.

Rooms live in memory. There is no database, and nothing here is persisted --
closing the server ends every round, which is correct for a party game.
"""

from __future__ import annotations

import random
import re
import secrets
import time

from engine import llm
from engine.game import Room
from engine.patient import CannedPatient, PatientSession, load_case

# No 0/O and no 1/I/L. Someone is reading this off a projector.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

# The campaign, in order. Levels 1 and 2 are the trial pair: a wrong call
# cannot kill them. From level 3 a wrong answer does (see Room.guess).
#
# Same order as the v2 ladder in v2/server/api.py, so a case is the same
# difficulty whichever mode you meet it in. The host picks the starting level,
# so a short session is three of these, not a forced run of nine.
LEVELS = ["kamal", "nadia", "rita", "samir", "farida", "omar",
          "georges", "elias", "hana"]

rooms: dict[str, Room] = {}


def new_code() -> str:
    while True:
        code = "".join(random.choice(CODE_ALPHABET) for _ in range(4))
        if code not in rooms:
            return code


def case_for_level(level: int) -> str:
    return LEVELS[max(1, min(level, len(LEVELS))) - 1]


def make_patient(case: dict):
    """Live if a key is configured and the client builds; canned otherwise.

    This is the one place that decision gets made. `.env` (loaded in
    server/main.py) or the real environment supplies the key; with none set,
    behaviour is unchanged from before this existed. A bad or expired key must
    never crash a round -- it falls back to the offline voice exactly the way
    a failed API call already does mid-round in engine/patient.py.
    """
    if llm.available():
        try:
            return PatientSession(case=case)
        except Exception:
            return CannedPatient(case)
    return CannedPatient(case)


def build(code: str, level: int) -> Room:
    """Construct a room for a level, wiring up the card for the NEXT one."""
    level = max(1, min(level, len(LEVELS)))
    is_last = level >= len(LEVELS)
    next_card = None
    if not is_last:
        next_card = load_case(LEVELS[level]).get("level_card")
    case = load_case(case_for_level(level))
    return Room(
        case,
        room_code=code,
        level=level,
        next_card=next_card,
        is_last=is_last,
        patient=make_patient(case),
    )


MAX_ROOMS = 300                 # a busy festival, not an open-ended allocation
IDLE_SECONDS = 3 * 3600         # a room nobody has touched in three hours is gone
CODE_RE = re.compile(r"^[A-Z0-9]{3,8}$")


class RoomLimit(Exception):
    """Too many live rooms on this server."""


def valid_code(code) -> bool:
    return isinstance(code, str) and bool(CODE_RE.match(code.upper()))


def touch(room: Room):
    room.touched = time.monotonic()


def get(code: str) -> Room | None:
    if not valid_code(code):
        return None
    return rooms.get(code.upper())


def get_or_make(code: str | None = None, level: int = 1) -> Room:
    if code and not valid_code(code):
        raise ValueError("invalid room code")
    if code and code.upper() in rooms:
        room = rooms[code.upper()]
        touch(room)
        return room
    reap()
    if len(rooms) >= MAX_ROOMS:
        raise RoomLimit()
    code = (code or new_code()).upper()
    room = build(code, level)
    touch(room)
    rooms[code] = room
    return room


def _carry(old: Room, new: Room):
    """What survives a level change or a reset: the host, and the clock."""
    new.host_key = old.host_key
    touch(new)


def advance(code: str) -> Room | None:
    """Move a room to the next level, carrying every player's score forward.

    Returns None if the campaign is over. Scores carry but `guessed` does not --
    each round is a fresh chance to call it.
    """
    code = code.upper()
    old = rooms.get(code)
    if not old or old.is_last:
        return None

    room = build(code, old.level + 1)
    for name, player in old.players.items():
        room.add_player(name)["score"] = player["score"]
    _carry(old, room)
    rooms[code] = room
    return room


def reset(code: str) -> Room:
    code = code.upper()
    old = rooms.get(code)
    room = build(code, old.level if old else 1)
    if old:
        _carry(old, room)
    touch(room)
    rooms[code] = room
    return room


def claim_host(room: Room, key: str | None) -> str | None:
    """The projector that owns a room gets a key; phones never have it.

    The first screen to claim an unowned room owns it. A screen presenting the
    key it was given (it keeps it across reloads) is recognised again. Anyone
    else is refused, which is what stops a phone in the audience from killing
    the patient or resetting the round.
    """
    if room.host_key is None:
        room.host_key = key if (isinstance(key, str) and 16 <= len(key) <= 64) else secrets.token_urlsafe(24)
        return room.host_key
    if isinstance(key, str) and secrets.compare_digest(key, room.host_key):
        return room.host_key
    return None


def is_host(room: Room, key) -> bool:
    return room.host_key is not None and isinstance(key, str) and secrets.compare_digest(key, room.host_key)


def reap(now: float | None = None, has_watchers=lambda code: False) -> int:
    """Drop rooms idle for IDLE_SECONDS that nobody is watching."""
    now = time.monotonic() if now is None else now
    stale = [c for c, r in rooms.items()
             if now - getattr(r, "touched", now) > IDLE_SECONDS and not has_watchers(c)]
    for c in stale:
        rooms.pop(c, None)
    return len(stale)


def opening_card(level: int = 1):
    return load_case(case_for_level(level)).get("level_card")
