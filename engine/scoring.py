"""Points, and deciding whether a guess is right.

Non-doctors are playing. Matching is deliberately generous: "liver" counts.
The only thing guarded against is a guess that scores while saying the opposite
("it is not his liver"), which a plain substring check would happily accept.
"""

from __future__ import annotations

import re

FIRST, SECOND, THIRD = 100, 60, 40
WASTED_QUESTION = -5
NEVER_CRITICAL_BONUS = 50

_NEGATIONS = {
    "not", "isnt", "isn't", "arent", "aren't", "no", "nope", "never",
    "doubt", "cant", "can't", "wasnt", "wasn't", "dont", "don't",
}

# How much a correct guess is worth, by how many people got there first.
_PLACE_POINTS = [FIRST, SECOND, THIRD]


def _tokens(text: str):
    return re.findall(r"[a-z']+", text.lower())


def match_guess(case, guess: str) -> bool:
    """Is this guess right? Generous, but not fooled by a negation.

    Substring matching is intentional -- "his liver is shot" should score. A
    negation in the two tokens immediately before the match rejects it, which
    catches "not the liver" while still accepting "not sure but liver".
    """
    if not guess or not guess.strip():
        return False
    low = guess.lower()
    for answer in case["accepted_answers"]:
        ans = answer.lower()
        for m in re.finditer(re.escape(ans), low):
            before = _tokens(low[: m.start()])[-2:]
            if not any(t in _NEGATIONS for t in before):
                return True
    return False


def covers_key_topic(case, question: str):
    """Which key question this covers, or None. The offline fallback path.

    Reads key_questions and key_keywords, which are secret and never enter a
    prompt. This runs server-side only.
    """
    if not question:
        return None
    toks = set(_tokens(question))
    low = question.lower()
    for i, kq in enumerate(case["key_questions"]):
        for kw in case["key_keywords"][i]:
            kw = kw.lower()
            if " " in kw:
                if kw in low:
                    return kq
            elif kw in toks:
                return kq
    return None


def award_guess(place: int) -> int:
    """place is 0-based: the first person to get it scores 100."""
    if 0 <= place < len(_PLACE_POINTS):
        return _PLACE_POINTS[place]
    return 0


def final_scores(players, ever_critical: bool):
    """Apply the end-of-round bonus. players is a list of dicts with 'score'.

    The bonus is a ROOM outcome -- they kept him off the edge together -- so
    everyone who took part gets it. Awarding it per-player would punish the
    person who happened to ask the question that came too late.
    """
    if ever_critical:
        return players
    for p in players:
        p["score"] = p.get("score", 0) + NEVER_CRITICAL_BONUS
    return players
