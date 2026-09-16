"""What the monitor shows. Pure functions, no AI anywhere near them.

Two rules make this testable:

1. `elapsed_s` is EFFECTIVE decline time, not wall time. The room object stops
   accumulating it while he is stabilised, so this function never has to know
   how many times he was stabilised or when. That keeps it pure and correct
   across any number of overlapping stabilisations -- a function of wall time
   and a single `stabilised_until` deadline could not be.

2. The lie spike is an ADDITIVE term applied on top, never folded into the
   decline. Decline therefore stays monotonic and stays easy to assert.
"""

from __future__ import annotations

# Thresholds. critical is specified; declining is the band before it.
CRITICAL_SPO2 = 88
CRITICAL_HR = 140
DECLINING_SPO2 = 94
DECLINING_HR = 115

# How hard his heart jumps while he is telling the lie, and for how long.
LIE_SPIKE_BPM = 18.0
LIE_SPIKE_SECONDS = 6.0


def lie_spike_at(seconds_since_lie: float | None) -> float:
    """0..1 intensity of the tell. Rises instantly, decays over LIE_SPIKE_SECONDS.

    This is the mechanic that makes the monitor worth watching: he says the
    calm thing and his heart disagrees with him in front of the whole room.
    """
    if seconds_since_lie is None or seconds_since_lie < 0:
        return 0.0
    if seconds_since_lie >= LIE_SPIKE_SECONDS:
        return 0.0
    return 1.0 - (seconds_since_lie / LIE_SPIKE_SECONDS)


def vitals_at(case, elapsed_s, stabilised_until=None, seconds_since_lie=None):
    """The monitor reading after `elapsed_s` seconds of effective decline.

    `stabilised_until` is accepted so callers can pass the room's deadline, but
    the freeze is applied by the room when it accumulates `elapsed_s`. It is not
    read here, and must not be -- that is what keeps this function pure.
    """
    start = case["vitals_start"]
    rate = case["vitals_decline"]
    minutes = max(0.0, elapsed_s) / 60.0

    hr = start["hr"] + rate["hr"] * minutes
    spo2 = start["spo2"] + rate["spo2"] * minutes
    sys = start["sys"] + rate["sys"] * minutes
    dia = start["dia"] + rate["dia"] * minutes
    rr = start["rr"] + rate["rr"] * minutes

    hr += LIE_SPIKE_BPM * lie_spike_at(seconds_since_lie)

    hr = _clamp(hr, 0, 260)
    spo2 = _clamp(spo2, 0, 100)
    sys = _clamp(sys, 0, 260)
    dia = _clamp(dia, 0, 200)
    rr = _clamp(rr, 0, 80)

    return {
        "hr": int(round(hr)),
        "spo2": int(round(spo2)),
        "bp": "%d/%d" % (round(sys), round(dia)),
        "rr": int(round(rr)),
    }


def dead_vitals():
    """What the monitor shows once he is gone."""
    return {"hr": 0, "spo2": 0, "bp": "0/0", "rr": 0}


def status_for(vitals) -> str:
    """stable | declining | critical | flatline"""
    if vitals["hr"] <= 0:
        return "flatline"
    if vitals["spo2"] < CRITICAL_SPO2 or vitals["hr"] > CRITICAL_HR:
        return "critical"
    if vitals["spo2"] < DECLINING_SPO2 or vitals["hr"] > DECLINING_HR:
        return "declining"
    return "stable"


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v
