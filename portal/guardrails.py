"""Safety & governance: audit log, permission checks, PII masking and
untrusted-posting checks. All deterministic Python, so posting or resume
text cannot argue its way past them."""

from __future__ import annotations

import json
import re

from . import context, db
from .config import PERMISSIONS, ROOT

# --------------------------------------------------------------- audit log

AUDIT_FILE = ROOT / "logs" / "portal-audit.jsonl"


def audit(kind: str, actor: str, action: str, detail: dict | None = None,
          record_id: str | None = None, run_id: str | None = None) -> None:
    """Append-only audit log (SQLite table + JSONL file).
    kind: run | loop | agent | llm | tool | memory | human | guardrail | system"""
    safe = {}
    for k, v in (detail or {}).items():
        if isinstance(v, str) and len(v) > 1500:
            v = v[:1500] + "…"
        safe[k] = v
    row = {"ts": db.now(), "run_id": run_id or context.run_id(), "kind": kind, "actor": actor,
           "action": action, "record_id": record_id or "", "detail": safe}
    db.insert("audit", row)
    try:
        AUDIT_FILE.parent.mkdir(exist_ok=True)
        with AUDIT_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
    except OSError:
        pass


# ------------------------------------------------------------- permissions

class Forbidden(Exception):
    pass


def require(user: dict | None, permission: str) -> dict:
    if not user:
        raise Forbidden("Please log in")
    if permission not in PERMISSIONS.get(user["role"], []):
        audit("guardrail", user["name"], "permission_denied",
              {"permission": permission, "role": user["role"]})
        raise Forbidden(f"Your role ({user['role']}) cannot do this")
    return user


# ------------------------------------------------------------- PII masking

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")


def mask_text(text: str, student: dict | None = None) -> str:
    text = text or ""
    if student:
        for key, ph in (("name", "{{STUDENT_NAME}}"), ("usn", "{{STUDENT_USN}}"),
                        ("email", "{{STUDENT_EMAIL}}"), ("phone", "{{STUDENT_PHONE}}")):
            if student.get(key):
                text = re.sub(re.escape(student[key]), ph, text, flags=re.I)
        if student.get("name"):  # also first / last name alone
            for part in student["name"].split():
                if len(part) > 2:
                    text = re.sub(rf"\b{re.escape(part)}\b", "{{STUDENT_NAME}}", text, flags=re.I)
    text = _EMAIL.sub("{{EMAIL}}", text)
    return _PHONE.sub("{{PHONE}}", text)


def mask_student(student: dict) -> dict:
    """Copy of the student that is safe to send to the LLM provider."""
    prof = student.get("resume_profile") or {}
    return {"department": student.get("department"), "semester": student.get("semester"),
            "cgpa": student.get("cgpa"), "skills": student.get("skills") or [],
            "preferred_domains": student.get("preferred_domains"),
            "preferred_locations": student.get("preferred_locations"),
            "open_to_remote": bool(student.get("open_to_remote")),
            "summary": mask_text(prof.get("summary", ""), student),
            "projects": [{"title": p.get("title"), "skills": p.get("skills", [])}
                         for p in prof.get("projects", [])][:6]}


def unmask(text: str, student: dict) -> str:
    for ph, key in (("{{STUDENT_NAME}}", "name"), ("{{STUDENT_USN}}", "usn"),
                    ("{{STUDENT_EMAIL}}", "email"), ("{{STUDENT_PHONE}}", "phone")):
        text = text.replace(ph, student.get(key) or "")
    return text


# ------------------------------------------------ untrusted posting checks

_INJECTION = re.compile(
    r"ignore (all )?(previous|prior) (rules|instructions)|system instruction|"
    r"you are now|disregard .{0,20}instructions|mark every student", re.I)
_SCAM = re.compile(r"registration fee|pay ₹|pay rs|earn money from home|no interview|"
                   r"security deposit|training fee", re.I)


def posting_flags(opp: dict) -> list[str]:
    text = f"{opp.get('title', '')} {opp.get('description', '')} {opp.get('stipend', '')}"
    flags = []
    if _INJECTION.search(text):
        flags.append("PROMPT_INJECTION")
    if _SCAM.search(text):
        flags.append("SUSPECTED_SCAM")
    return flags


def wrap_untrusted(opp: dict) -> str:
    """Posting text goes to the LLM inside tags; every skill says the tag
    contents are data, never instructions."""
    return ("<posting>\n"
            f"Title: {opp['title']}\nCompany: {opp['company']}\n"
            f"Location: {opp.get('location')} ({opp.get('mode')})\n"
            f"Duration: {opp.get('duration_weeks')} weeks, Stipend: {opp.get('stipend')}\n"
            f"Required skills: {', '.join(opp.get('required_skills') or [])}\n"
            f"Description: {(opp.get('description') or '')[:1500]}\n"
            "</posting>")


RISK_REGISTER = [
    {"risk": "An agent approves its own recommendation", "severity": "High",
     "control": "NOC and grade gates accept decisions only from the student's coordinator; agents can only write PENDING events."},
    {"risk": "Prompt injection inside a posting or resume", "severity": "High",
     "control": "Untrusted text is wrapped in tags, injection patterns are flagged, eligibility and marks are Python."},
    {"risk": "Fake or fee-charging internships", "severity": "High",
     "control": "Scam and injection checks block the posting; blocked postings are never shown to students."},
    {"risk": "Student personal data sent to the LLM provider", "severity": "Medium",
     "control": "Name, USN, email and phone are masked before every LLM call and re-inserted locally."},
    {"risk": "Eligibility silently relaxed", "severity": "High",
     "control": "Every failed criterion is shown; only a published, versioned rule change alters the outcome."},
    {"risk": "Wrong grade published", "severity": "High",
     "control": "Marks computed in Python from the rubric; the grade stays a draft until the coordinator signs it off."},
    {"risk": "Bad rule published by the policy agent", "severity": "Medium",
     "control": "Generated tests must pass, a human publishes it, every rule is versioned and can be rolled back."},
    {"risk": "Applications submitted on the student's behalf", "severity": "High",
     "control": "No code path submits to an employer; the student applies on the company site and marks it here."},
]
