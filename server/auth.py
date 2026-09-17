"""Passwords and sessions, standard library only.

scrypt from hashlib for password hashing (memory-hard, no extra dependency);
opaque random session tokens stored server-side, so a session can be revoked
by deleting a row. The cookie is HttpOnly + SameSite=Lax; every mutating API
takes JSON, which a cross-site form cannot send, so that is the CSRF story
for v1.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets

from fastapi import HTTPException, Request

from server import db

COOKIE = "yh_session"
# Secure cookies are only sent over HTTPS. Forcing them on a plain-HTTP
# deployment means sign-in "works" and then never sticks, so the default
# follows the public URL; YH_SECURE_COOKIES=1/0 overrides it.
_secure_env = os.environ.get("YH_SECURE_COOKIES")
SECURE_COOKIES = (_secure_env == "1") if _secure_env in ("0", "1") else     os.environ.get("APP_URL", "").lower().startswith("https://")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$" + salt.hex() + "$" + digest.hex()


def verify_password(password: str, stored: str) -> bool:
    if not isinstance(password, str) or not isinstance(stored, str):
        return False
    try:
        _, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                                n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


# Verified against when an email is unknown, so a failed sign-in costs the same
# time whether or not the account exists.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def check_password_strength(password: str):
    if len(password or "") < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")


def check_email(email: str):
    if not EMAIL_RE.match(email or ""):
        raise HTTPException(400, "Enter a valid email address.")


def current_user(request: Request) -> dict | None:
    return db.session_user(request.cookies.get(COOKIE, ""))


def require_user(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise HTTPException(401, "Sign in to continue.")
    return user


def require_role(request: Request, *roles: str) -> dict:
    user = require_user(request)
    if user["role"] not in roles:
        raise HTTPException(403, "You do not have access to that.")
    return user


def set_session_cookie(response, token: str):
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=SECURE_COOKIES,
                        max_age=db.SESSION_DAYS * 86400, path="/")


def clear_session_cookie(response):
    response.delete_cookie(COOKIE, path="/")


def public_user(user: dict) -> dict:
    return {"id": user["id"], "email": user["email"], "name": user["name"],
            "role": user["role"], "org_id": user["org_id"]}
