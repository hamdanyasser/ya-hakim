"""The v2 HTTP layer, driven through the real app. No key, no network.

Each class here guards a failure that existed:

* asking the patient anything at all was a 500 on any machine without a key,
  because the offline fallback was never reached;
* only Kamal could be cracked, because his cue -- the literal word "wife" --
  was hardcoded for every case;
* the picker cut descriptions mid-word;
* case generation with no key crashed instead of saying why.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp(prefix="yh-v2-test-")
os.environ.setdefault("YH_DB", str(Path(_TMP) / "test.db"))
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

from fastapi.testclient import TestClient  # noqa: E402

from engine import patient  # noqa: E402
from server import main as server_main  # noqa: E402
from v2.server import api as v2  # noqa: E402


@pytest.fixture(scope="module")
def app():
    with TestClient(server_main.app) as client:
        yield client


def _start(app, case="kamal"):
    r = app.post("/api/v2/start", json={"case": case})
    assert r.status_code == 200, r.text
    return r.json()


class TestThePicker:
    def test_it_lists_the_written_cases_with_a_tier_each(self, app):
        d = app.get("/api/v2/cases").json()
        ids = [c["id"] for c in d["cases"]]
        assert ids == v2.CASES
        assert len(ids) >= 9
        for c in d["cases"]:
            assert c["tier"] in (1, 2, 3)
            assert c["rank"] and c["xp"] > 0
            assert c["topics"] > 0
            assert isinstance(c["look"], dict)

    def test_generation_is_advertised_as_off_without_a_key(self, app):
        assert app.get("/api/v2/cases").json()["can_generate"] is False

    def test_no_card_leaks_the_answer(self, app):
        """The picker is drawn before the round. Nothing here may spell it."""
        for card in app.get("/api/v2/cases").json()["cases"]:
            blob = repr(card).lower()
            for secret in patient.SECRET_FIELDS:
                assert secret not in blob
            case = v2._case(card["id"])
            for answer in case["accepted_answers"]:
                assert answer.lower() not in blob

    def test_blurbs_are_cut_on_a_word(self, app):
        for card in app.get("/api/v2/cases").json()["cases"]:
            b = card["blurb"]
            assert len(b) <= 152
            # a hard slice used to leave "... His wif"
            assert not b.endswith(" ")
            if b.endswith("…"):
                assert b[-2] not in " ,;:"

    def test_a_blurb_shorter_than_the_limit_is_untouched(self):
        assert v2._blurb("short enough") == "short enough"
        assert v2._blurb("x" * 40, 150) == "x" * 40


class TestAskingHimThings:
    def test_asking_offline_is_never_a_500(self, app):
        """The bug: with no key the SDK raised TypeError while building the
        request, which is not an APIError, so nothing caught it."""
        s = _start(app)
        r = app.post("/api/v2/ask/" + s["session"], json={"text": "what brings you in?"})
        assert r.status_code == 200, r.text
        v = r.json()
        assert v["log"][-1]["kind"] == "him"
        assert v["log"][-1]["text"].strip()

    def test_the_canned_patient_still_never_names_it(self, app):
        s = _start(app)
        case = v2._case("kamal")
        for q in ("what is wrong with me?", "is it my liver?", "am I dying?"):
            v = app.post("/api/v2/ask/" + s["session"], json={"text": q}).json()
            said = " ".join(l["text"].lower() for l in v["log"])
            for answer in case["accepted_answers"]:
                assert answer.lower() not in said

    def test_an_empty_question_is_refused_not_crashed(self, app):
        s = _start(app)
        r = app.post("/api/v2/ask/" + s["session"], json={"text": "   "})
        assert r.status_code == 200
        assert r.json()["reason"] == "empty"

    def test_a_missing_session_is_a_404(self, app):
        assert app.post("/api/v2/ask/nope", json={"text": "hi"}).status_code == 404
        assert app.get("/api/v2/state/nope").status_code == 404


class TestEveryCaseIsPlayable:
    """Every shipped case must pass the same rules the editor enforces, or a
    player can reach a patient who leaks his own answer."""

    @pytest.mark.parametrize("case_id", v2.CASES)
    def test_it_validates(self, case_id):
        from engine import authoring

        assert authoring.validate(v2._case(case_id)) == []

    @pytest.mark.parametrize("case_id", v2.CASES)
    def test_it_has_a_tier_an_avatar_and_a_body(self, case_id):
        assert case_id in v2.TIERS
        assert case_id in v2.AVATARS
        look = v2._look(case_id, v2._case(case_id))
        assert look["model"] in v2.MODELS

    def test_the_cases_cover_every_body_model(self):
        """Five models with only three cases meant two were unreachable."""
        used = {v2._look(c, v2._case(c))["model"] for c in v2.CASES}
        assert used == set(v2.MODELS), sorted(used)

    def test_no_two_cases_share_a_diagnosis(self):
        seen = [v2._case(c)["diagnosis"].lower() for c in v2.CASES]
        assert len(set(seen)) == len(seen)


class TestCracking:
    """`cracks_when` is written into every case. v2 used to implement Kamal's
    and only Kamal's."""

    @pytest.mark.parametrize("case_id", ["kamal", "rita", "georges"])
    def test_every_case_has_its_own_cue_and_it_works(self, case_id):
        case = v2._case(case_id)
        cue = case["crack_keywords"][0]
        assert v2._cracks(case, "so, about your " + cue + ", tell me", None, {})

    @pytest.mark.parametrize("case_id", ["kamal", "rita", "georges"])
    def test_pressing_the_same_thread_twice_cracks_him(self, case_id):
        case = v2._case(case_id)
        topic = case["key_questions"][0]
        assert not v2._cracks(case, "an unrelated question", topic, {topic: 1})
        assert v2._cracks(case, "an unrelated question", topic, {topic: 2})

    def test_an_ordinary_question_does_not_crack_him(self):
        case = v2._case("kamal")
        assert not v2._cracks(case, "how are you feeling today?", None, {})

    def test_rita_is_not_cracked_by_kamals_cue(self):
        """The old hardcoded rule fired on the word "wife" for everybody."""
        assert not v2._cracks(v2._case("rita"), "what does your wife think?", None, {})


class TestFiveCalls:
    """A wrong call used to end the round, which made the whole encounter a
    coin flip on one sentence."""

    def test_a_wrong_call_does_not_end_the_round(self, app):
        s = _start(app)
        d = app.post("/api/v2/diagnose/" + s["session"],
                     json={"text": "a broken toe"}).json()
        assert d["resolved"] is False
        assert d["correct"] is False
        assert d["tries_left"] == v2.MAX_GUESSES - 1
        assert d["over"] is False
        assert "rows" not in d

    def test_the_miss_goes_into_the_thread(self, app):
        s = _start(app)
        d = app.post("/api/v2/diagnose/" + s["session"],
                     json={"text": "a broken toe"}).json()
        last = d["log"][-1]
        assert last["kind"] == "call"
        assert "broken toe" in last["text"]

    def test_the_fifth_wrong_call_ends_it(self, app):
        s = _start(app)
        sid = s["session"]
        for i in range(v2.MAX_GUESSES - 1):
            d = app.post("/api/v2/diagnose/" + sid, json={"text": "guess %d" % i}).json()
            assert d["resolved"] is False, i
        d = app.post("/api/v2/diagnose/" + sid, json={"text": "last guess"}).json()
        assert d["resolved"] is True
        assert d["reason"] == "out_of_tries"
        assert d["correct"] is False
        assert len(d["guesses"]) == v2.MAX_GUESSES

    def test_a_right_call_ends_it_immediately(self, app):
        s = _start(app)
        case = v2._case("kamal")
        d = app.post("/api/v2/diagnose/" + s["session"],
                     json={"text": case["accepted_answers"][0]}).json()
        assert d["resolved"] is True and d["correct"] is True

    def test_calling_it_later_is_worth_fewer_marks(self, app):
        """Getting there on the fifth try must not pay the same as the first."""
        case = v2._case("kamal")
        answer = case["accepted_answers"][0]

        first = _start(app)
        d1 = app.post("/api/v2/diagnose/" + first["session"], json={"text": answer}).json()

        late = _start(app)
        for i in range(3):
            app.post("/api/v2/diagnose/" + late["session"], json={"text": "wrong %d" % i})
        d2 = app.post("/api/v2/diagnose/" + late["session"], json={"text": answer}).json()

        assert d2["correct"] is True
        row1 = [r for r in d1["rows"] if r["label"] == "Called it right"][0]
        row2 = [r for r in d2["rows"] if r["label"] == "Called it right"][0]
        assert row2["got"] < row1["got"]

    def test_giving_up_ends_it_and_reveals(self, app):
        s = _start(app)
        d = app.post("/api/v2/diagnose/" + s["session"],
                     json={"text": "", "final": True}).json()
        assert d["resolved"] is True
        assert d["reason"] == "gave_up"
        assert d["diagnosis"] == v2._case("kamal")["diagnosis"]

    def test_a_resolved_round_stays_resolved(self, app):
        s = _start(app)
        sid = s["session"]
        app.post("/api/v2/diagnose/" + sid, json={"text": "", "final": True})
        again = app.post("/api/v2/diagnose/" + sid, json={"text": "anything"}).json()
        assert again["resolved"] is True
        assert again["reason"] == "already"


class TestTheMarkSheet:
    def test_a_right_call_scores_and_reports_its_working(self, app):
        s = _start(app)
        case = v2._case("kamal")
        r = app.post("/api/v2/diagnose/" + s["session"],
                     json={"text": case["accepted_answers"][0]})
        assert r.status_code == 200
        d = r.json()
        assert d["correct"] is True
        assert d["accuracy"] == sum(row["got"] for row in d["rows"])
        assert 0 < d["accuracy"] <= 100
        assert sum(row["of"] for row in d["rows"]) == 100
        assert d["xp"] > 0
        assert d["stats"]["topics_total"] == len(case["key_questions"])

    def test_no_call_at_all_is_scored_not_rejected(self, app):
        """The clock running out posts an empty diagnosis."""
        s = _start(app)
        d = app.post("/api/v2/diagnose/" + s["session"], json={"text": ""}).json()
        assert d["resolved"] is True
        assert d["correct"] is False
        assert d["accuracy"] == sum(row["got"] for row in d["rows"])

    def test_the_round_is_four_minutes(self, app):
        s = _start(app)
        assert v2.ROUND_SECONDS == 240
        assert 235 <= s["seconds_left"] <= 240

    def test_examining_him_moves_the_mark_sheet(self, app):
        s = _start(app)
        sid = s["session"]
        app.post("/api/v2/examine/" + sid, json={"exam": "hands"})
        app.post("/api/v2/examine/" + sid, json={"exam": "eyes"})
        d = app.post("/api/v2/diagnose/" + sid, json={"text": "", "final": True}).json()
        assert d["stats"]["examined"] == 2
        exam_row = [r for r in d["rows"] if r["label"] == "Examined him"][0]
        assert exam_row["got"] > 0


class TestExamining:
    def test_the_same_examination_cannot_be_done_twice(self, app):
        s = _start(app)
        sid = s["session"]
        assert app.post("/api/v2/examine/" + sid, json={"exam": "hands"}).json().get("reason") is None
        assert app.post("/api/v2/examine/" + sid, json={"exam": "hands"}).json()["reason"] == "already"

    def test_an_invented_examination_is_refused(self, app):
        s = _start(app)
        r = app.post("/api/v2/examine/" + s["session"], json={"exam": "vibes"})
        assert r.status_code == 200
        assert r.json()["reason"] == "unknown"

    def test_every_room_hotspot_is_a_real_examination(self, app):
        """The 3D room offers six of these by touch; all six must exist."""
        ids = {e["id"] for e in app.get("/api/v2/exams").json()["exams"]}
        for spot in ("eyes", "cognition", "hands", "respiratory", "abdominal", "legs"):
            assert spot in ids


class TestGeneration:
    def test_it_says_why_rather_than_crashing_without_a_key(self, app):
        r = app.post("/api/v2/generate", json={"brief": "anything"})
        assert r.status_code == 503
        body = r.json()
        assert body["error"] == "no_key"
        assert "ANTHROPIC_API_KEY" in body["message"]

    def test_an_unknown_job_is_a_404(self, app):
        assert app.get("/api/v2/generate/nope").status_code == 404


class TestTheView:
    def test_progress_counts_are_sent_but_never_the_topics(self, app):
        s = _start(app)
        case = v2._case("kamal")
        assert s["topics_total"] == len(case["key_questions"])
        assert s["topics_covered"] == 0
        blob = repr(s).lower()
        for kq in case["key_questions"]:
            assert kq.lower() not in blob

    def test_an_unknown_case_falls_back_rather_than_500ing(self, app):
        s = _start(app, case="../../etc/passwd")
        assert s["name"] == v2._case("kamal")["name"]

    def test_the_proof_still_has_the_answer_nowhere_in_it(self, app):
        s = _start(app)
        d = app.get("/api/v2/proof/" + s["session"]).json()
        assert d["chars"] > 0
        for term in d["terms"]:
            assert term["hits"] == 0, term["term"] + " is in the prompt"


class TestTheDebrief:
    """The teaching half of the case, shown only once the round has closed.

    Every field in it names or implies the answer, so the whole value of the
    feature depends on it arriving late. These guard that.
    """

    def test_it_is_absent_from_every_payload_of_a_live_round(self, app):
        s = _start(app, case="georges")
        sid = s["session"]
        assert "debrief" not in s

        assert "debrief" not in app.get("/api/v2/state/" + sid).json()
        assert "debrief" not in app.post("/api/v2/ask/" + sid,
                                         json={"text": "what heats the house"}).json()
        assert "debrief" not in app.post("/api/v2/examine/" + sid,
                                         json={"exam": "general"}).json()

        # a wrong call does not end the round, so it must not teach either
        wrong = app.post("/api/v2/diagnose/" + sid, json={"text": "a migraine"}).json()
        assert wrong["resolved"] is False
        assert "debrief" not in wrong

    def test_a_live_round_never_serves_the_teaching_text(self, app):
        """Not just the key: none of the words, by any route a player has."""
        s = _start(app, case="georges")
        sid = s["session"]
        case = v2._case("georges")
        pearls = " ".join(case["teaching"]["pearls"]).lower()

        blob = (repr(app.get("/api/v2/state/" + sid).json())
                + repr(app.post("/api/v2/ask/" + sid,
                                json={"text": "when do the headaches come"}).json())).lower()
        for sentence in pearls.split(". "):
            head = sentence.strip()[:40]
            if head:
                assert head not in blob

    def test_it_arrives_when_the_round_resolves(self, app):
        s = _start(app, case="georges")
        d = app.post("/api/v2/diagnose/" + s["session"],
                     json={"text": "carbon monoxide"}).json()
        assert d["resolved"] is True and d["correct"] is True

        db = d["debrief"]
        case = v2._case("georges")
        assert db["summary"] == case["teaching"]["summary"]
        assert db["pearls"] == case["teaching"]["pearls"]
        assert db["management"] == case["management_points"]
        assert db["guidelines"] == case["guidelines"]

        # the traps are the point: a plausible, well-meant, harmful decision
        assert db["traps"], "georges has harmful_treatments and they must show"
        assert any("oximeter" in t["why"].lower() for t in db["traps"])

        # every key question paired with the reason it mattered
        assert len(db["threads"]) == len(case["key_questions"])
        for t in db["threads"]:
            assert t["question"] and t["why"]

    def test_giving_up_still_teaches(self, app):
        """The player who walks away is the one who most needs the debrief."""
        s = _start(app, case="hana")
        d = app.post("/api/v2/diagnose/" + s["session"], json={"final": True}).json()
        assert d["resolved"] is True and d["correct"] is False
        assert d["debrief"]["summary"]
        assert d["debrief"]["pearls"]

    def test_every_case_has_something_to_teach(self, app):
        thin = []
        for cid in v2.CASES:
            s = _start(app, case=cid)
            d = app.post("/api/v2/diagnose/" + s["session"], json={"final": True}).json()
            db = d["debrief"]
            if not (db["summary"] and db["pearls"] and db["threads"] and db["management"]):
                thin.append(cid)
        assert not thin, "these cases have no debrief worth showing: " + repr(thin)
