"""FastAPI backend for the Internship Application & Tracking Portal.

Run:  python -m uvicorn portal.main:app --port 8000
The React build (frontend/dist) is served from / when it exists."""

from __future__ import annotations

import base64
import re
import secrets
from contextlib import asynccontextmanager
from datetime import date

from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, connector, db, evals, llm, rules
from .agents import (ALL_AGENTS, ApplicationProcessingAgent, ApprovalAgent, CareerAssistant,
                     CompanyResearchAgent, EligibilityVerificationAgent, ExpertPanel, OpsAgent,
                     OpportunityDiscoveryAgent, PolicyAgent)
from .agents.approval import trail
from .agents.assistant import skill_gaps
from .config import MIN_MATCH_TO_SHOW, PERMISSIONS, RESUME_DIR
from .coordinator import (process_student, react, recheck_eligibility_only, rematch_all, start_scheduler,
                          submit, sweep)
from .graph import graph
from .guardrails import RISK_REGISTER, Forbidden, audit, require
from .notify import notify_role, notify_student
from .mcp_client import client as mcp_client
from .runtime import gateway, runtime_overview, skill_catalog


@asynccontextmanager
async def lifespan(_app):
    db.init_db()
    start_scheduler()
    yield


app = FastAPI(title="Internship Application & Tracking Portal", version="2.0", lifespan=lifespan)
db.init_db()


_QUIET = ("/api/auth/", "/api/notifications/read", "/api/assistant/clear", "/api/admin/reset")
_ACTION = {"logs": "submits a weekly log", "status": "updates the application status", "offer": "records an offer",
           "report": "submits the final report", "rating": "gives the mentor rating", "verify": "verifies a weekly log",
           "resume": "uploads a resume", "profile": "updates the profile", "skills": "edits skills",
           "rematch": "asks for a re-match", "sync": "syncs job boards", "sweep": "runs the scheduled sweep",
           "fix": "approves an ops fix", "rollback": "rolls back a rule", "close": "closes a posting",
           "apply": "applies", "panel": "asks for an expert panel review", "decision": "makes a decision",
           "kit": "regenerates the application kit", "research": "asks for company research",
           "extract": "pastes a job description", "propose": "drafts an eligibility rule",
           "publish": "publishes an eligibility rule", "assistant": "chats with the career assistant",
           "opportunities": "posts an internship"}


@app.middleware("http")
async def gateway_interface(request: Request, call_next):
    """Interface layer of the runtime: every POST/PUT from the web UI becomes a Gateway run,
    so the person's action and every agent it triggers share one run id in the activity log."""
    path = request.url.path
    if request.method not in ("POST", "PUT") or not path.startswith("/api/") or path.startswith(_QUIET):
        return await call_next(request)
    token = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
    srow = db.one("SELECT user_id FROM sessions WHERE token = ?", (token,)) if token else None
    u = db.get_user(srow["user_id"]) if srow else None
    if not u:
        return await call_next(request)
    sid = (db.student_for_user(u["id"]) or {}).get("id") if u["role"] == "student" else None
    rid = (re.search(r"IR-\d+", path) or [None])[0]
    last = path.rstrip("/").split("/")[-1]
    verb = _ACTION.get(last, "does " + last.replace("-", " "))
    demo = request.headers.get("x-demo") == "1"
    with gateway.run(f"{'[Demo] ' if demo else ''}{u['name']} {verb}", channel="demo" if demo else "web",
                     actor=u["name"], student_id=sid, record_id=rid, generic=True):
        return await call_next(request)


@app.exception_handler(Forbidden)
def _forbidden(_: Request, e: Forbidden):
    return JSONResponse({"detail": str(e)}, status_code=403)


@app.exception_handler(ValueError)
def _bad(_: Request, e: ValueError):
    return JSONResponse({"detail": str(e)}, status_code=400)


# ================================================================== auth

def current(authorization: str | None) -> dict:
    token = (authorization or "").removeprefix("Bearer ").strip()
    s = db.one("SELECT user_id FROM sessions WHERE token = ?", (token,)) if token else None
    u = db.get_user(s["user_id"]) if s else None
    if not u:
        raise HTTPException(401, "Please log in")
    return u


def student_of(u: dict) -> dict:
    if u["role"] != "student":
        raise Forbidden("Students only")
    s = db.student_for_user(u["id"])
    if not s:
        raise HTTPException(404, "Student profile not found")
    return s


def _session(user_id: str) -> str:
    token = secrets.token_urlsafe(24)
    db.insert("sessions", {"token": token, "user_id": user_id, "created_at": db.now()})
    return token


@app.post("/api/auth/login")
def login(body: dict = Body(...)):
    row = db.one("SELECT * FROM users WHERE email = ?", ((body.get("email") or "").strip().lower(),))
    if not row or not db.check_password(body.get("password") or "", row["password_hash"]):
        raise HTTPException(401, "Wrong email or password")
    audit("human", row["name"], "login", {})
    return {"token": _session(row["id"])}


@app.post("/api/auth/register")
def register(body: dict = Body(...)):
    email = (body.get("email") or "").strip().lower()
    name = (body.get("name") or "").strip()
    pw = body.get("password") or ""
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) or len(name) < 2:
        raise ValueError("Enter your name and a valid email")
    if len(pw) < 6:
        raise ValueError("Password must be at least 6 characters")
    if db.one("SELECT id FROM users WHERE email = ?", (email,)):
        raise ValueError("An account with this email already exists")
    uid = db.next_id("u-stu-", "users")
    sid = db.next_id("s-", "students")
    db.insert("users", {"id": uid, "name": name, "role": "student", "email": email, "title": "Student",
                        "password_hash": db.hash_password(pw), "created_at": db.now()})
    faculty = db.one("SELECT id FROM users WHERE role = 'faculty' ORDER BY id LIMIT 1")
    db.insert("students", {"id": sid, "user_id": uid, "name": name, "email": email,
                           "usn": (body.get("usn") or "").strip().upper(),
                           "department": body.get("department") or "CSE",
                           "semester": int(body.get("semester") or 5), "skills": [],
                           "open_to_remote": 1, "faculty_id": faculty["id"] if faculty else None,
                           "agent_status": "idle", "agent_message": "Upload your resume to get matches",
                           "updated_at": db.now()})
    audit("human", name, "registered", {"student": sid})
    return {"token": _session(uid)}


@app.post("/api/auth/logout")
def logout(authorization: str = Header(None)):
    token = (authorization or "").removeprefix("Bearer ").strip()
    db.execute("DELETE FROM sessions WHERE token = ?", (token,))
    return {"ok": True}


@app.get("/api/me")
def me(authorization: str = Header(None)):
    u = current(authorization)
    unread = db.one("SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND read = 0", (u["id"],))["n"]
    return {"user": u, "student": db.student_for_user(u["id"]) if u["role"] == "student" else None,
            "permissions": PERMISSIONS.get(u["role"], []), "unread": unread,
            "llm": {"provider": "groq" if llm.available() else "offline", "model": config.MODEL_PRIMARY,
                    "error": llm.last_error}}


@app.get("/api/notifications")
def notifications(authorization: str = Header(None)):
    u = current(authorization)
    return db.query("SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 40", (u["id"],))


@app.post("/api/notifications/read")
def notifications_read(authorization: str = Header(None)):
    u = current(authorization)
    db.execute("UPDATE notifications SET read = 1 WHERE user_id = ?", (u["id"],))
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True, "llm": "groq" if llm.available() else "offline", "llm_error": llm.last_error,
            "today": date.today().isoformat()}


# ================================================================== student profile

PROFILE_FIELDS = {"name": str, "usn": str, "phone": str, "department": str, "semester": int,
                  "cgpa": float, "active_backlogs": int, "attendance_pct": float,
                  "preferred_domains": str, "preferred_locations": str, "open_to_remote": int, "links": str}


@app.get("/api/profile")
def get_profile(authorization: str = Header(None)):
    return student_of(current(authorization))


@app.put("/api/profile")
def put_profile(body: dict = Body(...), authorization: str = Header(None)):
    u = require(current(authorization), "edit_profile")
    s = student_of(u)
    data = {}
    for k, typ in PROFILE_FIELDS.items():
        if k in body:
            v = body[k]
            data[k] = None if v in ("", None) else typ(v)
    if data.get("cgpa") is not None and not 0 <= data["cgpa"] <= 10:
        raise ValueError("CGPA must be between 0 and 10")
    if data.get("attendance_pct") is not None and not 0 <= data["attendance_pct"] <= 100:
        raise ValueError("Attendance must be between 0 and 100")
    if data.get("semester") is not None and not 1 <= data["semester"] <= 8:
        raise ValueError("Semester must be 1-8")
    data["updated_at"] = db.now()
    db.update("students", s["id"], data)
    if data.get("name"):
        db.execute("UPDATE users SET name = ? WHERE id = ?", (data["name"], u["id"]))
    audit("human", u["name"], "profile_updated", {"fields": sorted(data)})
    changed = {k for k in data if k != "updated_at" and data[k] != s.get(k)}
    if s.get("skills") and changed & {"preferred_domains", "preferred_locations", "open_to_remote"}:
        _set_matching(s["id"])
        submit(process_student, s["id"], None, True, "web", "preferences changed")
    elif s.get("skills") and changed & {"cgpa", "attendance_pct", "active_backlogs", "semester", "department"}:
        submit(recheck_eligibility_only, s["id"])
    return db.get_student(s["id"])


@app.put("/api/profile/skills")
def put_skills(body: dict = Body(...), authorization: str = Header(None)):
    u = require(current(authorization), "edit_profile")
    s = student_of(u)
    skills = []
    for x in body.get("skills") or []:
        x = str(x).strip().lower()[:40]
        if x and x not in skills:
            skills.append(x)
    db.update("students", s["id"], {"skills": skills[:60], "updated_at": db.now()})
    audit("human", u["name"], "skills_edited", {"count": len(skills)})
    _set_matching(s["id"])
    submit(process_student, s["id"], None, True, "web", "skills edited")
    return db.get_student(s["id"])


def _set_matching(sid: str, msg: str = "Re-matching internships…") -> None:
    db.update("students", sid, {"agent_status": "matching", "agent_message": msg})


@app.post("/api/profile/resume")
def upload_resume(body: dict = Body(...), authorization: str = Header(None)):
    u = require(current(authorization), "edit_profile")
    s = student_of(u)
    name = body.get("filename") or ""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ("pdf", "docx", "txt"):
        raise ValueError("Upload a PDF, DOCX or TXT file")
    try:
        data = base64.b64decode(body.get("content_base64") or "", validate=True)
    except Exception:
        raise ValueError("Could not read the uploaded file")
    if not data or len(data) > 5 * 1024 * 1024:
        raise ValueError("File must be under 5 MB")
    RESUME_DIR.mkdir(parents=True, exist_ok=True)
    stored = f"{s['id']}_{secrets.token_hex(4)}.{ext}"
    (RESUME_DIR / stored).write_bytes(data)
    db.update("students", s["id"], {"resume_filename": name[:120], "agent_status": "parsing",
                                    "agent_message": "Reading your resume…"})
    audit("human", u["name"], "resume_uploaded", {"file": name[:120], "bytes": len(data)})
    submit(process_student, s["id"], stored)
    return {"ok": True}


@app.post("/api/profile/rematch")
def rematch(authorization: str = Header(None)):
    s = student_of(current(authorization))
    _set_matching(s["id"])
    submit(process_student, s["id"], None, False, "web", "re-match requested")
    return {"ok": True}


# ================================================================== internships (student)

def _record_for(sid: str, oid: str) -> dict | None:
    return db.one("SELECT id, stage FROM records WHERE student_id = ? AND opportunity_id = ?", (sid, oid))


def _card(m: dict, o: dict, sid: str) -> dict:
    r = _record_for(sid, o["id"])
    return {"id": o["id"], "title": o["title"], "company": o["company"], "location": o["location"],
            "mode": o["mode"], "stipend": o["stipend"], "duration_weeks": o["duration_weeks"],
            "deadline": o["deadline"], "source": o["source"], "url": o["url"],
            "score": m["score"], "have": m["have"], "missing": m["missing"], "why": m["why"],
            "eligibility": m["eligibility"]["status"], "eligibility_summary": m["eligibility"]["summary"],
            "record": r}


@app.get("/api/internships")
def internships(q: str = "", eligible: bool = False, remote: bool = False, min_score: float = 0,
                authorization: str = Header(None)):
    s = student_of(current(authorization))
    rows = db.query("SELECT m.*, o.title AS o_title FROM matches m JOIN opportunities o ON o.id = m.opportunity_id "
                    "WHERE m.student_id = ? AND o.status = 'open' ORDER BY m.score DESC", (s["id"],))
    out = []
    for m in rows:
        o = db.get_opportunity(m["opportunity_id"])
        if m["score"] < max(MIN_MATCH_TO_SHOW, min_score):
            continue
        if eligible and m["eligibility"]["status"] != "ELIGIBLE":
            continue
        if remote and o["mode"] != "remote":
            continue
        if q and q.lower() not in f"{o['title']} {o['company']} {o['location']} {o['description']}".lower():
            continue
        out.append(_card(m, o, s["id"]))
    total = db.one("SELECT COUNT(*) AS n FROM opportunities WHERE status = 'open'")["n"]
    return {"items": out, "open_postings": total, "status": s["agent_status"], "message": s["agent_message"]}


@app.get("/api/internships/{opp_id}")
def internship(opp_id: str, authorization: str = Header(None)):
    s = student_of(current(authorization))
    o = db.get_opportunity(opp_id)
    m = db.get_match(s["id"], opp_id)
    if not o or not m or o["status"] != "open":
        raise HTTPException(404, "Internship not found")
    cached = db.one("SELECT data FROM research WHERE company = ?", (re.sub(r"[^A-Za-z0-9 &().-]", "", o["company"]).strip()[:60],))
    return {"opportunity": o, "match": m, "record": _record_for(s["id"], opp_id),
            "research": cached["data"] if cached else None}


@app.post("/api/internships/{opp_id}/panel")
def internship_panel(opp_id: str, authorization: str = Header(None)):
    s = student_of(current(authorization))
    o = db.get_opportunity(opp_id)
    if not o:
        raise HTTPException(404, "Internship not found")
    with gateway.run(f"Expert panel review: {o['title']} at {o['company']}", actor=s["name"], student_id=s["id"]):
        return ExpertPanel().review(s, o)


@app.post("/api/research")
def research(body: dict = Body(...), authorization: str = Header(None)):
    u = current(authorization)
    sid = (db.student_for_user(u["id"]) or {}).get("id")
    with gateway.run(f"Research company: {body.get('company', '')}", actor=u["name"], student_id=sid):
        return CompanyResearchAgent().run(body.get("company", ""), force=bool(body.get("force")))


@app.post("/api/internships/{opp_id}/apply")
def start_application(opp_id: str, authorization: str = Header(None)):
    u = require(current(authorization), "apply")
    s = student_of(u)
    o, m = db.get_opportunity(opp_id), db.get_match(s["id"], opp_id)
    if not o or not m or o["status"] != "open":
        raise HTTPException(404, "Internship not found")
    if m["eligibility"]["status"] != "ELIGIBLE":
        raise ValueError("You are not eligible: " + "; ".join(m["eligibility"]["shortfalls"]))
    existing = _record_for(s["id"], opp_id)
    if existing:
        return {"record_id": existing["id"]}
    rid = db.next_id("IR-", "records")
    with gateway.run(f"Start application: {o['title']} at {o['company']}", actor=u["name"], student_id=s["id"],
                     record_id=rid):
        _start(rid, s, o, m, u)
    return {"record_id": rid}


def _start(rid, s, o, m, u):
    opp_id = o["id"]
    db.insert("records", {"id": rid, "student_id": s["id"], "opportunity_id": opp_id, "stage": "SAVED",
                          "match": {k: m[k] for k in ("score", "have", "missing", "why", "improve", "highlight")},
                          "eligibility": m["eligibility"], "created_at": db.now(), "updated_at": db.now()})
    audit("human", u["name"], "application_started", {"opportunity": opp_id}, rid)
    ApplicationProcessingAgent().prepare(db.get_record(rid))


@app.get("/api/insights")
def insights(authorization: str = Header(None)):
    s = student_of(current(authorization))
    rows = db.query("SELECT m.score, m.eligibility FROM matches m JOIN opportunities o ON o.id = m.opportunity_id "
                    "WHERE m.student_id = ? AND o.status = 'open'", (s["id"],))
    shown = [r for r in rows if r["score"] >= MIN_MATCH_TO_SHOW]
    recs = db.query("SELECT stage FROM records WHERE student_id = ?", (s["id"],))
    return {"matches": len(shown), "strong": sum(1 for r in shown if r["score"] >= 70),
            "eligible": sum(1 for r in shown if r["eligibility"]["status"] == "ELIGIBLE"),
            "gaps": skill_gaps(s["id"])[:8], "applications": len(recs),
            "active": sum(1 for r in recs if r["stage"] == "ONGOING")}


# ================================================================== tracked records

def visible(u: dict, rec: dict) -> bool:
    if u["role"] == "admin":
        return True
    if u["role"] == "student":
        s = db.student_for_user(u["id"])
        return bool(s) and rec["student_id"] == s["id"]
    if u["role"] == "mentor":
        return rec.get("mentor_id") == u["id"]
    if u["role"] == "faculty":
        return (db.get_student(rec["student_id"]) or {}).get("faculty_id") == u["id"]
    return False


def load_record(rid: str, u: dict) -> dict:
    rec = db.get_record(rid)
    if not rec:
        raise HTTPException(404, "Record not found")
    if not visible(u, rec):
        raise Forbidden("You cannot view this record")
    return rec


def summary(r: dict) -> dict:
    o = db.get_opportunity(r["opportunity_id"]) or {}
    s = db.get_student(r["student_id"]) or {}
    pending = db.one("SELECT agent_recommendation FROM approvals WHERE record_id = ? AND decision = 'PENDING' "
                     "ORDER BY id DESC LIMIT 1", (r["id"],))
    unverified = db.one("SELECT COUNT(*) AS n FROM progress_logs WHERE record_id = ? AND mentor_verified = 0",
                        (r["id"],))["n"]
    return {"id": r["id"], "stage": r["stage"], "student_id": r["student_id"], "student": s.get("name"),
            "usn": s.get("usn"), "department": s.get("department"), "opportunity_id": r["opportunity_id"],
            "title": o.get("title"), "company": o.get("company"), "location": o.get("location"),
            "score": (r.get("match") or {}).get("score"), "health": (r.get("progress_health") or {}).get("status"),
            "mentor_id": r.get("mentor_id"), "recommendation": pending["agent_recommendation"] if pending else None,
            "unverified_logs": unverified,
            "needs_rating": r["stage"] in ("ONGOING", "COMPLETED") and (r.get("final_report") or {}).get("mentor_score") is None,
            "updated_at": r["updated_at"]}


@app.get("/api/records")
def records(authorization: str = Header(None)):
    u = current(authorization)
    return [summary(r) for r in db.query("SELECT * FROM records ORDER BY updated_at DESC") if visible(u, r)]


@app.get("/api/records/{rid}")
def record(rid: str, authorization: str = Header(None)):
    u = current(authorization)
    r = load_record(rid, u)
    mentor = db.get_user(r["mentor_id"]) if r.get("mentor_id") else None
    return {"record": r, "summary": summary(r), "opportunity": db.get_opportunity(r["opportunity_id"]),
            "student": {k: v for k, v in db.get_student(r["student_id"]).items() if k != "resume_text"},
            "mentor": mentor, "approvals": trail(rid),
            "logs": db.query("SELECT * FROM progress_logs WHERE record_id = ? ORDER BY week", (rid,)),
            "evaluations": db.query("SELECT * FROM evaluations WHERE record_id = ? ORDER BY version", (rid,)),
            "activity": db.query("SELECT ts, kind, actor, action FROM audit WHERE record_id = ? AND kind IN "
                                 "('agent','human','guardrail') ORDER BY id DESC LIMIT 40", (rid,))}


def own(rid: str, u: dict, stages: tuple[str, ...]) -> dict:
    if u["role"] != "student":
        raise Forbidden("Only the student can do this")
    r = load_record(rid, u)
    if r["stage"] not in stages:
        raise ValueError("That action is not available at this stage")
    return r


@app.post("/api/records/{rid}/kit")
def regenerate_kit(rid: str, authorization: str = Header(None)):
    u = require(current(authorization), "apply")
    r = own(rid, u, ("SAVED", "APPLIED", "INTERVIEW"))
    with gateway.run(f"Regenerate application kit for {rid}", actor=u["name"], student_id=r["student_id"],
                     record_id=rid):
        return ApplicationProcessingAgent().prepare(r)


STUDENT_MOVES = {"APPLIED": ("SAVED",), "INTERVIEW": ("APPLIED",), "NOT_SELECTED": ("APPLIED", "INTERVIEW"),
                 "WITHDRAWN": ("SAVED", "APPLIED", "INTERVIEW", "NOC_CHANGES")}


@app.post("/api/records/{rid}/status")
def move(rid: str, body: dict = Body(...), authorization: str = Header(None)):
    u = require(current(authorization), "track")
    to = body.get("stage", "")
    if to not in STUDENT_MOVES:
        raise ValueError("Unknown status")
    r = own(rid, u, STUDENT_MOVES[to])
    extra = {}
    if to == "APPLIED":
        if not body.get("applied_on"):
            raise ValueError("Enter the date you applied")
        extra["submission"] = {"applied_on": body["applied_on"], "reference": body.get("reference", ""),
                               "confirmed_by": u["name"], "confirmed_at": db.now()}
    db.update("records", rid, {"stage": to, "updated_at": db.now(), **extra})
    audit("human", u["name"], f"marked_{to.lower()}", {"note": body.get("note", "")}, rid)
    if to in ("NOT_SELECTED", "WITHDRAWN"):
        o = db.get_opportunity(r["opportunity_id"])
        from .memory import LongTermMemory
        LongTermMemory.remember(r["student_id"], "outcome", f"{to.replace('_', ' ').title()} at {o['company']} "
                                f"({o['title']}). {body.get('note', '')}".strip())
    return {"stage": to}


@app.post("/api/records/{rid}/offer")
def offer(rid: str, body: dict = Body(...), authorization: str = Header(None)):
    u = require(current(authorization), "track")
    own(rid, u, ("APPLIED", "INTERVIEW", "NOC_CHANGES"))
    if not body.get("offer_ref") or not body.get("start_date"):
        raise ValueError("Offer reference and start date are required")
    off = {k: body.get(k, "") for k in ("offer_ref", "start_date", "duration_weeks", "stipend", "notes")}
    off["duration_weeks"] = int(off["duration_weeks"] or 0) or None
    db.update("records", rid, {"stage": "OFFERED", "offer": off, "updated_at": db.now()})
    audit("human", u["name"], "offer_recorded", off, rid)
    return {"agents": react(rid), "stage": db.get_record(rid)["stage"]}


@app.post("/api/records/{rid}/decision")
def decision(rid: str, body: dict = Body(...), authorization: str = Header(None)):
    u = current(authorization)
    gate = body.get("gate", "")
    require(u, "decide_noc" if gate == "NOC" else "decide_grade")
    r = load_record(rid, u)
    with gateway.run(f"{u['name']} decides {gate} for {rid}", actor=u["name"], student_id=r["student_id"],
                     record_id=rid):
        ApprovalAgent().decide(r, gate, body.get("decision", ""), u, body.get("remarks", ""), body.get("mentor_id"))
        agents = react(rid, body.get("remarks", ""), u["name"])
    return {"agents": agents, "stage": db.get_record(rid)["stage"]}


@app.post("/api/records/{rid}/logs")
def add_log(rid: str, body: dict = Body(...), authorization: str = Header(None)):
    u = require(current(authorization), "submit_log")
    r = own(rid, u, ("ONGOING",))
    week = int(body.get("week") or 0)
    if not 1 <= week <= 52:
        raise ValueError("Week must be between 1 and 52")
    if db.one("SELECT id FROM progress_logs WHERE record_id = ? AND week = ?", (rid, week)):
        raise ValueError(f"Week {week} is already logged")
    if len(str(body.get("tasks", "")).strip()) < 10:
        raise ValueError("Describe what you worked on this week")
    hours = float(body.get("hours") or 0)
    if not 0 <= hours <= 80:
        raise ValueError("Hours must be 0-80")
    db.insert("progress_logs", {"record_id": rid, "week": week, "hours": hours, "tasks": body["tasks"],
                                "learnings": body.get("learnings", ""), "artifacts": body.get("artifacts", ""),
                                "submitted_at": db.now()})
    audit("human", u["name"], "log_submitted", {"week": week, "hours": hours}, rid)
    from .notify import notify
    notify(r.get("mentor_id"), f"{u['name']} submitted the week {week} log", f"#/records/{rid}")
    return {"agents": react(rid)}


@app.post("/api/logs/{log_id}/verify")
def verify_log(log_id: int, body: dict = Body({}), authorization: str = Header(None)):
    u = require(current(authorization), "verify_log")
    log = db.one("SELECT * FROM progress_logs WHERE id = ?", (log_id,))
    if not log:
        raise HTTPException(404, "Log not found")
    r = load_record(log["record_id"], u)
    db.update("progress_logs", log_id, {"mentor_verified": 1, "mentor_remarks": body.get("remarks", "")})
    audit("human", u["name"], "log_verified", {"week": log["week"]}, r["id"])
    notify_student(r["student_id"], f"Mentor verified your week {log['week']} log"
                   + (f": {body['remarks']}" if body.get("remarks") else ""), f"#/records/{r['id']}")
    return {"agents": react(r["id"]) if r["stage"] == "ONGOING" else []}


@app.post("/api/records/{rid}/report")
def final_report(rid: str, body: dict = Body(...), authorization: str = Header(None)):
    u = require(current(authorization), "submit_report")
    r = own(rid, u, ("ONGOING",))
    if len(str(body.get("summary", "")).strip()) < 80:
        raise ValueError("Write a report summary of at least 80 characters")
    fr = dict(r.get("final_report") or {})
    fr.update({"summary": body["summary"], "link": body.get("link", ""), "submitted_at": db.now()})
    db.update("records", rid, {"stage": "COMPLETED", "final_report": fr, "updated_at": db.now()})
    audit("human", u["name"], "report_submitted", {}, rid)
    from .notify import notify
    if fr.get("mentor_score") is None:
        notify(r.get("mentor_id"), f"{u['name']} finished the internship; please give your final rating",
               f"#/records/{rid}")
    return {"agents": react(rid), "stage": db.get_record(rid)["stage"]}


@app.post("/api/records/{rid}/rating")
def mentor_rating(rid: str, body: dict = Body(...), authorization: str = Header(None)):
    u = require(current(authorization), "mentor_rating")
    r = load_record(rid, u)
    if r["stage"] not in ("ONGOING", "COMPLETED"):
        raise ValueError("Rating is possible only during or after the internship")
    score = float(body.get("score", -1))
    if not 0 <= score <= 10:
        raise ValueError("Rating must be 0-10")
    fr = dict(r.get("final_report") or {})
    fr.update({"mentor_score": score, "mentor_feedback": body.get("feedback", ""), "mentor_name": u["name"]})
    db.update("records", rid, {"final_report": fr, "updated_at": db.now()})
    audit("human", u["name"], "mentor_rating", {"score": score}, rid)
    return {"agents": react(rid) if r["stage"] == "COMPLETED" else [], "stage": db.get_record(rid)["stage"]}


# ================================================================== assistant

@app.get("/api/assistant")
def assistant_history(authorization: str = Header(None)):
    s = student_of(current(authorization))
    return db.query("SELECT role, content, tools, ts FROM chat_messages WHERE student_id = ? ORDER BY id DESC "
                    "LIMIT 30", (s["id"],))[::-1]


@app.post("/api/assistant")
def assistant(body: dict = Body(...), authorization: str = Header(None)):
    u = require(current(authorization), "assistant")
    msg = (body.get("message") or "").strip()
    if not msg:
        raise ValueError("Type a message")
    s = student_of(u)
    with gateway.run(f"Chat: {msg[:60]}", channel="chat", actor=u["name"], student_id=s["id"]):
        return CareerAssistant(s).chat(msg[:1000])


@app.post("/api/assistant/clear")
def assistant_clear(authorization: str = Header(None)):
    s = student_of(current(authorization))
    db.execute("DELETE FROM chat_messages WHERE student_id = ?", (s["id"],))
    return {"ok": True}


# ================================================================== faculty

def _my_students(u: dict) -> list[dict]:
    if u["role"] == "admin":
        return db.query("SELECT * FROM students ORDER BY name")
    return db.query("SELECT * FROM students WHERE faculty_id = ? ORDER BY name", (u["id"],))


def _student_row(s: dict) -> dict:
    ms = db.query("SELECT m.score, m.eligibility FROM matches m JOIN opportunities o ON o.id = m.opportunity_id "
                  "WHERE m.student_id = ? AND o.status = 'open'", (s["id"],))
    recs = db.query("SELECT stage, progress_health FROM records WHERE student_id = ?", (s["id"],))
    return {"id": s["id"], "name": s["name"], "usn": s["usn"], "department": s["department"],
            "semester": s["semester"], "cgpa": s["cgpa"], "attendance_pct": s["attendance_pct"],
            "skills": len(s.get("skills") or []), "resume": bool(s.get("resume_profile")),
            "eligible_matches": sum(1 for m in ms if m["score"] >= 60 and m["eligibility"]["status"] == "ELIGIBLE"),
            "applications": len(recs), "ongoing": sum(1 for r in recs if r["stage"] == "ONGOING"),
            "at_risk": any((r.get("progress_health") or {}).get("status") in ("AT_RISK", "DELAYED") for r in recs),
            "agent_status": s["agent_status"]}


@app.get("/api/faculty/overview")
def faculty_overview(authorization: str = Header(None)):
    u = require(current(authorization), "view_students")
    studs = _my_students(u)
    ids = {s["id"] for s in studs}
    recs = [r for r in db.query("SELECT * FROM records") if r["student_id"] in ids]
    by = lambda *st: [summary(r) for r in recs if r["stage"] in st]  # noqa: E731
    return {"students": [_student_row(s) for s in studs],
            "pending": by("NOC_PENDING", "GRADE_PENDING"),
            "at_risk": [summary(r) for r in recs if (r.get("progress_health") or {}).get("status") in ("AT_RISK", "DELAYED")
                        and r["stage"] == "ONGOING"],
            "counts": {"students": len(studs), "applied": len(by("APPLIED", "INTERVIEW")),
                       "ongoing": len(by("ONGOING")), "graded": len(by("GRADED")),
                       "pending": len(by("NOC_PENDING", "GRADE_PENDING"))}}


@app.get("/api/students/{sid}")
def student_detail(sid: str, authorization: str = Header(None)):
    u = require(current(authorization), "view_students")
    s = db.get_student(sid)
    if not s or (u["role"] == "faculty" and s["faculty_id"] != u["id"]):
        raise HTTPException(404, "Student not found")
    ms = db.query("SELECT m.score, m.have, m.missing, m.eligibility, o.id, o.title, o.company FROM matches m "
                  "JOIN opportunities o ON o.id = m.opportunity_id WHERE m.student_id = ? AND o.status = 'open' "
                  "ORDER BY m.score DESC LIMIT 8", (sid,))
    return {"student": {k: v for k, v in s.items() if k != "resume_text"}, "matches": ms,
            "records": [summary(r) for r in db.query("SELECT * FROM records WHERE student_id = ?", (sid,))],
            "gaps": skill_gaps(sid)[:6]}


@app.get("/api/mentors")
def mentors(authorization: str = Header(None)):
    current(authorization)
    return db.query("SELECT id, name, title, email FROM users WHERE role = 'mentor' ORDER BY name")


@app.get("/api/opportunities")
def opportunities(authorization: str = Header(None)):
    require(current(authorization), "post_opportunity")
    rows = db.query("SELECT * FROM opportunities ORDER BY status, retrieved_at DESC")
    for o in rows:
        st = db.one("SELECT COUNT(*) AS n, SUM(CASE WHEN score >= 60 AND json_extract(eligibility,'$.status') = "
                    "'ELIGIBLE' THEN 1 ELSE 0 END) AS good FROM matches WHERE opportunity_id = ?", (o["id"],))
        o["matched_students"] = st["good"] or 0
        o["applications"] = db.one("SELECT COUNT(*) AS n FROM records WHERE opportunity_id = ?", (o["id"],))["n"]
        o["description"] = (o["description"] or "")[:300]
    return {"items": rows, "boards_synced": db.get_meta("boards_synced")}


@app.post("/api/opportunities/extract")
def extract_opportunity(body: dict = Body(...), authorization: str = Header(None)):
    require(current(authorization), "post_opportunity")
    text = (body.get("text") or "").strip()
    if len(text) < 40:
        raise ValueError("Paste the full job description")
    with gateway.run("Extract a pasted internship posting", actor=current(authorization)["name"]):
        return OpportunityDiscoveryAgent().extract_posting(text)


@app.post("/api/opportunities")
def post_opportunity(body: dict = Body(...), authorization: str = Header(None)):
    u = require(current(authorization), "post_opportunity")
    if not body.get("title") or not body.get("company") or not body.get("url"):
        raise ValueError("Title, company and apply link are required")
    if not re.match(r"^https?://", body["url"]):
        raise ValueError("Apply link must start with http:// or https://")
    num = lambda k, t: t(body[k]) if body.get(k) not in (None, "") else None  # noqa: E731
    p = {"id": db.next_id("fp-", "opportunities"), "title": body["title"].strip(), "company": body["company"].strip(),
         "location": body.get("location", ""), "mode": body.get("mode") or "onsite",
         "duration_weeks": num("duration_weeks", int), "stipend": body.get("stipend", ""),
         "deadline": body.get("deadline", ""), "description": body.get("description", ""),
         "required_skills": [s.strip().lower() for s in body.get("required_skills") or [] if s.strip()],
         "min_cgpa": num("min_cgpa", float), "max_active_backlogs": num("max_active_backlogs", int),
         "eligible_branches": body.get("eligible_branches") or [], "min_semester": num("min_semester", int),
         "source": "faculty", "url": body["url"], "posted_by": u["id"]}
    oid, outcome = OpportunityDiscoveryAgent().store_posting(p)
    audit("human", u["name"], "opportunity_posted", {"id": oid, "outcome": outcome})
    if outcome == "added":
        submit(rematch_all, f"new posting {oid}")
    return {"id": oid, "outcome": outcome}


@app.post("/api/opportunities/{oid}/close")
def close_opportunity(oid: str, authorization: str = Header(None)):
    u = require(current(authorization), "post_opportunity")
    db.update("opportunities", oid, {"status": "closed"})
    audit("human", u["name"], "opportunity_closed", {"id": oid})
    return {"ok": True}


@app.post("/api/opportunities/sync")
def sync(authorization: str = Header(None)):
    u = require(current(authorization), "sync_boards")

    def job():
        OpportunityDiscoveryAgent().sync_boards()
        rematch_all("job boards synced")
    submit(job)
    audit("human", u["name"], "sync_requested", {})
    return {"ok": True}


@app.get("/api/rules")
def get_rules(authorization: str = Header(None)):
    require(current(authorization), "manage_rules")
    return {"active": rules.active_rules(), "all": rules.all_rules()}


@app.post("/api/rules/propose")
def rules_propose(body: dict = Body(...), authorization: str = Header(None)):
    u = require(current(authorization), "manage_rules")
    with gateway.run(f"Draft rule: {body.get('requirement', '')[:60]}", actor=u["name"]):
        return PolicyAgent().propose(body.get("requirement", ""))


@app.post("/api/rules/publish")
def rules_publish(body: dict = Body(...), authorization: str = Header(None)):
    u = require(current(authorization), "manage_rules")
    with gateway.run("Publish eligibility rule", actor=u["name"]):
        released = PolicyAgent().publish(body.get("spec") or {}, u)
        n = EligibilityVerificationAgent().recheck_all()
    notify_role("student", f"College eligibility rule updated: {released['name']}", "#/internships")
    return {"rule": released, "rechecked": n}


@app.post("/api/rules/{key}/rollback")
def rules_rollback(key: str, authorization: str = Header(None)):
    u = require(current(authorization), "manage_rules")
    res = rules.rollback(key)
    audit("human", u["name"], "rule_rolled_back", res)
    res["rechecked"] = EligibilityVerificationAgent().recheck_all()
    return res


# ================================================================== mentor

@app.get("/api/mentor/overview")
def mentor_overview(authorization: str = Header(None)):
    u = current(authorization)
    if u["role"] != "mentor":
        raise Forbidden("Mentors only")
    return [summary(r) for r in db.query("SELECT * FROM records WHERE mentor_id = ? ORDER BY updated_at DESC",
                                         (u["id"],))]


# ================================================================== admin

def admin(authorization) -> dict:
    return require(current(authorization), "view_system")


@app.get("/api/admin/overview")
def admin_overview(authorization: str = Header(None)):
    admin(authorization)
    count = lambda sql: db.one(sql)["n"]  # noqa: E731
    runs = db.query("SELECT r.*, (SELECT COUNT(*) FROM audit a WHERE a.run_id = r.run_id) AS events FROM runs r "
                    "ORDER BY r.started_at DESC LIMIT 15")
    a = lambda where: count(f"SELECT COUNT(*) AS n FROM audit WHERE {where}")  # noqa: E731
    worklet = ["Opportunity Discovery Agent", "Eligibility Verification Agent", "Application Processing Agent",
               "Approval Agent", "Progress Tracking Agent", "Evaluation Agent"]
    calls = {r["actor"]: r["n"] for r in db.query("SELECT actor, COUNT(*) AS n FROM audit WHERE kind = 'agent' "
                                                  "AND action = 'called' GROUP BY actor")}
    concepts = [
        (1, "Agent (plan, act, observe, revise)", "Coordinator loop on every run; Career Assistant clarifies before acting",
         f"{a("kind = 'loop' AND action = 'PLAN'")} plans, {a("kind = 'loop' AND action = 'IMPROVE'")} revisions"),
        (2, "Tools & function calling", "Career Assistant (function calling); agents' tool allow-lists",
         f"{a("kind = 'tool'")} tool calls, {a("kind = 'llm' AND detail LIKE '%function_calls%'")} function-calling turns"),
        (3, "Skills", "skills/*/SKILL.md, loaded only when the owning agent runs",
         f"{a("action = 'skill_loaded'")} skill loads"),
        (4, "Memory & context", "Session memory per run; long-term memory in SQLite + data/memory/*.md",
         f"{a("kind = 'memory' AND action = 'remembered'")} saved, {a("kind = 'memory' AND action = 'recalled'")} recalled"),
        (5, "MCP connector", "mcp-server/portal_mcp_server.py over stdio; File + SQLite + API tools",
         f"{a("kind = 'tool' AND json_extract(detail, '$.transport') = 'mcp'")} calls over MCP"),
        (6, "OpenClaw-style runtime", "Gateway -> run -> agent (skill, tools, memory, audit), portal/runtime.py",
         f"{count('SELECT COUNT(*) AS n FROM runs')} runs, {a("kind = 'agent' AND action = 'called'")} agent calls"),
        (7, "Node graph", "portal/graph.py routes every record; human gates for NOC and grade",
         f"{count('SELECT COUNT(*) AS n FROM records')} tracked records"),
        (8, "Parallel swarm", "Expert panel: 4 reviewers in parallel, merge, critique, resolve",
         f"{calls.get('Expert Panel', 0)} panel reviews"),
        (9, "Deep research", "Company insights: question, search, extract, compare, synthesize",
         f"{count('SELECT COUNT(*) AS n FROM research')} companies researched"),
        (10, "Cloud agent", "System health: observe, diagnose, fix after approval",
         f"{calls.get('Ops Agent', 0)} diagnoses, {a("action LIKE 'ops_fix_%'")} approved fixes"),
        (11, "Agentic SDLC", "Eligibility rules: requirement, design, tests, impact, publish, monitor",
         f"{calls.get('Policy Agent', 0)} Policy Agent runs, {count("SELECT COUNT(*) AS n FROM rules WHERE created_by != 'seed'")} published"),
        (12, "Responsible autonomy", "Human gates, permissions, PII masking, scam blocking, audit, rollback, evals",
         f"{count('SELECT COUNT(*) AS n FROM approvals')} approval events, {a("kind = 'guardrail'")} guardrail events"),
    ]
    return {"concepts": [{"n": n, "name": nm, "where": w, "evidence": e} for n, nm, w, e in concepts],
            "worklet_agents": [{"name": w, "calls": calls.get(w, 0)} for w in worklet],
            "users": count("SELECT COUNT(*) AS n FROM users"), "students": count("SELECT COUNT(*) AS n FROM students"),
            "open_postings": count("SELECT COUNT(*) AS n FROM opportunities WHERE status = 'open'"),
            "blocked_postings": count("SELECT COUNT(*) AS n FROM opportunities WHERE status = 'blocked'"),
            "records": count("SELECT COUNT(*) AS n FROM records"),
            "llm_calls": count("SELECT COUNT(*) AS n FROM audit WHERE kind = 'llm'"),
            "tool_calls": count("SELECT COUNT(*) AS n FROM audit WHERE kind = 'tool'"),
            "boards_synced": db.get_meta("boards_synced"), "runs": runs}


@app.get("/api/admin/agents")
def admin_agents(authorization: str = Header(None)):
    admin(authorization)
    calls = {r["actor"]: r["n"] for r in db.query(
        "SELECT actor, COUNT(*) AS n FROM audit WHERE kind = 'agent' AND action = 'called' GROUP BY actor")}
    return {"agents": [{**a.card(), "calls": calls.get(a.name, 0)} for a in ALL_AGENTS], "skills": skill_catalog(),
            "graph": graph(), "tools": connector.list_tools(), "runtime": runtime_overview()}


@app.get("/api/admin/mcp")
def admin_mcp(authorization: str = Header(None)):
    admin(authorization)
    st = mcp_client.status()
    st["recent_calls"] = db.query("SELECT ts, actor, action, json_extract(detail, '$.transport') AS transport, "
                                  "json_extract(detail, '$.ms') AS ms, json_extract(detail, '$.ok') AS ok "
                                  "FROM audit WHERE kind = 'tool' ORDER BY id DESC LIMIT 25")
    return st


@app.get("/api/admin/runs/{run_id}")
def admin_run(run_id: str, authorization: str = Header(None)):
    admin(authorization)
    return {"run": db.one("SELECT * FROM runs WHERE run_id = ?", (run_id,)),
            "events": db.query("SELECT * FROM audit WHERE run_id = ? ORDER BY id", (run_id,))}


# ================================================================== activity log (all roles)

def _run_scope(u: dict) -> tuple[str, tuple]:
    """Which runs a user may see: their own runs (students), their students' runs
    (coordinator), their interns' runs (mentor), everything (admin)."""
    if u["role"] == "admin":
        return "1=1", ()
    if u["role"] == "student":
        s = db.student_for_user(u["id"])
        return "r.student_id = ?", ((s or {}).get("id", "-"),)
    if u["role"] == "faculty":
        return ("(r.actor = ? OR r.student_id IN (SELECT id FROM students WHERE faculty_id = ?))",
                (u["name"], u["id"]))
    return ("(r.actor = ? OR r.record_id IN (SELECT id FROM records WHERE mentor_id = ?))", (u["name"], u["id"]))


@app.get("/api/activity")
def activity(after: int = 0, limit: int = 150, authorization: str = Header(None)):
    """Live agent activity: every run, agent call, skill load, MCP tool call, model call,
    memory access and human decision, newest last. Poll with ?after=<last id>."""
    u = current(authorization)
    where, params = _run_scope(u)
    rows = db.query("SELECT a.id, a.ts, a.run_id, a.kind, a.actor, a.action, a.record_id, a.detail, r.goal, "
                    "r.channel FROM audit a JOIN runs r ON r.run_id = a.run_id "
                    f"WHERE a.id > ? AND {where} ORDER BY a.id DESC LIMIT ?", (after, *params, min(limit, 500)))
    for r in rows:  # prompts/responses are for the admin only
        if u["role"] != "admin" and isinstance(r["detail"], dict):
            r["detail"] = {k: v for k, v in r["detail"].items() if k not in ("prompt", "response")}
    return rows[::-1]


TRIGGERS = {
    "Resume Agent": "Runs when a student uploads a resume (and at first start for the demo student).",
    "Opportunity Discovery Agent": "Runs at startup, after a resume upload, on Re-match and when a new internship is posted.",
    "Eligibility Verification Agent": "Runs inside every match, and again when an offer is checked before the NOC.",
    "Application Processing Agent": "Runs when the student clicks Apply on an internship.",
    "Approval Agent": "Runs when the student records an offer, when the coordinator decides, and before grade sign-off.",
    "Progress Tracking Agent": "Runs when the NOC is approved and after every weekly log or mentor verification.",
    "Evaluation Agent": "Runs when the final report and the mentor's rating are both in.",
    "Career Assistant": "Runs when the student sends a message in the Career assistant chat.",
    "Expert Panel": "Runs when the student clicks Get review on an internship (4 reviewers in parallel).",
    "Company Research Agent": "Runs when the student clicks Research company on an internship.",
    "Policy Agent": "Runs when the coordinator drafts a rule on the Eligibility rules page.",
    "Ops Agent": "Runs when the admin opens System health.",
}


@app.get("/api/activity/agents")
def activity_agents(authorization: str = Header(None)):
    """All agents with how often they ran (in the runs this user may see) and what triggers them."""
    from .agents import WORKLET_AGENTS
    from .agents.panel import ROLES
    u = current(authorization)
    where, params = _run_scope(u)
    by = {r["actor"]: r for r in db.query(
        "SELECT a.actor, COUNT(*) AS n, MAX(a.ts) AS last FROM audit a JOIN runs r ON r.run_id = a.run_id "
        f"WHERE a.kind = 'agent' AND a.action = 'called' AND {where} GROUP BY a.actor", params)}
    agents = [{"name": a.name, "worklet": a in WORKLET_AGENTS, "calls": by.get(a.name, {}).get("n", 0),
               "last": by.get(a.name, {}).get("last"), "trigger": TRIGGERS.get(a.name, ""), "skill": a.skill}
              for a in ALL_AGENTS]
    reviewers = [{"name": r, "calls": by.get(r, {}).get("n", 0)} for r in ROLES]
    return {"agents": agents, "reviewers": reviewers, "ran": sum(1 for a in agents if a["calls"]),
            "total": len(agents)}


@app.get("/api/admin/demo")
def demo_status(authorization: str = Header(None)):
    from .demo import STATUS
    admin(authorization)
    return STATUS


@app.post("/api/admin/demo")
def demo_start(authorization: str = Header(None)):
    from .demo import STATUS, run_journey
    admin(authorization)
    if STATUS["state"] == "running":
        raise ValueError("The demo journey is already running")
    STATUS.update(state="running", step="Starting…", done=0, total=0, error="")
    submit(run_journey)
    return STATUS


@app.get("/api/activity/runs/{run_id}")
def activity_run(run_id: str, authorization: str = Header(None)):
    u = current(authorization)
    where, params = _run_scope(u)
    run = db.one(f"SELECT r.* FROM runs r WHERE r.run_id = ? AND {where}", (run_id, *params))
    if not run:
        raise HTTPException(404, "Run not found")
    events = db.query("SELECT a.*, ? AS goal FROM audit a WHERE a.run_id = ? ORDER BY a.id", (run["goal"], run_id))
    if u["role"] != "admin":
        for e in events:
            if isinstance(e["detail"], dict):
                e["detail"] = {k: v for k, v in e["detail"].items() if k not in ("prompt", "response")}
    return {"run": run, "events": events}


@app.get("/api/activity/runs")
def activity_runs(authorization: str = Header(None)):
    u = current(authorization)
    where, params = _run_scope(u)
    return db.query(f"SELECT r.*, (SELECT COUNT(*) FROM audit a WHERE a.run_id = r.run_id) AS events, "
                    "(SELECT COUNT(*) FROM audit a WHERE a.run_id = r.run_id AND a.kind = 'agent' AND "
                    "a.action = 'called') AS agents FROM runs r "
                    f"WHERE {where} ORDER BY r.started_at DESC LIMIT 40", params)


@app.post("/api/admin/tools/{name}")
def admin_tool(name: str, body: dict = Body({}), authorization: str = Header(None)):
    u = admin(authorization)
    return connector.call(name, body, actor=f"{u['name']} (admin console)")


@app.get("/api/admin/audit")
def admin_audit(kind: str = "", authorization: str = Header(None)):
    admin(authorization)
    if kind:
        return db.query("SELECT * FROM audit WHERE kind = ? ORDER BY id DESC LIMIT 300", (kind,))
    return db.query("SELECT * FROM audit ORDER BY id DESC LIMIT 300")


@app.get("/api/admin/health")
def admin_health(authorization: str = Header(None)):
    admin(authorization)
    with gateway.run("Check system health", channel="web", actor="Portal Admin"):
        agent = OpsAgent()
        signals = agent.observe()
        return {"signals": signals, "diagnosis": agent.diagnose(signals)}


@app.post("/api/admin/health/fix")
def admin_fix(body: dict = Body(...), authorization: str = Header(None)):
    u = require(current(authorization), "ops_apply")
    return OpsAgent().apply(body.get("action", ""), u)


@app.get("/api/admin/safety")
def admin_safety(authorization: str = Header(None)):
    admin(authorization)
    res = evals.run()
    audit("system", "Eval harness", "evals_run", {"passed": sum(r["passed"] for r in res), "total": len(res)})
    return {"evals": res, "risks": RISK_REGISTER, "permissions": PERMISSIONS}


@app.post("/api/admin/sweep")
def admin_sweep(authorization: str = Header(None)):
    admin(authorization)
    submit(sweep)
    return {"ok": True}


@app.post("/api/admin/reset")
def admin_reset(authorization: str = Header(None)):
    require(current(authorization), "reset_demo")
    db.init_db(reset=True)
    for p in RESUME_DIR.glob("*"):
        p.unlink(missing_ok=True)
    return {"ok": True}


# ================================================================== React build

if (config.FRONTEND_DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = config.FRONTEND_DIST / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(config.FRONTEND_DIST / "index.html")
