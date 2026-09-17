"""Requests are shaped for the model they go to.

Sending a parameter a model does not support is a 400, and every caller treats
an API error as "use the offline path" -- so a wrong option would not crash
anything, it would quietly turn the live patient off. These tests record the
request instead of sending it.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from engine import llm, patient

CASES_DIR = Path(__file__).resolve().parent.parent / "cases"


class _Recorder:
    def __init__(self):
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def with_options(self, **_):
        return self

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text="Two glasses, like anyone.")])


def _kamal():
    with open(CASES_DIR / "kamal.json", encoding="utf-8") as fh:
        return json.load(fh)


def test_haiku_gets_no_effort_and_no_fallbacks(monkeypatch):
    monkeypatch.setattr(llm, "PATIENT_MODEL", "claude-haiku-4-5")
    rec = _Recorder()
    reply = patient.ask(_kamal(), [], "how much do you drink?", client=rec)
    assert reply == "Two glasses, like anyone."
    sent = rec.calls[0]
    assert sent["model"] == "claude-haiku-4-5"
    assert "output_config" not in sent, "Haiku 4.5 rejects effort"
    assert "fallbacks" not in sent and "betas" not in sent


def test_opus_keeps_effort_and_refusal_fallbacks(monkeypatch):
    monkeypatch.setattr(llm, "PATIENT_MODEL", "claude-opus-5")
    rec = _Recorder()
    patient.ask(_kamal(), [], "how much do you drink?", client=rec)
    sent = rec.calls[0]
    assert sent["output_config"] == {"effort": "low"}
    assert sent["fallbacks"] == "default" and sent["betas"] == [llm.FALLBACK_BETA]


def test_structured_output_keeps_its_format_on_every_model():
    fmt = {"type": "json_schema", "schema": {"type": "object"}}
    for model in ("claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"):
        opts = llm.request_options(model, "high", fmt)
        assert opts["output_config"]["format"] == fmt
        assert ("effort" in opts["output_config"]) == (model != "claude-haiku-4-5")
