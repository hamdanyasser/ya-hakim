"""How one question lands. Shared by classroom rooms and solo practice.

Given the case, the question, and how hard the hidden topic has been pressed
so far, decide: which key topic (if any) this covers, whether the patient
cracks, and whether this turn is the lie. Pure -- no clocks, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine import scoring

CRACK_AFTER = 2   # pressing the hidden topic this many times breaks the front


@dataclass
class Landing:
    topic: str | None
    lie_asks: int
    cracked: bool
    telling_lie: bool


def land(case: dict, question: str, lie_asks: int, cracked: bool) -> Landing:
    low = (question or "").lower()
    lie_topic = case["key_questions"][0]
    topic = scoring.covers_key_topic(case, question)

    # A case can name other ways in -- asking the person who brought them in,
    # or asking what worries them. Those count as pressing the hidden topic,
    # and they break it at once. Checked after the keyword pass so "what does
    # your wife say about your eyes" still lands on the eyes topic.
    crack_hit = any(k.lower() in low for k in case.get("crack_keywords", []))
    if topic is None and crack_hit:
        topic = lie_topic

    if topic == lie_topic:
        lie_asks += 1
        if lie_asks >= CRACK_AFTER:
            cracked = True
    if crack_hit:
        cracked = True

    # The lie is told exactly when the hidden topic is raised and the front
    # is still up -- whatever words the reply itself uses.
    telling_lie = topic == lie_topic and not cracked
    return Landing(topic=topic, lie_asks=lie_asks, cracked=cracked,
                   telling_lie=telling_lie)
