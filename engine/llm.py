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
# On a small budget set YH_MODEL=claude-haiku-4-5: about a fifth the cost, and
# for a patient who answers in two short sentences the difference barely shows.
MODEL = os.environ.get("YH_MODEL", "claude-opus-5")


def _supports_effort(model: str) -> bool:
    """output_config.effort is a 400 on Haiku 4.5 and the older models.

    Sending it anyway is how a cheap deployment discovers, live on stage, that
    every single AI call fails.
    """
    m = (model or "").lower()
    return not ("haiku" in m or "sonnet-4-5" in m or "sonnet-3" in m)


def _supports_fallbacks(model: str) -> bool:
    """Server-side refusal fallbacks exist for the models that can refuse."""
    m = (model or "").lower()
    return ("opus-5" in m or "opus-4-8" in m or "fable" in m or "mythos" in m)

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


def create(client=None, timeout=None, **kwargs):
    """messages.create, with only the options this model actually accepts."""
    kwargs.setdefault("model", MODEL)
    model = kwargs["model"]
    api = client or globals()["client"]()
    if timeout is not None:
        api = api.with_options(timeout=timeout)

    if not _supports_effort(model):
        cfg = dict(kwargs.get("output_config") or {})
        cfg.pop("effort", None)
        if cfg:
            kwargs["output_config"] = cfg
        else:
            kwargs.pop("output_config", None)

    if _supports_fallbacks(model):
        return api.beta.messages.create(
            betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
    return api.beta.messages.create(**kwargs)


def text_of(response) -> str:
    return "".join(b.text for b in response.content if getattr(b, "type", None) == "text")


def json_call(system: str, user: str, schema: dict, *, effort: str = "high",
              max_tokens: int = 16000, timeout: float = 120.0) -> dict | None:
    """One structured-output call. Returns the parsed object, or None on any
    failure -- every caller has a deterministic path that does not need this."""
    output_config = {"format": {"type": "json_schema", "schema": schema}}
    if _supports_effort(MODEL):
        output_config["effort"] = effort

    extra = {}
    if _supports_fallbacks(MODEL):
        extra = {"betas": [FALLBACK_BETA], "fallbacks": "default"}

    try:
        resp = client().with_options(timeout=timeout).beta.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config=output_config,
            **extra,
        )
    except anthropic.APIError:
        return None
    if resp.stop_reason in ("refusal", "max_tokens"):
        return None
    try:
        return json.loads(text_of(resp))
    except (ValueError, TypeError):
        return None
