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
#   YH_MODEL          debriefs and case drafting (and the patient, unless set below)
#   YH_PATIENT_MODEL  the patient's replies -- the most frequent call, so the one
#                     worth pointing at a fast, cheap model
# On a small budget set YH_MODEL=claude-haiku-4-5: about a fifth the cost, and
# for a patient who answers in two short sentences the difference barely shows.
MODEL = os.environ.get("YH_MODEL", "claude-opus-5")
PATIENT_MODEL = os.environ.get("YH_PATIENT_MODEL") or MODEL


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

# What has been spent this process. Not billing-accurate -- it is the number
# you need at 2am to answer "is something burning my credit", which the
# dashboard is too slow to tell you.
USAGE = {"calls": 0, "input": 0, "output": 0, "cache_read": 0}

# $ per million tokens, input/output. Only the models this app is run on.
PRICES = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5":  (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-5":    (5.0, 25.0),
}


def _record(model, resp):
    u = getattr(resp, "usage", None)
    if not u:
        return
    USAGE["calls"] += 1
    USAGE["input"] += getattr(u, "input_tokens", 0) or 0
    USAGE["output"] += getattr(u, "output_tokens", 0) or 0
    USAGE["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0


def usage_report(model=None) -> dict:
    model = model or MODEL
    inp, out = PRICES.get(model, (5.0, 25.0))
    cost = (USAGE["input"] / 1e6) * inp + (USAGE["output"] / 1e6) * out
    return {
        "model": model,
        "calls": USAGE["calls"],
        "input_tokens": USAGE["input"],
        "output_tokens": USAGE["output"],
        "cached_input_tokens": USAGE["cache_read"],
        "estimated_usd": round(cost, 4),
    }


def available() -> bool:
    """True when a live model can be used. The app is fully playable without."""
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def request_options(model: str, effort: str | None = None, fmt: dict | None = None) -> dict:
    """The per-model part of a request: only the options this model accepts.

    Every caller treats an API error as "use the offline path", so a rejected
    option would not crash anything -- it would quietly switch the live
    patient off. That is why this is decided here and nowhere else.
    """
    opts = {"model": model}
    config = {}
    if effort and _supports_effort(model):
        config["effort"] = effort
    if fmt:
        config["format"] = fmt
    if config:
        opts["output_config"] = config
    if _supports_fallbacks(model):
        opts["betas"] = [FALLBACK_BETA]
        opts["fallbacks"] = "default"
    return opts


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
        resp = api.beta.messages.create(
            betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
    else:
        resp = api.beta.messages.create(**kwargs)
    _record(model, resp)
    return resp


def text_of(response) -> str:
    return "".join(b.text for b in response.content if getattr(b, "type", None) == "text")


def json_call(system: str, user: str, schema: dict, *, effort: str = "high",
              max_tokens: int = 16000, timeout: float = 300.0) -> dict | None:
    """One structured-output call. Returns the parsed object, or None on any
    failure -- every caller has a deterministic path that does not need this.

    Streamed, because a debrief or a drafted case is long output and a
    non-streaming request that size can outlive an HTTP idle timeout. The
    schema must stick to what structured outputs support: no numeric or
    string-length constraints (callers clamp values themselves).
    """
    try:
        with client().with_options(timeout=timeout).beta.messages.stream(
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            **request_options(MODEL, effort, {"type": "json_schema", "schema": schema}),
        ) as stream:
            resp = stream.get_final_message()
    except anthropic.APIError:
        return None
    _record(MODEL, resp)
    if resp.stop_reason in ("refusal", "max_tokens"):
        return None
    try:
        return json.loads(text_of(resp))
    except (ValueError, TypeError):
        return None
