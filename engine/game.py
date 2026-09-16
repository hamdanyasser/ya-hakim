"""The room. One patient, one clock, one set of players.

The clock and the decline clock are deliberately separate. The round always
lasts ROUND_SECONDS of wall time; stabilising freezes only the DECLINE, so the
room still runs out of time but he arrives at the end in better shape. That is
what makes a good question feel like it bought something.
"""

from __future__ import annotations

import time

from engine import scoring
from engine.patient import CannedPatient, FALLBACKS
from engine.state import GameState
from engine.vitals import dead_vitals, status_for, vitals_at

ROUND_SECONDS = 150          # 2.5 minutes
STABILISE_SECONDS = 45
MAX_MESSAGES = 60


class Room:
    def __init__(self, case, room_code="TEST", level=1, clock=time.monotonic,
                 patient=None):
        self.case = case
        self.room_code = room_code
        self.level = level
        self.clock = clock
        self.patient = patient or CannedPatient(case)

        self.phase = "lobby"
        self.players = {}            # name -> {"name","score","guessed"}
        self.messages = []

        self.wall_elapsed = 0.0      # always advances while playing
        self.decline_elapsed = 0.0   # frozen while stabilised
        self.stabilised_until = 0.0
        self.last_tick = None

        self.covered_topics = set()  # each key topic stabilises once
        self.drink_asks = 0          # engine-owned; decides when he cracks
        self.cracked = False
        self.lied_at = None          # drives the heart-rate tell
        self.ever_critical = False

        self.correct_guessers = []   # in order, for 100 / 60 / 40
        self.killed_by_wrong_answer = False
        self.scored = False

    # ------------------------------------------------------------- lifecycle

    def add_player(self, name):
        name = (name or "").strip()[:18] or "Doctor"
        if name not in self.players:
            self.players[name] = {"name": name, "score": 0, "guessed": False}
        return self.players[name]

    def start(self):
        self.phase = "playing"
        self.last_tick = self.clock()
        self.say(self.case["name"], self.case["opening_line"], "reply")

    def tick(self, now=None):
        """Called once a second. Advances the two clocks and ends the round."""
        now = self.clock() if now is None else now
        if self.last_tick is None:
            self.last_tick = now
        dt = max(0.0, now - self.last_tick)
        self.last_tick = now

        if self.phase != "playing":
            return

        self.wall_elapsed += dt
        if now >= self.stabilised_until:
            self.decline_elapsed += dt

        if status_for(self.current_vitals(now)) == "critical":
            self.ever_critical = True

        if self.wall_elapsed >= ROUND_SECONDS:
            self.flatline()

    def flatline(self):
        self.phase = "flatline"
        self.finish_scoring()

    def reveal(self):
        self.phase = "reveal"

    def finish_scoring(self):
        if self.scored:
            return
        self.scored = True
        scoring.final_scores(list(self.players.values()), self.ever_critical)

    # ---------------------------------------------------------------- vitals

    def current_vitals(self, now=None):
        if self.phase in ("flatline", "reveal"):
            return dead_vitals()
        now = self.clock() if now is None else now
        since_lie = None if self.lied_at is None else max(0.0, now - self.lied_at)
        return vitals_at(self.case, self.decline_elapsed,
                         stabilised_until=self.stabilised_until,
                         seconds_since_lie=since_lie)

    def status(self):
        if self.phase in ("flatline", "reveal"):
            return "flatline"
        return status_for(self.current_vitals())

    # -------------------------------------------------------------- the loop

    def say(self, who, text, kind):
        self.messages.append({"who": who, "text": text, "kind": kind})
        if len(self.messages) > MAX_MESSAGES:
            del self.messages[: len(self.messages) - MAX_MESSAGES]

    def ask(self, player_name, question, now=None):
        """A player asks the patient something. Returns his reply."""
        if self.phase != "playing":
            return None
        now = self.clock() if now is None else now
        player = self.add_player(player_name)
        self.say(player["name"], question, "question")

        topic = scoring.covers_key_topic(self.case, question)
        drink_topic = self.case["key_questions"][0]

        # Asking what his wife thinks is the other thing that breaks him, so it
        # counts as pressing him on the drinking -- it must not read as a wasted
        # question. Checked only after the keyword pass, so "what does your wife
        # say about your eyes" still lands on the eyes topic.
        if topic is None and "wife" in (question or "").lower():
            topic = drink_topic

        if topic is None:
            player["score"] += scoring.WASTED_QUESTION
        else:
            # A topic buys time once. Otherwise the room could hold him alive
            # forever by asking the same good question on a loop.
            if topic not in self.covered_topics:
                self.covered_topics.add(topic)
                self.stabilised_until = max(self.stabilised_until, now) + STABILISE_SECONDS

            if topic == drink_topic:
                self.drink_asks += 1
                if self.drink_asks >= 2:
                    self.cracked = True

        if "wife" in (question or "").lower():
            self.cracked = True

        reply = self.patient.reply(question, cracked=self.cracked, topic=topic)
        if not reply:
            reply = FALLBACKS[0]

        # He is telling the lie -> his heart disagrees with him, in front of
        # everyone. This is the whole reason the monitor is worth watching.
        if reply == self.case["lie"]:
            self.lied_at = now

        self.say(self.case["name"], reply, "reply")
        return reply

    def guess(self, player_name, text):
        """A player commits to a diagnosis."""
        if self.phase not in ("playing", "flatline"):
            return False
        player = self.add_player(player_name)
        if player["guessed"]:
            return False
        player["guessed"] = True

        if scoring.match_guess(self.case, text):
            place = len(self.correct_guessers)
            self.correct_guessers.append(player["name"])
            player["score"] += scoring.award_guess(place)
            return True

        # Higher levels are unforgiving: a wrong call costs him his life.
        if self.level >= 3 and self.phase == "playing":
            self.killed_by_wrong_answer = True
            self.flatline()
        return False

    # ----------------------------------------------------------- what leaves

    def seconds_left(self):
        return max(0, int(round(ROUND_SECONDS - self.wall_elapsed)))

    def reveal_payload(self):
        """The one place the diagnosis legitimately reaches a client.

        Built only when the round is over. Nothing here is reachable in any
        other phase, because public_state() passes None instead.
        """
        won = bool(self.correct_guessers)
        return {
            "diagnosis": self.case["diagnosis"],
            "winners": list(self.correct_guessers),
            "died": True,
            "won": won,
            "killed_by_wrong_answer": self.killed_by_wrong_answer,
            "headline": self._headline(won),
            "scores": sorted(
                [dict(p) for p in self.players.values()],
                key=lambda p: -p["score"],
            ),
        }

    def _headline(self, won):
        if won and self.killed_by_wrong_answer:
            return "He died. Someone still called it."
        if won:
            return "He died. You were right."
        if self.killed_by_wrong_answer:
            return "He died. Nobody called it."
        return "Time ran out."

    def public_state(self) -> GameState:
        """Constructed field by field. The room object is never serialised."""
        return GameState(
            room_code=self.room_code,
            phase=self.phase,
            patient_name=self.case["name"],
            patient_age=self.case["age"],
            vitals=self.current_vitals(),
            status=self.status(),
            seconds_left=self.seconds_left(),
            messages=list(self.messages),
            players=sorted(
                [dict(p) for p in self.players.values()], key=lambda p: -p["score"]
            ),
            reveal=self.reveal_payload() if self.phase == "reveal" else None,
        )
