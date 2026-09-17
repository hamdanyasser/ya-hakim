"""The 3D room must build on the three.js revision we actually ship.

A geometry that exists in modern three.js but not in r128 throws at construction
and takes the whole page down with it -- screen.js never reaches connect(), no
state arrives, and every number on the projector sits at a dash. That failure is
invisible to every other test here because it only happens in a browser.

So the room is built head to toe against a stub with exactly r128's API surface.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BUILDER = ROOT / "tests" / "web" / "build_room.js"

node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node is not installed")


def _run():
    return subprocess.run([node, str(BUILDER)], capture_output=True, text=True,
                          cwd=str(ROOT), timeout=60)


def test_the_room_builds_on_r128():
    r = _run()
    assert r.returncode == 0, "room3d.js failed on r128:\n" + r.stdout + r.stderr
    assert "Room3D built OK" in r.stdout


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


def test_the_scene_survives_a_frame_and_a_status_change():
    r = _run()
    assert "frame/setStatus/freeze all survive" in r.stdout, r.stdout
