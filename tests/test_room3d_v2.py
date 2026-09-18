"""The v2 room and its monitor must build on the three.js revision we ship.

Same reasoning as test_room3d.py, for the newer scene: a geometry or a 2D
canvas method that exists in a modern browser but not in r128 throws at
construction and takes the whole page down with it. That failure is invisible
to every other test here because it only happens in a browser.

v2 draws far more of itself in code than v1 did -- painted textures, a monitor
face with three live traces, limbs placed by their endpoints -- so the builder
exercises the monitor as well as the scene.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BUILDER = ROOT / "tests" / "web" / "build_room_v2.js"

node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node is not installed")


def _run():
    return subprocess.run([node, str(BUILDER)], capture_output=True, text=True,
                          cwd=str(ROOT), timeout=60)


def test_the_v2_room_builds_on_r128():
    r = _run()
    assert r.returncode == 0, "v2 room3d.js failed on r128:\n" + r.stdout + r.stderr
    assert "Room3D built OK on r128" in r.stdout


def test_the_monitor_draws_and_fires_beats():
    """The beep is driven off the R peak of the trace it draws. A monitor that
    renders but never fires is a silent bedside."""
    r = _run()
    assert "Monitor built OK" in r.stdout, r.stdout
    assert "Monitor survives flatline" in r.stdout, r.stdout


def test_the_patient_is_actually_in_the_scene():
    """A room with no person in it is the bug this was written after."""
    r = _run()
    assert "patient present: true" in r.stdout, r.stdout


def test_every_hotspot_maps_to_a_real_examination():
    """A hotspot pointing at an examination the engine does not have is a
    click that silently does nothing."""
    from engine import clinical

    r = _run()
    line = [l for l in r.stdout.splitlines() if "hotspots:" in l]
    assert line, r.stdout
    ids = [i.strip() for i in line[0].split("->")[1].split(",")]
    assert ids
    for exam_id in ids:
        assert exam_id in clinical.EXAM_BY_ID, exam_id + " is not a real examination"


def test_the_scene_survives_frames_and_a_new_patient():
    r = _run()
    assert "frame/setStatus/setPatientLook/resize/freeze all survive" in r.stdout, r.stdout


def test_all_five_patient_models_apply():
    """One man in three hair colours is not three patients."""
    r = _run()
    assert "all 5 patient models applied" in r.stdout, r.stdout


def test_the_server_offers_exactly_those_five_models():
    from v2.server import api as v2

    assert len(v2.MODELS) == 5
    seen = set()
    for sex in ("male", "female"):
        for age in (22, 35, 50, 62, 81):
            seen.add(v2._model_for(sex, age))
    assert seen == set(v2.MODELS), seen
    for name, m in v2.MODELS.items():
        assert 0.85 <= m["build"] <= 1.15, name
        assert 0.90 <= m["frame"] <= 1.10, name
