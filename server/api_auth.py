"""Sign up, sign in, invites.

Plain `def` endpoints: scrypt is deliberately slow and must not run on the
event loop. Sign-in and account creation are rate limited per client address
(and sign-in also per email), which is what makes password guessing
impractical.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from engine import llm
from server import auth, billing, db, guard

router = APIRouter(prefix="/api")

# A whole cohort usually shares one campus address, so per-address limits are
# sized for a lecture hall signing in at once. The per-account limit is the one
# that actually stops password guessing.
_login_ip = guard.RateLimit(600, 300)       # attempts per address per 5 minutes
_login_email = guard.RateLimit(10, 300)     # attempts per account per 5 minutes
_signup_ip = guard.RateLimit(10, 3600)      # new schools per address per hour
_join_ip = guard.RateLimit(400, 3600)       # invite redemptions per address per hour
_invite_peek = guard.RateLimit(600, 300)    # invite code lookups per address


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


def _credentials(payload: dict) -> tuple:
    email = guard.text(payload, "email", 254).lower()
    password = payload.get("password") if isinstance(payload, dict) else None
    if not isinstance(password, str):
        password = ""
    auth.check_email(email)
    auth.check_password_strength(password)
    if len(password) > 1024:
        raise HTTPException(400, "That password is too long.")
    return email, password


@router.post("/auth/signup")
def signup(request: Request, payload: dict):
    """A new school. The first user is its admin."""
    _signup_ip.check(guard.client_ip(request), "Too many new schools from this network.")
    email, password = _credentials(payload)
    name = guard.text(payload, "name", 80)
    org_name = guard.text(payload, "org_name", 120) or ((name or "My") + "'s school")
    if db.user_by_email(email):
        raise HTTPException(409, "That email already has an account. Sign in instead.")
    password_hash = auth.hash_password(password)
    try:
        with db.tx() as conn:
            org = db.create_org(org_name, conn=conn)
            user = db.create_user(org["id"], email, name, "admin", password_hash, conn=conn)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "That email already has an account. Sign in instead.")
    db.audit("signup", org_id=org["id"], user_id=user["id"])
    return _login_response(user)


@router.post("/auth/join")
def join(request: Request, payload: dict):
    """Join an existing school with an invite code.

    The invite's use count, the school's seat count and the new user are
    checked and written in one transaction, so two people redeeming the last
    seat at the same moment cannot both get in.
    """
    _join_ip.check(guard.client_ip(request), "Too many new accounts from this network.")
    code = guard.text(payload, "code", 12).upper()
    email, password = _credentials(payload)
    name = guard.text(payload, "name", 80)
    password_hash = auth.hash_password(password)
    try:
        with db.tx() as conn:
            invite = conn.execute("SELECT * FROM invites WHERE code=?", (code,)).fetchone()
            if not invite or invite["uses"] >= invite["max_uses"] or \
                    (invite["expires_at"] and invite["expires_at"] < time.time()):
                raise HTTPException(400, "That invite code is not valid any more.")
            if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
                raise HTTPException(409, "That email already has an account. Sign in instead.")
            org = conn.execute("SELECT * FROM orgs WHERE id=?", (invite["org_id"],)).fetchone()
            members = conn.execute("SELECT COUNT(*) FROM users WHERE org_id=?", (org["id"],)).fetchone()[0]
            if members >= org["seats"]:
                raise HTTPException(402, "This school has used all its seats. Ask your administrator to add more.")
            user = db.create_user(org["id"], email, name, invite["role"], password_hash, conn=conn)
            conn.execute("UPDATE invites SET uses=uses+1 WHERE code=?", (code,))
            if invite["cohort_id"]:
                conn.execute("INSERT OR IGNORE INTO cohort_members(cohort_id, user_id, joined_at) VALUES (?,?,?)",
                             (invite["cohort_id"], user["id"], time.time()))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "That email already has an account. Sign in instead.")
    db.audit("join", org_id=user["org_id"], user_id=user["id"], detail={"invite": code})
    return _login_response(user)


@router.post("/auth/login")
def login(request: Request, payload: dict):
    email = guard.text(payload, "email", 254).lower()
    password = payload.get("password") if isinstance(payload, dict) else None
    _login_ip.check(guard.client_ip(request), "Too many sign-in attempts.")
    _login_email.check(email, "Too many sign-in attempts for this account.")
    user = db.user_by_email(email) if email else None
    if not isinstance(password, str) or len(password) > 1024:
        password = ""
    # Hash even when the account does not exist, so response time does not
    # reveal which emails are registered.
    stored = user["password_hash"] if user else auth.DUMMY_HASH
    ok = auth.verify_password(password, stored)
    if not user or not ok:
        raise HTTPException(401, "Email or password is wrong.")
    return _login_response(user)


@router.post("/auth/logout")
def logout(request: Request):
    token = request.cookies.get(auth.COOKIE)
    if token:
        db.delete_session(token)
    resp = JSONResponse({"ok": True})
    auth.clear_session_cookie(resp)
    return resp


@router.get("/me")
def me(request: Request):
    user = auth.current_user(request)
    if not user:
        return {"user": None}
    org = _org(user["org_id"])
    return {"user": auth.public_user(user), "org": _public_org(org),
            "plan": billing.plan_info(org), "live": llm.available(),
            "features": {"authoring": llm.available(), "billing": billing.configured()}}


@router.post("/auth/invite-preview")
def invite_preview(request: Request, payload: dict):
    _invite_peek.check(guard.client_ip(request))
    code = guard.text(payload, "code", 12).upper()
    invite = db.one("SELECT i.role, i.uses, i.max_uses, i.expires_at, o.name FROM invites i "
                    "JOIN orgs o ON o.id=i.org_id WHERE i.code=?", (code,))
    if not invite or invite["uses"] >= invite["max_uses"] or \
            (invite["expires_at"] and invite["expires_at"] < time.time()):
        raise HTTPException(404, "Unknown invite code.")
    return {"org_name": invite["name"], "role": invite["role"]}


def make_invite(org_id: str, role: str, cohort_id: str | None, created_by: str) -> dict:
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    for _ in range(10):
        code = "".join(secrets.choice(alphabet) for _ in range(6))
        try:
            db.run("INSERT INTO invites(code, org_id, role, cohort_id, created_by, created_at, max_uses) "
                   "VALUES (?,?,?,?,?,?,?)", (code, org_id, role, cohort_id, created_by, time.time(), 500))
            break
        except sqlite3.IntegrityError:
            continue
    else:
        raise HTTPException(500, "Could not create an invite code. Try again.")
    app_url = os.environ.get("APP_URL", "").rstrip("/")
    return {"code": code, "url": (app_url + "/app/join?code=" + code) if app_url else "/app/join?code=" + code}
