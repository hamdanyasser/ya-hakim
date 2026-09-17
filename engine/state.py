"""The only thing clients ever receive.

GameState is constructed explicitly, field by field. The internal room object is
never serialised and stripped -- that is the pattern that leaks, because a field
added to the room later is included by default. Here, a field added to the room
is absent by default and someone has to deliberately write a line to include it.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field


@dataclass
class GameState:
    room_code: str
    phase: str            # lobby | playing | flatline | reveal
    patient_name: str
    patient_age: int
    patient_sex: str      # male | female | "" -- picks the voice the patient speaks in
    description: str      # short, non-medical bio line -- same allowlist as personality
    mood: str             # guarded | uneasy | defensive | rattled | scared |
                           # pleading | resigned | flatline -- see engine/mood.py
    vitals: dict          # hr, spo2, bp, rr
    status: str           # stable | declining | critical | flatline
    seconds_left: int
    messages: list        # [{who, text, kind: "question"|"reply"}]
    players: list         # [{name, score, guessed: bool}]
    reveal: dict | None = None   # populated ONLY in phase == "reveal"

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)
