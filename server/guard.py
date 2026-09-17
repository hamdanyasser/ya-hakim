"""Request hygiene shared by every router: reading untrusted JSON fields, and
in-memory rate limits.

Every endpoint takes `payload: dict`, so any field can arrive as a number, a
list or null. Reading them through `text()` / `number()` means a malformed
request gets a 400 instead of an AttributeError and a 500.

The rate limits are per process, which matches how this app is deployed (one
uvicorn process, see Dockerfile). They exist to stop two things: password
guessing, and strangers spending the model budget through the public pages.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


def text(payload, key: str, limit: int = 1000, default: str = "") -> str:
    """A string field, stripped and capped. Non-strings are refused."""
    if not isinstance(payload, dict):
        raise HTTPException(400, "Send a JSON object.")
    value = payload.get(key)
    if value is None:
        return default
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        raise HTTPException(400, "'%s' must be text." % key)
    return value.strip()[:limit]


def number(payload, key: str, default=None, lo=None, hi=None):
    """A numeric field. Accepts numbers or numeric strings; refuses the rest."""
    if not isinstance(payload, dict):
        raise HTTPException(400, "Send a JSON object.")
    value = payload.get(key)
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise HTTPException(400, "'%s' must be a number." % key)
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise HTTPException(400, "'%s' must be a number." % key)
    if value != value or value in (float("inf"), float("-inf")):
        raise HTTPException(400, "'%s' must be a number." % key)
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


def client_ip(request: Request) -> str:
    return (request.client.host if request.client else "") or "unknown"


class RateLimit:
    """Sliding window: at most `limit` events per `window` seconds per key."""

    def __init__(self, limit: int, window: float):
        self.limit = limit
        self.window = window
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, now: float | None = None) -> float:
        """Record an event. Returns 0 if allowed, else seconds until allowed."""
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                return max(0.1, q[0] + self.window - now)
            q.append(now)
            if len(self._hits) > 50_000:          # never grow without bound
                for k in [k for k, v in self._hits.items() if not v][:25_000]:
                    del self._hits[k]
            return 0.0

    def check(self, key: str, message: str = "Too many requests. Try again shortly."):
        wait = self.hit(key)
        if wait:
            raise HTTPException(429, message + " (%ds)" % max(1, round(wait)),
                                headers={"Retry-After": str(max(1, round(wait)))})

    def reset(self):
        with self._lock:
            self._hits.clear()
