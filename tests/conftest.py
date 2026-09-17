"""Tests do not spend money.

Once a real key is in .env, anything that calls llm.available() takes the live
path -- so the suite started making hundreds of API calls, took two minutes
instead of two seconds, and cost real credits on every run. Worse, tests named
"offline" silently began exercising the live path and failing, but only on a
machine that had a key: CI stayed green because CI has none.

So the key is removed from the environment for every test by default. The suite
is then deterministic, free, and identical everywhere.

To deliberately exercise the live model -- the 100 attacks against the real
patient, which is the number worth quoting on stage:

    YH_LIVE=1 pytest tests/test_injection.py
"""

from __future__ import annotations

import os

import pytest

LIVE = os.environ.get("YH_LIVE") == "1"


@pytest.fixture(autouse=True)
def _no_api_calls(monkeypatch):
    if LIVE:
        return
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(var, raising=False)

    # engine.llm caches a client on first use; drop it so a client built from a
    # real key in an earlier test cannot survive into this one.
    try:
        from engine import llm
        monkeypatch.setattr(llm, "_client", None, raising=False)
    except Exception:
        pass
