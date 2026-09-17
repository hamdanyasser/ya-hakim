"""SQLite, one file, no ORM.

Everything a school needs to run this is a handful of tables. SQLite in WAL
mode handles a faculty's worth of concurrent learners on one small VM; the
schema is plain enough to move to Postgres when a customer needs it.

Encounter state and debrief reports are stored as JSON documents: they are
written once per action and read whole, which is exactly what a document
column is for.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = os.environ.get("YH_DB", str(Path(__file__).resolve().parent.parent / "data" / "yahakim.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS orgs (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, plan TEXT NOT NULL DEFAULT 'free',
  seats INTEGER NOT NULL DEFAULT 5, stripe_customer_id TEXT, stripe_subscription_id TEXT,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL REFERENCES orgs(id), email TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN ('learner','instructor','admin')),
  password_hash TEXT NOT NULL, created_at REAL NOT NULL, last_seen REAL
);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), created_at REAL NOT NULL,
  expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS invites (
  code TEXT PRIMARY KEY, org_id TEXT NOT NULL REFERENCES orgs(id), role TEXT NOT NULL,
  cohort_id TEXT, created_by TEXT NOT NULL, created_at REAL NOT NULL, uses INTEGER NOT NULL DEFAULT 0,
  max_uses INTEGER NOT NULL DEFAULT 500, expires_at REAL
);
CREATE TABLE IF NOT EXISTS cohorts (
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL REFERENCES orgs(id), name TEXT NOT NULL,
  created_by TEXT NOT NULL, created_at REAL NOT NULL, archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS cohort_members (
  cohort_id TEXT NOT NULL REFERENCES cohorts(id), user_id TEXT NOT NULL REFERENCES users(id),
  joined_at REAL NOT NULL, PRIMARY KEY (cohort_id, user_id)
);
CREATE TABLE IF NOT EXISTS cases (
  id TEXT PRIMARY KEY, org_id TEXT REFERENCES orgs(id), title TEXT NOT NULL, specialty TEXT,
  difficulty TEXT NOT NULL DEFAULT 'standard', data TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 0,
  builtin INTEGER NOT NULL DEFAULT 0, created_by TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS assignments (
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL REFERENCES orgs(id), cohort_id TEXT NOT NULL REFERENCES cohorts(id),
  case_id TEXT NOT NULL REFERENCES cases(id), title TEXT, due_at REAL, created_by TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS encounters (
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL REFERENCES orgs(id), user_id TEXT NOT NULL REFERENCES users(id),
  case_id TEXT NOT NULL REFERENCES cases(id), assignment_id TEXT REFERENCES assignments(id),
  state TEXT NOT NULL, report TEXT, score INTEGER, grade TEXT, status TEXT NOT NULL,
  started_at REAL NOT NULL, finished_at REAL, updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_encounters_user ON encounters(user_id, started_at);
CREATE INDEX IF NOT EXISTS idx_encounters_org ON encounters(org_id, started_at);
CREATE INDEX IF NOT EXISTS idx_encounters_assignment ON encounters(assignment_id);
CREATE INDEX IF NOT EXISTS idx_cases_org ON cases(org_id, published);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, org_id TEXT, user_id TEXT,
  action TEXT NOT NULL, detail TEXT
);
"""


def new_id(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(12)


def connect() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


@contextmanager
def tx():
    """One transaction. Commits on success, rolls back on any exception."""
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def init():
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (time.time(),))
    finally:
        conn.close()


def one(sql: str, params=()) -> dict | None:
    conn = connect()
    try:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def all_(sql: str, params=()) -> list:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def run(sql: str, params=()):
    conn = connect()
    try:
        conn.execute(sql, params)
    finally:
        conn.close()


def audit(action: str, org_id=None, user_id=None, detail=None):
    run("INSERT INTO audit(at, org_id, user_id, action, detail) VALUES (?,?,?,?,?)",
        (time.time(), org_id, user_id, action, json.dumps(detail) if detail is not None else None))


# ------------------------------------------------------------------ cases

def upsert_builtin_case(case: dict):
    now = time.time()
    with tx() as conn:
        row = conn.execute("SELECT id FROM cases WHERE id=?", (case["id"],)).fetchone()
        if row:
            conn.execute("UPDATE cases SET title=?, specialty=?, data=?, published=1, builtin=1, updated_at=? WHERE id=?",
                         (case.get("title") or case["name"], case.get("specialty"), json.dumps(case), now, case["id"]))
        else:
            conn.execute("INSERT INTO cases(id, org_id, title, specialty, difficulty, data, published, builtin, created_by, created_at, updated_at) "
                         "VALUES (?,NULL,?,?,?,?,1,1,NULL,?,?)",
                         (case["id"], case.get("title") or case["name"], case.get("specialty"),
                          case.get("difficulty", "standard"), json.dumps(case), now, now))


def case_row(case_id: str) -> dict | None:
    return one("SELECT * FROM cases WHERE id=?", (case_id,))


def load_case_data(case_id: str) -> dict | None:
    row = case_row(case_id)
    return json.loads(row["data"]) if row else None


def visible_cases(org_id: str, include_unpublished: bool = False) -> list:
    sql = "SELECT id, org_id, title, specialty, difficulty, published, builtin, created_by, created_at, updated_at " \
          "FROM cases WHERE (builtin=1 OR org_id=?)"
    if not include_unpublished:
        sql += " AND published=1"
    return all_(sql + " ORDER BY builtin DESC, title", (org_id,))


# ------------------------------------------------------------------- users

def _exec(conn, sql, params):
    if conn is not None:
        conn.execute(sql, params)
    else:
        run(sql, params)


def create_org(name: str, plan: str = "free", seats: int = 5, conn=None) -> dict:
    org = {"id": new_id("org_"), "name": name.strip()[:120] or "My school", "plan": plan,
           "seats": seats, "created_at": time.time()}
    _exec(conn, "INSERT INTO orgs(id, name, plan, seats, created_at) VALUES (?,?,?,?,?)",
          (org["id"], org["name"], plan, seats, org["created_at"]))
    return org


def create_user(org_id: str, email: str, name: str, role: str, password_hash: str, conn=None) -> dict:
    user = {"id": new_id("usr_"), "org_id": org_id, "email": email.strip().lower(),
            "name": name.strip()[:80] or email.split("@")[0], "role": role,
            "created_at": time.time()}
    _exec(conn, "INSERT INTO users(id, org_id, email, name, role, password_hash, created_at) VALUES (?,?,?,?,?,?,?)",
          (user["id"], org_id, user["email"], user["name"], role, password_hash, user["created_at"]))
    return user


def user_by_email(email: str) -> dict | None:
    return one("SELECT * FROM users WHERE email=?", (email.strip().lower(),))


def user_by_id(user_id: str) -> dict | None:
    return one("SELECT * FROM users WHERE id=?", (user_id,))


def org_member_count(org_id: str) -> int:
    row = one("SELECT COUNT(*) AS n FROM users WHERE org_id=?", (org_id,))
    return int(row["n"]) if row else 0


# ---------------------------------------------------------------- sessions

SESSION_DAYS = 30


def create_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    run("INSERT INTO sessions(token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
        (token, user_id, now, now + SESSION_DAYS * 86400))
    return token


def session_user(token: str) -> dict | None:
    if not token or len(token) > 128:
        return None
    row = one("SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token=? AND s.expires_at > ?",
              (token, time.time()))
    return row


def delete_session(token: str):
    run("DELETE FROM sessions WHERE token=?", (token,))


def purge_expired_sessions():
    run("DELETE FROM sessions WHERE expires_at <= ?", (time.time(),))


# -------------------------------------------------------------- encounters

def save_encounter(enc: dict):
    with tx() as conn:
        conn.execute(
            "INSERT INTO encounters(id, org_id, user_id, case_id, assignment_id, state, report, score, grade, status, started_at, finished_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state, report=excluded.report, "
            "score=excluded.score, grade=excluded.grade, status=excluded.status, finished_at=excluded.finished_at, updated_at=excluded.updated_at",
            (enc["id"], enc["org_id"], enc["user_id"], enc["case_id"], enc.get("assignment_id"),
             json.dumps(enc["state"]), json.dumps(enc["report"]) if enc.get("report") else None,
             enc.get("score"), enc.get("grade"), enc["status"], enc["started_at"], enc.get("finished_at"), time.time()))


def load_encounter(enc_id: str) -> dict | None:
    row = one("SELECT * FROM encounters WHERE id=?", (enc_id,))
    if not row:
        return None
    row["state"] = json.loads(row["state"])
    row["report"] = json.loads(row["report"]) if row["report"] else None
    return row
