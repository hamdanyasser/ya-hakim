"""The one place the app talks to Claude.

Every call site (patient voice, attending feedback, case drafting) goes through
here so model choice, refusal fallbacks and "is a key configured at all" live
in exactly one file.

Nothing in this module decides WHAT is sent -- the allowlist in patient.py and
the payload builders in grading.py / authoring.py own that. This only sends it.
"""

from __future__ import annotations

import json
import os

import anthropic

# One model for everything by default; override per deployment.
MODEL = os.environ.get("YH_MODEL", "claude-opus-5")

# Claude Opus 5 can decline a request on policy grounds. Medical role-play sits
# close enough to that line that a declined turn must not end an encounter, so
# a decline is re-run server-side on Anthropic's recommended fallback model.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

_client = None


def available() -> bool:
    """True when a live model can be used. The app is fully playable without."""
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def create(**kwargs):
    """messages.create with refusal fallbacks switched on."""
    kwargs.setdefault("model", MODEL)
    return client().beta.messages.create(
        betas=[FALLBACK_BETA],
        fallbacks="default",
        **kwargs,
    )


def text_of(response) -> str:
    return "".join(b.text for b in response.content if getattr(b, "type", None) == "text")


def json_call(system: str, user: str, schema: dict, *, effort: str = "high",
              max_tokens: int = 16000, timeout: float = 120.0) -> dict | None:
    """One structured-output call. Returns the parsed object, or None on any
    failure -- every caller has a deterministic path that does not need this."""
    try:
        resp = client().with_options(timeout=timeout).beta.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={
                "effort": effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        )
    except anthropic.APIError:
        return None
    if resp.stop_reason in ("refusal", "max_tokens"):
        return None
    try:
        return json.loads(text_of(resp))
    except (ValueError, TypeError):
        return None
