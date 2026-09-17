"""Sign up, sign in, invites."""

from __future__ import annotations

import os
import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from engine import llm
from server import auth, billing, db

router = APIRouter(prefix="/api")


def _org(org_id: str) -> dict:
    org = db.one("SELECT * FROM orgs WHERE id=?", (org_id,))
    if not org:
        raise HTTPException(404, "Organisation not found.")
    return org


def _login_response(user: dict) -> JSONResponse:
    token = db.create_session(user["id"])
    org = _org(user["org_id"])
    resp = JSONResponse({"user": auth.public_user(user), "org": _public_org(org)})
    auth.set_session_cookie(resp, token)
    db.run("UPDATE users SET last_seen=? WHERE id=?", (time.time(), user["id"]))
    return resp


def _public_org(org: dict) -> dict:
    return {"id": org["id"], "name": org["name"], "plan": org["plan"], "seats": org["seats"]}


@router.post("/auth/signup")
async def signup(payload: dict):
    """A new school. The first user is its admin."""
    email = (payload.get("email") or "").strip().lower()
    auth.check_email(email)
    auth.check_password_strength(payload.get("password"))
    if db.user_by_email(email):
        raise HTTPException(409, "That email already has an account. Sign in instead.")
    org = db.create_org(payload.get("org_name") or (payload.get("name") or "My") + "'s school")
    user = db.create_user(org["id"], email, payload.get("name") or "", "admin",
                          auth.hash_password(payload["password"]))
    db.audit("signup", org_id=org["id"], user_id=user["id"])
    return _login_response(user)


@router.post("/auth/join")
async def join(payload: dict):
    """Join an existing school with an invite code."""
    code = (payload.get("code") or "").strip().upper()
    invite = db.one("SELECT * FROM invites WHERE code=?", (code,))
    if not invite or invite["uses"] >= invite["max_uses"] or \
            (invite["expires_at"] and invite["expires_at"] < time.time()):
        raise HTTPException(400, "That invite code is not valid any more.")
    email = (payload.get("email") or "").strip().lower()
    auth.check_email(email)
    auth.check_password_strength(payload.get("password"))
    if db.user_by_email(email):
        raise HTTPException(409, "That email already has an account. Sign in instead.")
    org = _org(invite["org_id"])
    if not billing.seats_available(org):
        raise HTTPException(402, "This school has used all its seats. Ask your administrator to add more.")
    user = db.create_user(org["id"], email, payload.get("name") or "", invite["role"],
                          auth.hash_password(payload["password"]))
    with db.tx() as conn:
        conn.execute("UPDATE invites SET uses=uses+1 WHERE code=?", (code,))
        if invite["cohort_id"]:
            conn.execute("INSERT OR IGNORE INTO cohort_members(cohort_id, user_id, joined_at) VALUES (?,?,?)",
                         (invite["cohort_id"], user["id"], time.time()))
    db.audit("join", org_id=org["id"], user_id=user["id"], detail={"invite": code})
    return _login_response(user)


@router.post("/auth/login")
async def login(payload: dict):
    user = db.user_by_email(payload.get("email") or "")
    if not user or not auth.verify_password(payload.get("password") or "", user["password_hash"]):
        raise HTTPException(401, "Email or password is wrong.")
    return _login_response(user)


@router.post("/auth/logout")
async def logout(request: Request):
    token = request.cookies.get(auth.COOKIE)
    if token:
        db.delete_session(token)
    resp = JSONResponse({"ok": True})
    auth.clear_session_cookie(resp)
    return resp


@router.get("/me")
async def me(request: Request):
    user = auth.current_user(request)
    if not user:
        return {"user": None}
    org = _org(user["org_id"])
    return {"user": auth.public_user(user), "org": _public_org(org),
            "plan": billing.plan_info(org), "live": llm.available(),
            "features": {"authoring": llm.available(), "billing": billing.configured()}}


@router.post("/auth/invite-preview")
async def invite_preview(payload: dict):
    code = (payload.get("code") or "").strip().upper()
    invite = db.one("SELECT i.role, o.name FROM invites i JOIN orgs o ON o.id=i.org_id WHERE i.code=?", (code,))
    if not invite:
        raise HTTPException(404, "Unknown invite code.")
    return {"org_name": invite["name"], "role": invite["role"]}


def make_invite(org_id: str, role: str, cohort_id: str | None, created_by: str) -> dict:
    code = "".join(secrets.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(6))
    db.run("INSERT INTO invites(code, org_id, role, cohort_id, created_by, created_at, max_uses) VALUES (?,?,?,?,?,?,?)",
           (code, org_id, role, cohort_id, created_by, time.time(), 500))
    app_url = os.environ.get("APP_URL", "").rstrip("/")
    return {"code": code, "url": (app_url + "/app/join?code=" + code) if app_url else "/app/join?code=" + code}
