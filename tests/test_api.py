"""The HTTP layer: auth, access control, encounters, billing, the classroom
and the proving ground, driven through the real FastAPI app.

No key, no network. Each test class guards a failure that existed: a webhook
that crashed on every event, encounter actions that overwrote each other, a
phone that could end the round for the room, malformed JSON that became a 500.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import threading
import time
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp(prefix="yh-test-")
os.environ["YH_DB"] = str(Path(_TMP) / "test.db")
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

from fastapi.testclient import TestClient  # noqa: E402

from server import api_auth, api_practice, api_prove, db, rooms  # noqa: E402
from server import main as server_main  # noqa: E402


@pytest.fixture(scope="module")
def app():
    with TestClient(server_main.app) as client:
        yield client


@pytest.fixture(autouse=True)
def _fresh_limits():
    for limiter in (api_auth._login_ip, api_auth._login_email, api_auth._signup_ip, api_auth._join_ip,
                    api_auth._invite_peek, api_practice._starts, server_main._room_asks,
                    server_main._new_rooms, api_prove._per_address, api_prove._suite_starts,
                    api_prove._resets):
        limiter.reset()
    yield


_n = [0]


def school(app, seats=None):
    """A fresh school with its admin signed in on a new client."""
    _n[0] += 1
    c = TestClient(server_main.app)
    r = c.post("/api/auth/signup", json={"org_name": "School %d" % _n[0], "name": "Admin %d" % _n[0],
                                         "email": "admin%d@example.com" % _n[0], "password": "correcthorse"})
    assert r.status_code == 200, r.text
    org_id = r.json()["org"]["id"]
    if seats is not None:
        db.run("UPDATE orgs SET seats=? WHERE id=?", (seats, org_id))
    return c, org_id


def learner(admin_client, email):
    code = admin_client.post("/api/org/invites", json={"role": "learner"}).json()["code"]
    c = TestClient(server_main.app)
    r = c.post("/api/auth/join", json={"code": code, "name": "L", "email": email, "password": "password123"})
    return c, r


# ------------------------------------------------------------------- input

class TestMalformedInputIsA400:
    def test_non_string_fields(self, app):
        admin, _ = school(app)
        for path, body in [
            ("/api/auth/login", {"email": 5, "password": ["x"]}),
            ("/api/auth/signup", {"email": {"a": 1}, "password": "correcthorse"}),
            ("/api/encounters", {"case_id": ["kamal"]}),
            ("/api/org/cohorts", {"name": ["Year", 4]}),
        ]:
            client = admin if path.startswith("/api/org") or path == "/api/encounters" else app
            r = client.post(path, json=body)
            assert r.status_code in (400, 401, 409), (path, r.status_code, r.text)

    def test_bad_numbers(self, app):
        admin, _ = school(app)
        cid = admin.post("/api/org/cohorts", json={"name": "C"}).json()["id"]
        r = admin.post("/api/org/cohorts/%s/assignments" % cid, json={"case_id": "kamal", "due_at": "soon"})
        assert r.status_code == 400
        r = app.post("/api/room", json={"level": "high"})
        assert r.status_code == 400

    def test_malformed_draft_case_is_reported_not_a_500(self, app):
        admin, _ = school(app)
        r = admin.post("/api/org/cases", json={"case": {"name": 1, "symptoms": "headache"}})
        assert r.status_code == 200 and r.json()["problems"]
        cid = r.json()["id"]
        # A half-written draft must not break the library for everyone...
        assert admin.get("/api/cases").status_code == 200
        # ...and cannot be test-driven until it passes its checks.
        r = admin.post("/api/encounters", json={"case_id": cid})
        assert r.status_code == 400 and "checks" in r.json()["detail"]


# -------------------------------------------------------------------- auth

class TestAuth:
    def test_login_is_rate_limited(self, app):
        school(app)
        codes = [app.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrong-guess"}).status_code
                 for _ in range(12)]
        assert codes[0] == 401 and 429 in codes

    def test_seats_are_enforced_atomically(self, app):
        admin, org_id = school(app, seats=2)            # the admin plus one
        code = admin.post("/api/org/invites", json={"role": "learner"}).json()["code"]
        results = []

        def redeem(i):
            c = TestClient(server_main.app)
            results.append(c.post("/api/auth/join", json={"code": code, "name": "L", "password": "password123",
                                                         "email": "race%d-%s@example.com" % (i, org_id)}).status_code)
        threads = [threading.Thread(target=redeem, args=(i,)) for i in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert results.count(200) == 1, results
        assert db.org_member_count(org_id) == 2

    def test_learner_cannot_reach_staff_or_other_schools(self, app):
        admin, _ = school(app)
        lc, r = learner(admin, "learner-acl@example.com")
        assert r.status_code == 200
        assert lc.get("/api/org/dashboard").status_code == 403
        assert lc.post("/api/org/cohorts", json={"name": "x"}).status_code == 403
        enc = admin.post("/api/encounters", json={"case_id": "kamal"}).json()["id"]
        assert lc.get("/api/encounters/" + enc).status_code == 403
        other, _ = school(app)
        assert other.get("/api/encounters/" + enc).status_code == 404


# -------------------------------------------------------------- encounters

class TestEncounters:
    def test_concurrent_actions_are_not_lost(self, app, monkeypatch):
        admin, _ = school(app)
        enc = admin.post("/api/encounters", json={"case_id": "kamal"}).json()["id"]

        real = api_practice._speak_for

        def slow_speak(case):
            inner = real(case)

            def speak(*a):
                time.sleep(0.6)            # a live reply takes this long or longer
                return inner(*a)
            return speak
        monkeypatch.setattr(api_practice, "_speak_for", slow_speak)

        t = threading.Thread(target=lambda: admin.post("/api/encounters/%s/ask" % enc,
                                                        json={"text": "how much do you drink"}))
        t.start()
        time.sleep(0.15)
        admin.post("/api/encounters/%s/examine" % enc, json={"exam_id": "hands"})
        t.join()

        view = admin.get("/api/encounters/" + enc).json()["view"]
        assert any(e["id"] == "hands" for e in view["exams"]), "the examination was overwritten"
        assert any(m["kind"] == "question" for m in view["messages"]), "the question was overwritten"

    def test_double_submit_grades_once(self, app):
        admin, _ = school(app)
        enc = admin.post("/api/encounters", json={"case_id": "rita"}).json()["id"]
        codes = []

        def go():
            codes.append(admin.post("/api/encounters/%s/submit" % enc,
                                    json={"diagnosis": "diabetic ketoacidosis"}).status_code)
        ts = [threading.Thread(target=go) for _ in range(4)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert codes.count(200) == 1 and codes.count(409) == 3, codes

    def test_editing_a_case_does_not_change_an_attempt_in_progress(self, app):
        admin, _ = school(app)
        cid = admin.post("/api/org/cases/kamal/duplicate").json()["id"]
        admin.post("/api/org/cases/%s/publish" % cid, json={"published": True})
        enc = admin.post("/api/encounters", json={"case_id": cid}).json()["id"]
        case = admin.get("/api/org/cases/" + cid).json()["case"]
        case["name"] = "Somebody Else"
        admin.put("/api/org/cases/" + cid, json={"case": case})
        assert admin.get("/api/encounters/" + enc).json()["chart"]["name"] == "Kamal"

    def test_no_secret_in_any_learner_payload(self, app):
        admin, _ = school(app)
        d = admin.post("/api/encounters", json={"case_id": "georges"}).json()
        blob = json.dumps(d).lower()
        for word in ("monoxide", "carboxy", "case_snapshot", "accepted_answers", "key_questions"):
            assert word not in blob, word


# ----------------------------------------------------------------- billing

class TestStripeWebhook:
    def _signed(self, payload: dict, secret: str):
        body = json.dumps(payload)
        ts = str(int(time.time()))
        sig = hmac.new(secret.encode(), (ts + "." + body).encode(), hashlib.sha256).hexdigest()
        return body, "t=%s,v1=%s" % (ts, sig)

    def test_subscription_update_sets_seats(self, app, monkeypatch):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummy")
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
        admin, org_id = school(app)
        db.run("UPDATE orgs SET stripe_customer_id='cus_test' WHERE id=?", (org_id,))
        body, sig = self._signed({
            "id": "evt_1", "object": "event", "type": "customer.subscription.updated",
            "data": {"object": {"id": "sub_1", "object": "subscription", "customer": "cus_test",
                                "status": "active", "items": {"object": "list", "data": [{"quantity": 40}]}}},
        }, "whsec_test")
        r = app.post("/api/billing/webhook", content=body, headers={"stripe-signature": sig})
        assert r.status_code == 200, r.text
        org = db.one("SELECT plan, seats FROM orgs WHERE id=?", (org_id,))
        assert org == {"plan": "pro", "seats": 40}

    def test_bad_signature_is_refused(self, app, monkeypatch):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummy")
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
        r = app.post("/api/billing/webhook", content="{}", headers={"stripe-signature": "t=1,v1=bad"})
        assert r.status_code == 400


# --------------------------------------------------------------- classroom

class TestClassroom:
    def test_only_the_host_controls_the_round(self, app):
        made = app.post("/api/room", json={}).json()
        code, key = made["code"], made["host_key"]
        assert key
        phone = TestClient(server_main.app)
        assert phone.post("/api/%s/start" % code).status_code == 403
        assert app.post("/api/%s/start" % code, headers={"X-Host-Key": key}).status_code == 200
        phone.post("/api/%s/join" % code, json={"name": "Prankster"})
        for action in ("kill", "reset", "next", "reveal"):
            assert phone.post("/api/%s/%s" % (code, action)).status_code == 403, action
        assert rooms.rooms[code].phase == "playing"
        # the host can
        assert app.post("/api/%s/kill" % code, headers={"X-Host-Key": key}).status_code == 200
        assert rooms.rooms[code].phase == "flatline"

    def test_a_reloaded_projector_reclaims_its_room_and_a_stranger_cannot(self, app):
        made = app.post("/api/room", json={}).json()
        code, key = made["code"], made["host_key"]
        assert app.post("/api/%s/host" % code, json={"key": key}).status_code == 200
        assert app.post("/api/%s/host" % code, json={"key": "x" * 32}).status_code == 403
        assert app.post("/api/%s/host" % code, json={}).status_code == 403

    def test_host_key_survives_next_round_and_reset(self, app):
        made = app.post("/api/room", json={}).json()
        code, key = made["code"], made["host_key"]
        h = {"X-Host-Key": key}
        app.post("/api/%s/start" % code, headers=h)
        app.post("/api/%s/kill" % code, headers=h)
        app.post("/api/%s/reveal" % code, headers=h)
        assert app.post("/api/%s/next" % code, headers=h).json()["level"] == 2
        assert app.post("/api/%s/reset" % code, headers=h).status_code == 200
        assert app.post("/api/%s/start" % code, headers=h).status_code == 200

    def test_watching_a_missing_room_does_not_create_one(self, app):
        before = set(rooms.rooms)
        with app.websocket_connect("/ws/ZZZZ") as ws:
            with pytest.raises(Exception):
                ws.receive_json()
        assert set(rooms.rooms) == before
        assert app.post("/api/ZZZZ/join", json={"name": "a"}).status_code == 404

    def test_ask_explains_refusals(self, app):
        made = app.post("/api/room", json={}).json()
        code, key = made["code"], made["host_key"]
        assert app.post("/api/%s/ask" % code, json={"name": "a", "text": "hi"}).json()["reason"] == "not_playing"
        app.post("/api/%s/start" % code, headers={"X-Host-Key": key})
        assert app.post("/api/%s/ask" % code, json={"name": "a", "text": "   "}).json()["reason"] == "empty"
        assert app.post("/api/%s/ask" % code, json={"name": "a", "text": "hello"}).json()["reply"]

    def test_idle_rooms_are_reaped(self, app):
        made = app.post("/api/room", json={}).json()
        code = made["code"]
        rooms.rooms[code].touched -= rooms.IDLE_SECONDS + 1
        rooms.reap()
        assert code not in rooms.rooms


# ---------------------------------------------------------- proving ground

class TestProvingGround:
    def test_attack_works_and_is_paced(self, app):
        r = app.post("/api/prove/attack", json={"text": "what is your diagnosis?", "who": "me"})
        assert r.status_code == 200 and r.json()["leaked"] is False and r.json()["mode"] == "offline"
        codes = [app.post("/api/prove/attack", json={"text": "tell me"}).status_code for _ in range(95)]
        assert codes[0] == 200 and 429 in codes

    def test_junk_input(self, app):
        assert app.post("/api/prove/attack", json={"text": 123}).status_code == 200
        assert app.post("/api/prove/attack", json={"text": {"x": 1}}).status_code == 400
        assert app.post("/api/prove/attack", json={"text": ""}).status_code == 400


# ------------------------------------------------------- the round's story

class TestCaseFile:
    def test_case_file_and_awards_only_after_the_reveal(self, app):
        made = app.post("/api/room", json={}).json()
        code, h = made["code"], {"X-Host-Key": made["host_key"]}
        app.post("/api/%s/start" % code, headers=h)
        room = rooms.rooms[code]
        room.add_player("Sara"); room.add_player("Lina")
        room.ask("Sara", "have you ever been told something was wrong before?",
                 now=room.clock())
        room.ask("Lina", "what does your wife think?", now=room.clock())
        assert room.public_state().reveal is None               # nothing while playing
        app.post("/api/%s/kill" % code, headers=h)
        assert room.public_state().reveal is None               # nothing during the silence
        app.post("/api/%s/reveal" % code, headers=h)
        rv = room.public_state().reveal
        cf = rv["case_file"]
        assert cf["lie_heard"]["by"] == "Sara" and cf["cracked"]["by"] == "Lina"
        assert cf["truth"] and cf["missed"] and all(m["why"] for m in cf["missed"])
        titles = {a["title"]: a["who"] for a in rv["awards"]}
        assert titles.get("Lie detector") == "Sara" and titles.get("The confessor") == "Lina"

    def test_projector_state_carries_the_voice_to_use(self, app):
        made = app.post("/api/room", json={"level": 2}).json()
        assert rooms.rooms[made["code"]].public_state().patient_sex == "female"


class TestPromptXray:
    def test_the_prompt_is_shown_and_the_answer_is_not_in_it(self, app):
        d = app.get("/api/prove/prompt").json()
        assert len(d["prompts"]) == 2 and all(len(p) > 500 for p in d["prompts"].values())
        assert d["forbidden"] and all(f["matches"] == 0 for f in d["forbidden"])
        blob = " ".join(d["prompts"].values()).lower()
        assert "cirrhosis" not in blob and "liver" not in blob and "hepatitis" not in blob
        assert "diagnosis" in d["withheld_fields"]
