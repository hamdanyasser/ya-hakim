"""Decline is monotonic, thresholds fire, and stabilising buys exactly 45s."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine import vitals
from engine.game import ROUND_SECONDS, STABILISE_SECONDS, Room
from engine.vitals import dead_vitals, lie_spike_at, status_for, vitals_at

CASES_DIR = Path(__file__).resolve().parent.parent / "cases"


def load(case_id="kamal"):
    with open(CASES_DIR / (case_id + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def case():
    return load()


# ------------------------------------------------------------------ decline

def test_decline_is_monotonic(case):
    """Without the lie spike, he only ever gets worse."""
    prev = vitals_at(case, 0)
    for t in range(1, ROUND_SECONDS + 1):
        v = vitals_at(case, t)
        assert v["hr"] >= prev["hr"]
        assert v["spo2"] <= prev["spo2"]
        assert v["rr"] >= prev["rr"]
        prev = v


def test_decline_starts_at_the_case_values(case):
    v = vitals_at(case, 0)
    s = case["vitals_start"]
    assert v["hr"] == s["hr"]
    assert v["spo2"] == s["spo2"]
    assert v["bp"] == "%d/%d" % (s["sys"], s["dia"])


def test_vitals_never_go_out_of_physical_range(case):
    for t in range(0, 3000, 17):
        v = vitals_at(case, t)
        assert 0 <= v["spo2"] <= 100
        assert 0 <= v["hr"] <= 260
        assert 0 <= v["rr"] <= 80


# ---------------------------------------------------------------- thresholds

def test_status_thresholds_fire():
    assert status_for({"hr": 96, "spo2": 97}) == "stable"
    assert status_for({"hr": 120, "spo2": 97}) == "declining"   # hr > 115
    assert status_for({"hr": 96, "spo2": 92}) == "declining"    # spo2 < 94
    assert status_for({"hr": 141, "spo2": 97}) == "critical"    # hr > 140
    assert status_for({"hr": 96, "spo2": 87}) == "critical"     # spo2 < 88
    assert status_for(dead_vitals()) == "flatline"


def test_status_boundaries_are_exact():
    """The spec says critical if spo2 < 88 or hr > 140. Not <= and not >=."""
    assert status_for({"hr": 140, "spo2": 97}) != "critical"
    assert status_for({"hr": 141, "spo2": 97}) == "critical"
    assert status_for({"hr": 96, "spo2": 88}) != "critical"
    assert status_for({"hr": 96, "spo2": 87}) == "critical"


def test_he_actually_reaches_critical_inside_a_round(case):
    """Otherwise the red state never appears and the +50 bonus is free.

    This is the test that would have caught the spec's original decline rates,
    which needed 11 minutes to reach critical in a 150 second round.
    """
    assert status_for(vitals_at(case, ROUND_SECONDS)) == "critical"
    assert status_for(vitals_at(case, 0)) == "stable"

    seen = {status_for(vitals_at(case, t)) for t in range(ROUND_SECONDS + 1)}
    assert seen == {"stable", "declining", "critical"}, (
        "a round should pass through every colour, saw " + str(seen)
    )


# --------------------------------------------------------------- the tell

def test_lie_spike_rises_and_decays():
    assert lie_spike_at(0) == 1.0
    assert lie_spike_at(vitals.LIE_SPIKE_SECONDS / 2) == pytest.approx(0.5)
    assert lie_spike_at(vitals.LIE_SPIKE_SECONDS) == 0.0
    assert lie_spike_at(999) == 0.0
    assert lie_spike_at(None) == 0.0


def test_lie_spike_raises_heart_rate_visibly(case):
    calm = vitals_at(case, 30)["hr"]
    lying = vitals_at(case, 30, seconds_since_lie=0)["hr"]
    assert lying - calm >= 15, "the tell must be readable from the back of a room"


def test_lie_spike_does_not_touch_anything_but_heart_rate(case):
    calm = vitals_at(case, 30)
    lying = vitals_at(case, 30, seconds_since_lie=0)
    assert calm["spo2"] == lying["spo2"]
    assert calm["bp"] == lying["bp"]
    assert calm["rr"] == lying["rr"]


# ------------------------------------------------- stabilising, through Room

def _room(case, level=1):
    t = {"now": 0.0}
    room = Room(case, clock=lambda: t["now"])
    room.add_player("Sara")
    room.start()

    def run_to(target):
        while t["now"] < target:
            t["now"] += 1.0
            room.tick()

    return room, t, run_to


def test_stabilising_pauses_decline_for_exactly_45s(case):
    room, t, run_to = _room(case)
    run_to(10)
    assert room.decline_elapsed == pytest.approx(10, abs=0.01)

    room.ask("Sara", "how much do you drink?")          # stabilises until t=55
    assert room.stabilised_until == pytest.approx(10 + STABILISE_SECONDS)

    run_to(54)
    assert room.decline_elapsed == pytest.approx(10, abs=0.01), "decline resumed early"

    run_to(100)
    # Frozen for exactly 45 seconds, so decline is wall time minus 45.
    assert room.decline_elapsed == pytest.approx(100 - STABILISE_SECONDS, abs=1.01)


def test_overlapping_stabilisations_accumulate(case):
    """The case a pure function of (wall_time, stabilised_until) gets wrong.

    Stabilise at t=10 (until 55), then again at t=30. The second one extends
    from the existing deadline, not from t=30, so he is frozen 10 -> 100.
    """
    room, t, run_to = _room(case)
    run_to(10)
    room.ask("Sara", "how much do you drink?")
    run_to(30)
    room.ask("Sara", "are your eyes yellow?")
    assert room.stabilised_until == pytest.approx(100)

    run_to(150)
    assert room.decline_elapsed == pytest.approx(150 - 90, abs=1.01)


def test_a_topic_only_buys_time_once(case):
    """Otherwise the room keeps him alive forever on one good question."""
    room, t, run_to = _room(case)
    run_to(10)
    room.ask("Sara", "how much do you drink?")
    first = room.stabilised_until
    run_to(20)
    room.ask("Sara", "so how much do you drink really?")
    assert room.stabilised_until == first, "the same topic stabilised twice"


def test_the_clock_still_runs_while_stabilised(case):
    """Stabilising freezes the decline, never the round."""
    room, t, run_to = _room(case)
    run_to(10)
    room.ask("Sara", "how much do you drink?")
    run_to(40)
    assert room.seconds_left() == pytest.approx(ROUND_SECONDS - 40, abs=1)


def test_round_ends_in_flatline_at_zero(case):
    room, t, run_to = _room(case)
    run_to(ROUND_SECONDS + 1)
    assert room.phase == "flatline"
    assert room.seconds_left() == 0
    assert room.public_state().status == "flatline"
    assert room.public_state().vitals["hr"] == 0


def test_rate_limit_is_enforced_server_side(case):
    """A player with devtools open must not be able to spam the model."""
    from engine.game import ASK_COOLDOWN

    room, t, run_to = _room(case)
    run_to(10)
    assert room.ask("Sara", "do you smoke?", now=t["now"]) is not None
    assert room.ask("Sara", "do you smoke again?", now=t["now"]) is None, \
        "second question inside the cooldown was accepted"

    t["now"] += ASK_COOLDOWN + 0.1
    assert room.ask("Sara", "and now?", now=t["now"]) is not None


def test_rate_limit_is_per_player(case):
    room, t, run_to = _room(case)
    run_to(10)
    assert room.ask("Sara", "do you smoke?", now=t["now"]) is not None
    assert room.ask("Omar", "do you smoke?", now=t["now"]) is not None, \
        "one player's cooldown blocked another player"
