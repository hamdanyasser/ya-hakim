"""Instructors and administrators: cohorts, assignments, the dashboard, the
case editor, members and billing."""

from __future__ import annotations

import json
import time
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Request

from engine import authoring, llm
from server import api_auth, auth, billing, db

router = APIRouter(prefix="/api")

STAFF = ("instructor", "admin")


def _org_of(user: dict) -> dict:
    return api_auth._org(user["org_id"])


# ------------------------------------------------------------------ org

@router.get("/org")
async def org_info(request: Request):
    user = auth.require_role(request, *STAFF)
    org = _org_of(user)
    counts = db.one("SELECT SUM(role='learner') AS learners, SUM(role='instructor') AS instructors, "
                    "SUM(role='admin') AS admins FROM users WHERE org_id=?", (org["id"],)) or {}
    return {"org": {"id": org["id"], "name": org["name"], "plan": org["plan"], "seats": org["seats"]},
            "counts": {k: int(counts.get(k) or 0) for k in ("learners", "instructors", "admins")},
            "plan": billing.plan_info(org)}


@router.post("/org/name")
async def rename(request: Request, payload: dict):
    user = auth.require_role(request, "admin")
    name = (payload.get("name") or "").strip()[:120]
    if not name:
        raise HTTPException(400, "Give the school a name.")
    db.run("UPDATE orgs SET name=? WHERE id=?", (name, user["org_id"]))
    return {"ok": True}


@router.get("/org/members")
async def members(request: Request):
    user = auth.require_role(request, *STAFF)
    rows = db.all_("SELECT id, email, name, role, created_at, last_seen FROM users WHERE org_id=? ORDER BY role, name",
                   (user["org_id"],))
    cohorts = defaultdict(list)
    for r in db.all_("SELECT cm.user_id, c.name FROM cohort_members cm JOIN cohorts c ON c.id=cm.cohort_id "
                     "WHERE c.org_id=?", (user["org_id"],)):
        cohorts[r["user_id"]].append(r["name"])
    for r in rows:
        r["cohorts"] = cohorts.get(r["id"], [])
    return {"members": rows}


@router.post("/org/members/{user_id}/role")
async def set_role(request: Request, user_id: str, payload: dict):
    admin = auth.require_role(request, "admin")
    role = payload.get("role")
    if role not in ("learner", "instructor", "admin"):
        raise HTTPException(400, "Unknown role.")
    target = db.user_by_id(user_id)
    if not target or target["org_id"] != admin["org_id"]:
        raise HTTPException(404, "Member not found.")
    if target["id"] == admin["id"] and role != "admin":
        raise HTTPException(400, "You cannot remove your own admin role.")
    db.run("UPDATE users SET role=? WHERE id=?", (role, user_id))
    db.audit("member.role", org_id=admin["org_id"], user_id=admin["id"], detail={"target": user_id, "role": role})
    return {"ok": True}


@router.post("/org/invites")
async def invite(request: Request, payload: dict):
    user = auth.require_role(request, *STAFF)
    role = payload.get("role") or "learner"
    if role not in ("learner", "instructor", "admin"):
        raise HTTPException(400, "Unknown role.")
    if role != "learner" and user["role"] != "admin":
        raise HTTPException(403, "Only an admin can invite staff.")
    cohort_id = payload.get("cohort_id") or None
    if cohort_id and not db.one("SELECT id FROM cohorts WHERE id=? AND org_id=?", (cohort_id, user["org_id"])):
        raise HTTPException(404, "Cohort not found.")
    return api_auth.make_invite(user["org_id"], role, cohort_id, user["id"])


@router.get("/org/invites")
async def invites(request: Request):
    user = auth.require_role(request, *STAFF)
    rows = db.all_("SELECT i.code, i.role, i.uses, i.max_uses, i.created_at, c.name AS cohort FROM invites i "
                   "LEFT JOIN cohorts c ON c.id=i.cohort_id WHERE i.org_id=? ORDER BY i.created_at DESC LIMIT 50",
                   (user["org_id"],))
    return {"invites": rows}


# -------------------------------------------------------------- cohorts

@router.get("/org/cohorts")
async def cohorts(request: Request):
    user = auth.require_role(request, *STAFF)
    rows = db.all_(
        "SELECT c.id, c.name, c.created_at, c.archived, COUNT(cm.user_id) AS members FROM cohorts c "
        "LEFT JOIN cohort_members cm ON cm.cohort_id=c.id WHERE c.org_id=? GROUP BY c.id ORDER BY c.archived, c.name",
        (user["org_id"],))
    return {"cohorts": rows}


@router.post("/org/cohorts")
async def create_cohort(request: Request, payload: dict):
    user = auth.require_role(request, *STAFF)
    name = (payload.get("name") or "").strip()[:80]
    if not name:
        raise HTTPException(400, "Give the cohort a name, e.g. 'Year 4, 2026'.")
    cid = db.new_id("coh_")
    db.run("INSERT INTO cohorts(id, org_id, name, created_by, created_at) VALUES (?,?,?,?,?)",
           (cid, user["org_id"], name, user["id"], time.time()))
    inv = api_auth.make_invite(user["org_id"], "learner", cid, user["id"])
    return {"id": cid, "name": name, "invite": inv}


@router.post("/org/cohorts/{cohort_id}/members")
async def add_member(request: Request, cohort_id: str, payload: dict):
    user = auth.require_role(request, *STAFF)
    if not db.one("SELECT id FROM cohorts WHERE id=? AND org_id=?", (cohort_id, user["org_id"])):
        raise HTTPException(404, "Cohort not found.")
    target = db.user_by_id(payload.get("user_id") or "")
    if not target or target["org_id"] != user["org_id"]:
        raise HTTPException(404, "Member not found.")
    db.run("INSERT OR IGNORE INTO cohort_members(cohort_id, user_id, joined_at) VALUES (?,?,?)",
           (cohort_id, target["id"], time.time()))
    return {"ok": True}


@router.get("/org/cohorts/{cohort_id}")
async def cohort_detail(request: Request, cohort_id: str):
    user = auth.require_role(request, *STAFF)
    cohort = db.one("SELECT * FROM cohorts WHERE id=? AND org_id=?", (cohort_id, user["org_id"]))
    if not cohort:
        raise HTTPException(404, "Cohort not found.")
    learners = db.all_("SELECT u.id, u.name, u.email, u.last_seen FROM cohort_members cm JOIN users u ON u.id=cm.user_id "
                       "WHERE cm.cohort_id=? ORDER BY u.name", (cohort_id,))
    assignments = db.all_("SELECT a.*, c.title AS case_title FROM assignments a JOIN cases c ON c.id=a.case_id "
                          "WHERE a.cohort_id=? ORDER BY a.created_at DESC", (cohort_id,))
    ids = [l["id"] for l in learners]
    encs = []
    if ids:
        q = ",".join("?" * len(ids))
        encs = db.all_("SELECT id, user_id, case_id, assignment_id, score, grade, status, started_at, finished_at "
                       "FROM encounters WHERE user_id IN (%s) ORDER BY started_at DESC" % q, ids)
    by_user = defaultdict(list)
    for e in encs:
        by_user[e["user_id"]].append(e)
    for l in learners:
        mine = by_user.get(l["id"], [])
        done = [e for e in mine if e["status"] == "complete" and e["score"] is not None]
        l["attempts"] = len(mine)
        l["completed"] = len(done)
        l["average"] = round(sum(e["score"] for e in done) / len(done)) if done else None
        l["last"] = mine[0] if mine else None
    for a in assignments:
        rel = [e for e in encs if e["assignment_id"] == a["id"]]
        did = {e["user_id"] for e in rel if e["status"] == "complete"}
        scores = [e["score"] for e in rel if e["score"] is not None]
        a["completed"] = len(did)
        a["of"] = len(learners)
        a["average"] = round(sum(scores) / len(scores)) if scores else None
    return {"cohort": cohort, "learners": learners, "assignments": assignments}


@router.post("/org/cohorts/{cohort_id}/assignments")
async def assign(request: Request, cohort_id: str, payload: dict):
    user = auth.require_role(request, *STAFF)
    if not db.one("SELECT id FROM cohorts WHERE id=? AND org_id=?", (cohort_id, user["org_id"])):
        raise HTTPException(404, "Cohort not found.")
    case = db.case_row(payload.get("case_id") or "")
    if not case or (case["org_id"] and case["org_id"] != user["org_id"]) or not case["published"]:
        raise HTTPException(400, "Choose a published case.")
    aid = db.new_id("asg_")
    due = payload.get("due_at")
    db.run("INSERT INTO assignments(id, org_id, cohort_id, case_id, title, due_at, created_by, created_at) VALUES (?,?,?,?,?,?,?,?)",
           (aid, user["org_id"], cohort_id, case["id"], (payload.get("title") or case["title"])[:120],
            float(due) if due else None, user["id"], time.time()))
    return {"id": aid}


@router.get("/my/assignments")
async def my_assignments(request: Request):
    user = auth.require_user(request)
    rows = db.all_(
        "SELECT a.id, a.title, a.due_at, a.case_id, c.title AS case_title, c.specialty, co.name AS cohort "
        "FROM assignments a JOIN cohort_members cm ON cm.cohort_id=a.cohort_id AND cm.user_id=? "
        "JOIN cases c ON c.id=a.case_id JOIN cohorts co ON co.id=a.cohort_id ORDER BY a.due_at IS NULL, a.due_at",
        (user["id"],))
    done = {r["assignment_id"]: r for r in db.all_(
        "SELECT assignment_id, MAX(score) AS score, COUNT(*) AS attempts FROM encounters "
        "WHERE user_id=? AND assignment_id IS NOT NULL AND status='complete' GROUP BY assignment_id", (user["id"],))}
    for r in rows:
        d = done.get(r["id"])
        r["best_score"] = d["score"] if d else None
        r["attempts"] = d["attempts"] if d else 0
    return {"assignments": rows}


# ------------------------------------------------------------ dashboard

@router.get("/org/dashboard")
async def dashboard(request: Request):
    user = auth.require_role(request, *STAFF)
    org_id = user["org_id"]
    encs = db.all_("SELECT e.id, e.user_id, e.case_id, e.score, e.grade, e.status, e.started_at, e.finished_at, e.report, "
                   "u.name AS learner, c.title AS case_title FROM encounters e JOIN users u ON u.id=e.user_id "
                   "JOIN cases c ON c.id=e.case_id WHERE e.org_id=? ORDER BY e.started_at DESC LIMIT 2000", (org_id,))
    done = [e for e in encs if e["status"] == "complete" and e["score"] is not None]
    domains = defaultdict(lambda: [0, 0])
    missed = defaultdict(int)
    harm = defaultdict(int)
    dx = {"correct": 0, "partial": 0, "wrong": 0}
    outcomes = defaultdict(int)
    for e in done:
        rep = json.loads(e["report"]) if e["report"] else None
        if not rep:
            continue
        for d in rep.get("domains", []):
            domains[d["name"]][0] += d["score"]
            domains[d["name"]][1] += d["max"]
            for item in d.get("items", []):
                if not item.get("met"):
                    missed[item["label"]] += 1
                if item.get("harm"):
                    harm[item["label"]] += 1
        dd = rep.get("diagnosis") or {}
        dx["correct" if dd.get("correct") else "partial" if dd.get("partial") else "wrong"] += 1
        outcomes[rep.get("outcome") or "unknown"] += 1
    by_case = defaultdict(list)
    for e in done:
        by_case[e["case_title"]].append(e["score"])
    by_learner = defaultdict(list)
    for e in done:
        by_learner[e["learner"]].append(e["score"])
    week = time.time() - 7 * 86400
    return {
        "totals": {"encounters": len(encs), "completed": len(done),
                   "active_learners_7d": len({e["user_id"] for e in encs if e["started_at"] > week}),
                   "average": round(sum(e["score"] for e in done) / len(done)) if done else None},
        "domains": [{"name": k, "pct": round(100 * v[0] / v[1]) if v[1] else 0} for k, v in domains.items()],
        "diagnosis": dx,
        "outcomes": dict(outcomes),
        "most_missed": sorted(({"label": k, "count": v} for k, v in missed.items()), key=lambda x: -x["count"])[:10],
        "harm": sorted(({"label": k, "count": v} for k, v in harm.items()), key=lambda x: -x["count"])[:5],
        "by_case": sorted(({"case": k, "average": round(sum(v) / len(v)), "attempts": len(v)}
                           for k, v in by_case.items()), key=lambda x: x["average"]),
        "by_learner": sorted(({"learner": k, "average": round(sum(v) / len(v)), "attempts": len(v)}
                              for k, v in by_learner.items()), key=lambda x: x["average"]),
        "recent": [{k: e[k] for k in ("id", "learner", "case_title", "score", "grade", "status", "started_at")}
                   for e in encs[:25]],
    }


# ------------------------------------------------------------ case editor

def _own_case(user: dict, case_id: str) -> dict:
    row = db.case_row(case_id)
    if not row or (row["org_id"] and row["org_id"] != user["org_id"]):
        raise HTTPException(404, "Case not found.")
    return row


@router.get("/org/cases/{case_id}")
async def get_case(request: Request, case_id: str):
    user = auth.require_role(request, *STAFF)
    row = _own_case(user, case_id)
    data = json.loads(row["data"])
    return {"case": data, "published": bool(row["published"]), "builtin": bool(row["builtin"]),
            "problems": authoring.validate(data)}


@router.post("/org/cases")
async def create_case(request: Request, payload: dict):
    user = auth.require_role(request, *STAFF)
    data = payload.get("case")
    if not isinstance(data, dict):
        raise HTTPException(400, "Send the case as JSON.")
    cid = "c_" + authoring.slug(data.get("title") or data.get("name") or "case") + "_" + db.new_id()[:6].lower()
    data["id"] = cid
    problems = authoring.validate(data)
    now = time.time()
    db.run("INSERT INTO cases(id, org_id, title, specialty, difficulty, data, published, builtin, created_by, created_at, updated_at) "
           "VALUES (?,?,?,?,?,?,0,0,?,?,?)",
           (cid, user["org_id"], data.get("title") or data.get("name") or "Untitled", data.get("specialty"),
            data.get("difficulty", "standard"), json.dumps(data), user["id"], now, now))
    db.audit("case.create", org_id=user["org_id"], user_id=user["id"], detail={"case": cid})
    return {"id": cid, "problems": problems}


@router.put("/org/cases/{case_id}")
async def update_case(request: Request, case_id: str, payload: dict):
    user = auth.require_role(request, *STAFF)
    row = _own_case(user, case_id)
    if row["builtin"]:
        raise HTTPException(400, "Built-in cases are read-only. Duplicate it to edit.")
    data = payload.get("case")
    if not isinstance(data, dict):
        raise HTTPException(400, "Send the case as JSON.")
    data["id"] = case_id
    problems = authoring.validate(data)
    published = bool(row["published"]) and not problems
    db.run("UPDATE cases SET title=?, specialty=?, difficulty=?, data=?, published=?, updated_at=? WHERE id=?",
           (data.get("title") or data.get("name") or "Untitled", data.get("specialty"),
            data.get("difficulty", "standard"), json.dumps(data), int(published), time.time(), case_id))
    return {"id": case_id, "problems": problems, "published": published}


@router.post("/org/cases/{case_id}/duplicate")
async def duplicate_case(request: Request, case_id: str):
    user = auth.require_role(request, *STAFF)
    row = _own_case(user, case_id)
    data = json.loads(row["data"])
    data["title"] = (data.get("title") or row["title"]) + " (copy)"
    return await create_case(request, {"case": data})


@router.post("/org/cases/{case_id}/publish")
async def publish_case(request: Request, case_id: str, payload: dict):
    user = auth.require_role(request, *STAFF)
    row = _own_case(user, case_id)
    if row["builtin"]:
        raise HTTPException(400, "Built-in cases are always published.")
    want = bool(payload.get("published", True))
    problems = authoring.validate(json.loads(row["data"])) if want else []
    if problems:
        raise HTTPException(400, "Fix these before publishing: " + "; ".join(problems[:5]))
    db.run("UPDATE cases SET published=?, updated_at=? WHERE id=?", (int(want), time.time(), case_id))
    return {"published": want}


@router.delete("/org/cases/{case_id}")
async def delete_case(request: Request, case_id: str):
    user = auth.require_role(request, "admin")
    row = _own_case(user, case_id)
    if row["builtin"]:
        raise HTTPException(400, "Built-in cases cannot be deleted.")
    used = db.one("SELECT COUNT(*) AS n FROM encounters WHERE case_id=?", (case_id,))
    if used and used["n"]:
        db.run("UPDATE cases SET published=0, updated_at=? WHERE id=?", (time.time(), case_id))
        return {"deleted": False, "unpublished": True,
                "reason": "Learners have attempted this case, so it was unpublished instead of deleted."}
    db.run("DELETE FROM assignments WHERE case_id=?", (case_id,))
    db.run("DELETE FROM cases WHERE id=?", (case_id,))
    return {"deleted": True}


@router.post("/org/cases/draft")
async def draft_case(request: Request, payload: dict):
    user = auth.require_role(request, *STAFF)
    if not llm.available():
        raise HTTPException(400, "Case drafting needs an Anthropic API key on the server.")
    case = authoring.draft(payload.get("brief") or "", payload.get("specialty") or "",
                           payload.get("difficulty") or "standard", payload.get("language") or "English")
    if not case:
        raise HTTPException(502, "The model did not return a usable draft. Try again with a clearer brief.")
    db.audit("case.draft", org_id=user["org_id"], user_id=user["id"])
    return {"case": case, "problems": authoring.validate(case)}


@router.get("/org/case-template")
async def case_template(request: Request):
    auth.require_role(request, *STAFF)
    return {"case": db.load_case_data("kamal")}


# --------------------------------------------------------------- billing

@router.get("/billing")
async def billing_info(request: Request):
    user = auth.require_role(request, "admin")
    return billing.plan_info(_org_of(user))


@router.post("/billing/checkout")
async def checkout(request: Request, payload: dict):
    user = auth.require_role(request, "admin")
    return {"url": billing.checkout_url(_org_of(user), user, payload.get("seats") or 25)}


@router.post("/billing/portal")
async def portal(request: Request):
    user = auth.require_role(request, "admin")
    return {"url": billing.portal_url(_org_of(user))}


@router.post("/billing/webhook")
async def webhook(request: Request):
    payload = await request.body()
    return billing.handle_webhook(payload, request.headers.get("stripe-signature", ""))
