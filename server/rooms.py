"""The room registry and the campaign.

Rooms live in memory. There is no database, and nothing here is persisted --
closing the server ends every round, which is correct for a party game.
"""

from __future__ import annotations

import random

from engine import llm
from engine.game import Room
from engine.patient import CannedPatient, PatientSession, load_case

# No 0/O and no 1/I/L. Someone is reading this off a projector.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

# The campaign, in order. Level 1 is the trial: he cannot die of a wrong call.
# Level 3 is unforgiving -- a wrong answer kills him (see Room.guess).
LEVELS = ["kamal", "rita", "georges"]

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


def get_or_make(code: str | None = None, level: int = 1) -> Room:
    if code and code.upper() in rooms:
        return rooms[code.upper()]
    code = (code or new_code()).upper()
    room = build(code, level)
    rooms[code] = room
    return room


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
    rooms[code] = room
    return room


def reset(code: str) -> Room:
    code = code.upper()
    level = rooms[code].level if code in rooms else 1
    rooms.pop(code, None)
    return get_or_make(code, level)


def opening_card(level: int = 1):
    return load_case(case_for_level(level)).get("level_card")
