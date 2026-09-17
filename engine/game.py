"""The classroom room. One patient, one clock, one set of players.

This is the group mode -- a lecture theatre or a seminar room, one projector,
everyone on their phones. The clock and the decline clock are deliberately
separate: the round always lasts ROUND_SECONDS of wall time; a good question
freezes only the DECLINE, so the room still runs out of time but the patient
arrives at the end in better shape. That is what makes a good question feel
like it bought something.

How a question lands (topic, cracking, the lie) is shared with solo practice
in engine/encounter.py.
"""

from __future__ import annotations

import threading
import time

from engine import scoring
from engine.encounter import land
from engine.mood import mood_for
from engine.patient import CannedPatient, FALLBACKS
from engine.state import GameState
from engine.vitals import dead_vitals, lie_spike_at, status_for, vitals_at

ROUND_SECONDS = 150          # 2.5 minutes
STABILISE_SECONDS = 45
MAX_MESSAGES = 60
ASK_COOLDOWN = 8             # per player, seconds, when several are playing
SOLO_COOLDOWN = 1.5          # one person at the laptop: double-submit guard only


class Room:
    def __init__(self, case, room_code="TEST", level=1, clock=time.monotonic,
                 patient=None, next_card=None, is_last=True):
        self.case = case
        self.room_code = room_code
        self.level = level
        self.next_card = next_card    # the card shown before the NEXT round
        self.is_last = is_last
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
        self.lie_asks = 0            # engine-owned; decides when the front drops
        self.cracked = False
        self.lied_at = None          # drives the heart-rate tell
        self.ever_critical = False

        self.last_ask = {}           # player -> when they last asked
        self.correct_guessers = []   # in order, for 100 / 60 / 40
        self.killed_by_wrong_answer = False
        self.scored = False

        # Server bookkeeping, not game state: who hosts the room, when it was
        # last used, and a lock so two phones asking at once cannot interleave
        # their turns in the transcript or the live patient's history.
        self.host_key = None
        self.touched = 0.0
        self.ask_lock = threading.Lock()

        # The story of the round, for the case file at the reveal: who drew
        # the lie out, who broke him, who found each clue, who talked a lot and
        # found nothing. Never sent before the reveal.
        self.lie_heard = None        # {"by", "at", "question"}
        self.cracked_by = None       # {"by", "at", "question"}
        self.found_by = {}           # key question -> {"by", "at"}
        self.stats = {}              # player -> {"asked", "useful", "wasted"}
        self.fatal_guess = None      # {"by", "guess"}

    # ------------------------------------------------------------- lifecycle

    def add_player(self, name):
        name = (name or "").strip()[:18] or "Doctor"
        if name not in self.players:
            self.players[name] = {"name": name, "score": 0, "guessed": False}
            self.last_ask[name] = -1e9
        return self.players[name]

    def cooldown_left(self, name, now):
        """Seconds until this player may ask again. 0 means go ahead.

        The cooldown exists to stop a roomful of people spending the API budget
        in thirty seconds. With one person at the laptop there is no budget to
        race for, so it drops to a double-submit guard -- an 8 second wait for a
        solo player is just the game refusing to be played.
        """
        limit = ASK_COOLDOWN if len(self.players) > 1 else SOLO_COOLDOWN
        left = limit - (now - self.last_ask.get(name, -1e9))
        return max(0.0, left)

    def on_cooldown(self, name, now):
        return self.cooldown_left(name, now) > 0

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

    def mood(self, now=None):
        """How the patient is holding up right now. Engine-derived, never a
        secret -- see engine/mood.py."""
        if self.phase in ("flatline", "reveal"):
            return "flatline"
        now = self.clock() if now is None else now
        since_lie = None if self.lied_at is None else max(0.0, now - self.lied_at)
        return mood_for(
            status=status_for(self.current_vitals(now)),
            cracked=self.cracked,
            pressed=self.lie_asks,
            telling_lie=lie_spike_at(since_lie) > 0,
            seconds_left=self.seconds_left(),
        )

    # -------------------------------------------------------------- the loop

    def say(self, who, text, kind):
        self.messages.append({"who": who, "text": text, "kind": kind})
        if len(self.messages) > MAX_MESSAGES:
            del self.messages[: len(self.messages) - MAX_MESSAGES]

    def ask(self, player_name, question, now=None):
        """A player asks the patient something. Returns the reply."""
        if self.phase != "playing":
            return None
        question = (question or "").strip()
        if not question:
            return None
        now = self.clock() if now is None else now
        player = self.add_player(player_name)
        if self.on_cooldown(player["name"], now):
            return None
        self.last_ask[player["name"]] = now
        self.say(player["name"], question, "question")

        was_cracked = self.cracked
        landing = land(self.case, question, self.lie_asks, self.cracked)
        self.lie_asks = landing.lie_asks
        self.cracked = landing.cracked
        topic = landing.topic

        at = self.wall_elapsed
        mine = self.stats.setdefault(player["name"], {"asked": 0, "useful": 0, "wasted": 0})
        mine["asked"] += 1
        if topic is None:
            mine["wasted"] += 1
        elif topic not in self.found_by:
            mine["useful"] += 1
            self.found_by[topic] = {"by": player["name"], "at": at}
        if landing.telling_lie and self.lie_heard is None:
            self.lie_heard = {"by": player["name"], "at": at, "question": question}
        if self.cracked and not was_cracked:
            self.cracked_by = {"by": player["name"], "at": at, "question": question}

        if topic is None:
            player["score"] += scoring.WASTED_QUESTION
        elif topic not in self.covered_topics:
            # A topic buys time once. Otherwise the room could hold him alive
            # forever by asking the same good question on a loop.
            self.covered_topics.add(topic)
            self.stabilised_until = max(self.stabilised_until, now) + STABILISE_SECONDS

        current_mood = self.mood(now)
        reply = self.patient.reply(question, cracked=self.cracked, topic=topic,
                                    mood=current_mood)
        if not reply:
            reply = FALLBACKS[0]

        # The heart disagrees with the mouth, in front of everyone. This is the
        # whole reason the monitor is worth watching.
        if landing.telling_lie:
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
            self.fatal_guess = {"by": player["name"], "guess": (text or "").strip()[:80]}
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
        teaching = self.case.get("teaching")
        if isinstance(teaching, dict):
            teaching = teaching.get("summary")
        return {
            "diagnosis": self.case["diagnosis"],
            "winners": list(self.correct_guessers),
            "died": True,
            "won": won,
            "killed_by_wrong_answer": self.killed_by_wrong_answer,
            "headline": self._headline(won),
            "note": self.case.get("reveal_note") if won else None,
            "teaching": teaching,
            "level": self.level,
            "is_last": self.is_last,
            "next_card": None if self.is_last else self.next_card,
            "scores": sorted(
                [dict(p) for p in self.players.values()],
                key=lambda p: -p["score"],
            ),
            "case_file": self.case_file(),
            "awards": self.awards(),
        }

    def case_file(self):
        """What actually happened, told back to the room once it is over.

        The secret is out by now, so this is the one place the lie, the truth
        and the key questions are shown -- as the story of the round: what he
        hid, who caught it, and what nobody thought to ask and why it mattered.
        """
        kq = self.case["key_questions"]
        reasons = self.case.get("key_question_reasons") or []
        why = {q: (reasons[i] if i < len(reasons) else "") for i, q in enumerate(kq)}
        teaching = self.case.get("teaching")
        pearls = teaching.get("pearls", []) if isinstance(teaching, dict) else []
        return {
            "lie": self.case["lie"],
            "truth": self.case["truth"],
            "lie_topic": self.case.get("lie_topic"),
            "lie_heard": _clock(self.lie_heard),
            "cracked": _clock(self.cracked_by),
            "found": [{"topic": q, "by": self.found_by[q]["by"], "at": _mmss(ROUND_SECONDS - self.found_by[q]["at"]),
                       "why": why[q]} for q in kq if q in self.found_by],
            "missed": [{"topic": q, "why": why[q]} for q in kq if q not in self.found_by],
            "pearl": pearls[0] if pearls else None,
            "fatal_guess": self.fatal_guess,
        }

    def awards(self):
        """A superlative or two per round. The room remembers these more than
        the score -- and each one is a lesson wearing a joke."""
        out = []
        female = self.case.get("sex") == "female"
        pronoun, subject = ("her", "she") if female else ("him", "he")
        if self.lie_heard:
            out.append({"title": "Lie detector", "who": self.lie_heard["by"],
                        "why": "Asked the question %s lied to. The monitor caught it." % subject})
        if self.cracked_by:
            out.append({"title": "The confessor", "who": self.cracked_by["by"],
                        "why": "Got the truth out of %s." % pronoun})
        if self.correct_guessers:
            out.append({"title": "First to call it", "who": self.correct_guessers[0],
                        "why": "Right diagnosis, before anyone else."})
        if self.stats:
            best = max(self.stats.items(), key=lambda kv: (kv[1]["useful"], -kv[1]["asked"]))
            if best[1]["useful"] >= 2:
                out.append({"title": "Detective", "who": best[0],
                            "why": "Found %d of the clues that mattered." % best[1]["useful"]})
            chatty = max(self.stats.items(), key=lambda kv: kv[1]["wasted"])
            if chatty[1]["wasted"] >= 3:
                out.append({"title": "Bedside manner, no bedside point", "who": chatty[0],
                            "why": "%d questions. None of them bought %s a second." % (chatty[1]["wasted"], pronoun)})
        if self.fatal_guess:
            out.append({"title": "Malpractice", "who": self.fatal_guess["by"],
                        "why": "Called it \u201c%s\u201d. That was not it." % self.fatal_guess["guess"]})
        return out[:5]

    def _headline(self, won):
        pronoun = "She" if (self.case.get("sex") == "female") else "He"
        if won and self.killed_by_wrong_answer:
            return pronoun + " died. Someone still called it."
        if won:
            return pronoun + " died. You were right."
        if self.killed_by_wrong_answer:
            return pronoun + " died. Nobody called it."
        return "Time ran out."

    def public_state(self) -> GameState:
        """Constructed field by field. The room object is never serialised."""
        return GameState(
            room_code=self.room_code,
            phase=self.phase,
            patient_name=self.case["name"],
            patient_age=self.case["age"],
            patient_sex=self.case.get("sex") or "",
            description=self.case.get("description", ""),
            mood=self.mood(),
            vitals=self.current_vitals(),
            status=self.status(),
            seconds_left=self.seconds_left(),
            messages=list(self.messages),
            players=sorted(
                [dict(p) for p in self.players.values()], key=lambda p: -p["score"]
            ),
            reveal=self.reveal_payload() if self.phase == "reveal" else None,
        )


def _mmss(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return "%d:%02d" % (seconds // 60, seconds % 60)


def _clock(event):
    """An event with its time as the round clock showed it."""
    if not event:
        return None
    out = dict(event)
    out["at"] = _mmss(ROUND_SECONDS - event["at"])
    return out
