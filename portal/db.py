"""SQLite storage.

students      profile + parsed resume
opportunities internships (campus postings, faculty posts, synced job boards)
matches       one row per student x opportunity: relevance, have/missing skills, eligibility
records       the "one tracked record": created when a student starts an application,
              carried through offer, NOC, internship, report and final grade
approvals / audit / memory are append-only (never UPDATEd or DELETEd)."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from .config import DATA_DIR, DB_PATH, DOCS_DIR, RESUME_DIR

_lock = threading.RLock()
_JSON_COLS = {"skills", "required_skills", "eligible_branches", "match", "eligibility",
              "application", "submission", "offer", "noc", "milestones", "progress_health",
              "scores", "detail", "co_mapping", "panel", "final_report", "spec", "flags",
              "resume_profile", "have", "missing", "tools", "data", "links", "session"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, name TEXT, role TEXT, email TEXT UNIQUE, title TEXT,
  password_hash TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS students (
  id TEXT PRIMARY KEY, user_id TEXT, usn TEXT, name TEXT, email TEXT, phone TEXT,
  department TEXT, semester INTEGER, cgpa REAL, active_backlogs INTEGER, attendance_pct REAL,
  preferred_domains TEXT, preferred_locations TEXT, open_to_remote INTEGER DEFAULT 1,
  links TEXT, resume_filename TEXT, resume_text TEXT, resume_profile TEXT, skills TEXT,
  agent_status TEXT DEFAULT 'idle', agent_message TEXT DEFAULT '', matched_at TEXT,
  faculty_id TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS opportunities (
  id TEXT PRIMARY KEY, title TEXT, company TEXT, location TEXT, mode TEXT,
  duration_weeks INTEGER, stipend TEXT, deadline TEXT, description TEXT,
  required_skills TEXT, min_cgpa REAL, max_active_backlogs INTEGER,
  eligible_branches TEXT, min_semester INTEGER, source TEXT, url TEXT,
  posted_by TEXT, retrieved_at TEXT, flags TEXT DEFAULT '[]', status TEXT DEFAULT 'open');
CREATE TABLE IF NOT EXISTS matches (
  id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT, opportunity_id TEXT,
  score REAL, skills_fit REAL, role_fit REAL, pref_fit REAL, have TEXT, missing TEXT,
  why TEXT, improve TEXT, highlight TEXT, eligibility TEXT, panel TEXT, mode TEXT,
  computed_at TEXT, notified INTEGER DEFAULT 0, UNIQUE(student_id, opportunity_id));
CREATE TABLE IF NOT EXISTS records (
  id TEXT PRIMARY KEY, student_id TEXT, opportunity_id TEXT, stage TEXT,
  match TEXT, eligibility TEXT, application TEXT, submission TEXT, offer TEXT, noc TEXT,
  mentor_id TEXT, milestones TEXT, progress_health TEXT, final_report TEXT,
  created_at TEXT, updated_at TEXT, UNIQUE(student_id, opportunity_id));
CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, record_id TEXT, gate TEXT,
  decision TEXT, actor_id TEXT, actor_name TEXT, actor_role TEXT,
  agent_recommendation TEXT, remarks TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS progress_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, record_id TEXT, week INTEGER,
  hours REAL, tasks TEXT, learnings TEXT, artifacts TEXT, submitted_at TEXT,
  mentor_verified INTEGER DEFAULT 0, mentor_remarks TEXT DEFAULT '', co_mapping TEXT);
CREATE TABLE IF NOT EXISTS evaluations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, record_id TEXT, version INTEGER,
  scores TEXT, total REAL, grade TEXT, justification TEXT, status TEXT,
  mentor_score REAL, created_at TEXT);
CREATE TABLE IF NOT EXISTS memory (
  id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT, kind TEXT, content TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS chat_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT, role TEXT, content TEXT,
  tools TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, text TEXT, link TEXT,
  read INTEGER DEFAULT 0, ts TEXT);
CREATE TABLE IF NOT EXISTS research (company TEXT PRIMARY KEY, data TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, run_id TEXT, kind TEXT,
  actor TEXT, action TEXT, record_id TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT, rule_key TEXT, name TEXT,
  scope TEXT, field TEXT, op TEXT, value REAL, posting_field TEXT,
  active INTEGER, version INTEGER, created_by TEXT, created_at TEXT, spec TEXT);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, goal TEXT, channel TEXT, actor TEXT, student_id TEXT, record_id TEXT,
  status TEXT, started_at TEXT, finished_at TEXT, ms INTEGER, session TEXT);
CREATE INDEX IF NOT EXISTS audit_run ON audit(run_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DATA_DIR.mkdir(exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
    return _conn


def _decode(row) -> dict | None:
    if row is None:
        return None
    out = dict(row)
    for k, v in out.items():
        if k in _JSON_COLS and isinstance(v, str) and v:
            try:
                out[k] = json.loads(v)
            except json.JSONDecodeError:
                pass
    return out


def _encode(v):
    return json.dumps(v, default=str) if isinstance(v, (dict, list)) else v


def query(sql: str, params: tuple = ()) -> list[dict]:
    with _lock:
        return [_decode(r) for r in conn().execute(sql, params).fetchall()]


def one(sql: str, params: tuple = ()) -> dict | None:
    with _lock:
        return _decode(conn().execute(sql, params).fetchone())


def execute(sql: str, params: tuple = ()) -> int:
    with _lock:
        cur = conn().execute(sql, tuple(_encode(p) for p in params))
        conn().commit()
        return cur.lastrowid


def insert(table: str, data: dict) -> int:
    cols = ", ".join(data)
    marks = ", ".join("?" for _ in data)
    return execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(data.values()))


def update(table: str, key, data: dict, key_col: str = "id") -> None:
    if table in ("approvals", "audit", "memory"):
        raise PermissionError(f"{table} is append-only")
    sets = ", ".join(f"{k} = ?" for k in data)
    execute(f"UPDATE {table} SET {sets} WHERE {key_col} = ?", (*data.values(), key))


def get_meta(key: str) -> str | None:
    r = one("SELECT value FROM meta WHERE key = ?", (key,))
    return r["value"] if r else None


def set_meta(key: str, value: str) -> None:
    execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
            (key, value, value))


# ---------------------------------------------------------------- passwords

def hash_password(pw: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120_000).hex()
    return f"{salt}${digest}"


def check_password(pw: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
    except (ValueError, AttributeError):
        return False
    return secrets.compare_digest(hash_password(pw, salt), stored)


# ---------------------------------------------------------------- seed data

SEED_DIR = Path(__file__).with_name("seed")

# (id, name, role, email, title, password)
USERS = [
    ("u-fac-1", "Prof. S. Deshpande", "faculty", "coordinator@college.edu",
     "Department Internship Coordinator", "faculty123"),
    ("u-men-1", "Arjun Mehta", "mentor", "arjun.mehta@industry.com",
     "Industry Mentor, Software", "mentor123"),
    ("u-adm-1", "Portal Admin", "admin", "admin@college.edu", "System Administrator", "admin123"),
    ("u-stu-1", "Ananya Rao", "student", "ananya@college.edu", "Student", "student123"),
]

STUDENTS = [
    {"id": "s-1", "user_id": "u-stu-1", "usn": "2CS23CS001", "name": "Ananya Rao",
     "email": "ananya@college.edu", "department": "CSE", "semester": 6, "cgpa": 8.6,
     "active_backlogs": 0, "attendance_pct": 88.0, "preferred_domains": "AI/ML, Web development",
     "preferred_locations": "Bengaluru, Pune", "open_to_remote": 1, "resume_file": "ananya_rao.txt"},
]

BASE_RULES = [
    ("attendance", "Minimum attendance (college policy)", "institution", "attendance_pct", ">=", 75, None),
    ("min_sem_policy", "Semester 5 or above (college policy)", "institution", "semester", ">=", 5, None),
    ("cgpa", "Minimum CGPA (employer)", "posting", "cgpa", ">=", None, "min_cgpa"),
    ("backlogs", "Max active backlogs (employer)", "posting", "active_backlogs", "<=", None,
     "max_active_backlogs"),
    ("semester", "Minimum semester (employer)", "posting", "semester", ">=", None, "min_semester"),
    ("branch", "Eligible branch (employer)", "posting", "department", "in", None, "eligible_branches"),
]


def _seed_docs() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    for p in (SEED_DIR / "docs").glob("*"):
        target = DOCS_DIR / p.name
        if not target.exists():
            target.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")


def seed_postings() -> list[dict]:
    return json.loads((SEED_DIR / "campus_postings.json").read_text(encoding="utf-8"))


def init_db(reset: bool = False) -> None:
    global _conn
    DATA_DIR.mkdir(exist_ok=True)
    RESUME_DIR.mkdir(parents=True, exist_ok=True)
    if reset:
        with _lock:
            if _conn is not None:
                _conn.close()
                _conn = None
            if DB_PATH.exists():
                os.remove(DB_PATH)
    with _lock:
        conn().executescript(SCHEMA)
        conn().commit()
    _seed_docs()
    if one("SELECT COUNT(*) AS n FROM users")["n"]:
        return
    for uid, name, role, email, title, pw in USERS:
        insert("users", {"id": uid, "name": name, "role": role, "email": email, "title": title,
                         "password_hash": hash_password(pw), "created_at": now()})
    for s in STUDENTS:
        s = dict(s)
        resume = (SEED_DIR / "resumes" / s.pop("resume_file")).read_text(encoding="utf-8")
        insert("students", {**s, "resume_filename": "resume.txt", "resume_text": resume,
                            "skills": [], "faculty_id": "u-fac-1", "agent_status": "queued",
                            "agent_message": "Waiting for agents to read the resume",
                            "updated_at": now()})
    for key, name, scope, field, op, value, pfield in BASE_RULES:
        insert("rules", {"rule_key": key, "name": name, "scope": scope, "field": field, "op": op,
                         "value": value, "posting_field": pfield, "active": 1, "version": 1,
                         "created_by": "seed", "created_at": now(), "spec": {}})
    from .guardrails import audit, posting_flags  # local import: guardrails imports db
    seen = set()
    for p in seed_postings():
        key = (p["title"].strip().lower(), p["company"].strip().lower())
        if key in seen:  # same role cross-posted twice: keep one
            audit("guardrail", "Seeder", "duplicate_skipped", {"id": p["id"]})
            continue
        seen.add(key)
        flags = posting_flags(p)
        insert("opportunities", {**p, "source": "campus", "posted_by": "u-fac-1", "retrieved_at": now(),
                                 "flags": flags, "status": "blocked" if flags else "open"})


# ---------------------------------------------------------------- lookups

def get_user(user_id: str) -> dict | None:
    return one("SELECT id, name, role, email, title FROM users WHERE id = ?", (user_id,))


def get_student(student_id: str) -> dict | None:
    return one("SELECT * FROM students WHERE id = ?", (student_id,))


def student_for_user(user_id: str) -> dict | None:
    return one("SELECT * FROM students WHERE user_id = ?", (user_id,))


def get_opportunity(opp_id: str) -> dict | None:
    return one("SELECT * FROM opportunities WHERE id = ?", (opp_id,))


def get_record(record_id: str) -> dict | None:
    return one("SELECT * FROM records WHERE id = ?", (record_id,))


def get_match(student_id: str, opp_id: str) -> dict | None:
    return one("SELECT * FROM matches WHERE student_id = ? AND opportunity_id = ?",
               (student_id, opp_id))


def next_id(prefix: str, table: str) -> str:
    n = one(f"SELECT COUNT(*) AS n FROM {table}")["n"] + 1
    while one(f"SELECT id FROM {table} WHERE id = ?", (f"{prefix}{n:04d}",)):
        n += 1
    return f"{prefix}{n:04d}"
