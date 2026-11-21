"""Evaluation harness (course concept 12: responsible autonomy). Golden cases the
agents and guardrails must pass, run against the live rules so a bad rule
change shows up here. Uses synthetic test profiles, no AI calls."""

from __future__ import annotations

from . import db, taxonomy
from .agents.discovery import OpportunityDiscoveryAgent
from .agents.eligibility import EligibilityVerificationAgent
from .agents.evaluation import compute
from .agents.resume import heuristic_profile
from .guardrails import Forbidden, mask_student, mask_text, posting_flags, require

STRONG_CSE = {"id": "eval-1", "name": "Test Student", "department": "CSE", "semester": 6, "cgpa": 8.6,
              "active_backlogs": 0, "attendance_pct": 88}
WEAK_ECE = {"id": "eval-2", "name": "Test Student", "department": "ECE", "semester": 6, "cgpa": 6.9,
            "active_backlogs": 1, "attendance_pct": 78}


def _posting(pid: str) -> dict:
    return next(p for p in db.seed_postings() if p["id"] == pid)


def _status(student: dict, pid: str) -> str:
    return EligibilityVerificationAgent().check(student, _posting(pid))["status"]


def _dedupe() -> str:
    _, outcome = OpportunityDiscoveryAgent().store_posting({**_posting("cp-109"), "source": "campus"})
    return outcome


def _perm() -> str:
    try:
        require(db.get_user("u-men-1"), "decide_noc")
        return "allowed"
    except Forbidden:
        return "denied"


def _pii() -> bool:
    s = db.get_student("s-1")
    return "Ananya" in mask_text("Ananya Rao, +91 98450 12345", s) or "98450" in str(mask_student(s))


CASES = [
    ("Eligible: CSE, CGPA 8.6 for Infosys ML", lambda: _status(STRONG_CSE, "cp-101"), "ELIGIBLE"),
    ("CGPA shortfall: 6.9 for Bosch (needs 7.0)", lambda: _status(WEAK_ECE, "cp-103"), "NOT_ELIGIBLE"),
    ("Branch shortfall: CSE for Ather (ME only)", lambda: _status(STRONG_CSE, "cp-105"), "NOT_ELIGIBLE"),
    ("No employer cutoffs: AgriSense accepts any eligible student", lambda: _status(WEAK_ECE, "cp-104"), "ELIGIBLE"),
    ("Scam + prompt-injection posting is blocked", lambda: sorted(posting_flags(_posting("cp-108"))),
     ["PROMPT_INJECTION", "SUSPECTED_SCAM"]),
    ("Duplicate cross-posting is collapsed", _dedupe, "duplicate"),
    ("Resume parser finds core skills", lambda: all(s in taxonomy.find_skills("Skills: Python, React, SQL, Git")
                                                    for s in ("python", "react", "sql", "git")), True),
    ("Resume parser finds projects", lambda: len(heuristic_profile(
        "PROJECTS\nCrop Classifier (Python)\n- Built a CNN\nAttendance App\n- React app")["projects"]), 2),
    ("Grade maths: tech 8, report 7, mentor 9, full logs", lambda: compute(
        {"technical": 8, "report": 7}, 9, {"weeks_logged": 8, "total_hours": 240}, 8)["grade"], "A"),
    ("Name and phone masked before any AI call", _pii, False),
    ("Mentor cannot approve an NOC", _perm, "denied"),
]


def run() -> list[dict]:
    out = []
    for name, fn, expected in CASES:
        try:
            got = fn()
        except Exception as e:  # noqa: BLE001
            got = f"error: {e}"
        out.append({"case": name, "expected": expected, "got": got, "passed": got == expected})
    return out
