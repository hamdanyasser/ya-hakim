"""How he is holding himself, moment to moment. Pure, no AI, no secrets.

Derived only from signals already public on the room: the vitals colour,
whether he has cracked, how many times the one topic has been pressed,
whether he is mid-lie-spike, and how much time is left. Nothing here reads a
case's diagnosis, accepted_answers or key_questions, so a mood can be sent to
every client in every phase without going anywhere near the allowlist.

`test_mood.py` holds this to the same bar as vitals.py: pure functions,
deterministic, and safe against every case's secrets by construction.
"""

from __future__ import annotations

# label: what a client shows. icon: a plain-text glyph, generated in code like
# everything else on the projector -- no image files, nothing downloaded.
MOODS = {
    "guarded":   {"label": "Guarded",   "icon": "\U0001F6E1"},
    "uneasy":    {"label": "Uneasy",    "icon": "\U0001F615"},
    "defensive": {"label": "Defensive", "icon": "✋"},
    "rattled":   {"label": "Rattled",   "icon": "\U0001F62C"},
    "scared":    {"label": "Scared",    "icon": "\U0001F628"},
    "pleading":  {"label": "Pleading",  "icon": "\U0001F64F"},
    "resigned":  {"label": "Resigned",  "icon": "\U0001F614"},
}


def mood_for(status, cracked, pressed, telling_lie, seconds_left):
    """One word for how he is presenting right now.

    Priority is deliberate, checked top to bottom:

    1. `telling_lie` always wins. This is the exact moment the heart-rate tell
       fires, and it is the one thing the game is built around ("the monitor
       tells you when he is lying") -- the mood badge should say so too.
    2. Critical vitals beat everything except the tell, because a man who is
       actually dying stops performing for the room. Near the very end
       ("pleading") reads differently from merely "scared".
    3. Once he has cracked, the front is down -- "resigned", not defensive.
    4. Being pressed on the one thing he is guarding, before he cracks, reads
       as "defensive".
    5. Otherwise it is just the vitals: declining is "uneasy", anything else
       is the default "guarded".
    """
    if telling_lie:
        return "rattled"
    if status == "critical":
        return "pleading" if seconds_left <= 20 else "scared"
    if cracked:
        return "resigned"
    if pressed >= 1:
        return "defensive"
    if status == "declining":
        return "uneasy"
    return "guarded"
