"""Workflow node graph (course concept: agentic node graph).

Each tracked record sits at one node. Agent nodes run on their own;
human nodes wait for the student, coordinator or mentor. The coordinator
uses AGENT_STAGES to decide which agent acts next, and the admin
"Agents & workflow" page draws the same NODES/EDGES."""

from __future__ import annotations

NODES = [
    {"id": "resume", "label": "Resume Agent", "type": "agent"},
    {"id": "discovery", "label": "Discovery & matching", "type": "agent"},
    {"id": "eligibility", "label": "Eligibility check", "type": "agent"},
    {"id": "application", "label": "Application Agent", "type": "agent"},
    {"id": "apply", "label": "Student applies", "type": "human"},
    {"id": "offer", "label": "Interview / offer", "type": "human"},
    {"id": "approval", "label": "Approval Agent", "type": "agent"},
    {"id": "noc", "label": "NOC approval", "type": "human"},
    {"id": "progress", "label": "Progress Agent", "type": "agent"},
    {"id": "evaluation", "label": "Evaluation Agent", "type": "agent"},
    {"id": "grade", "label": "Grade sign-off", "type": "human"},
    {"id": "done", "label": "Graded", "type": "end"},
    {"id": "stop", "label": "Closed", "type": "end"},
]

EDGES = [
    ("resume", "discovery", "skills extracted"),
    ("discovery", "eligibility", "ranked postings"),
    ("eligibility", "application", "student opens an eligible match"),
    ("application", "apply", "cover letter + checklist"),
    ("apply", "offer", "marked applied"),
    ("offer", "stop", "not selected / withdrawn"),
    ("offer", "approval", "offer recorded"),
    ("approval", "noc", "checks + recommendation"),
    ("noc", "offer", "changes requested"),
    ("noc", "stop", "rejected"),
    ("noc", "progress", "NOC issued, mentor assigned"),
    ("progress", "evaluation", "report + mentor rating"),
    ("evaluation", "grade", "draft grade"),
    ("grade", "evaluation", "changes requested"),
    ("grade", "done", "approved"),
]

STAGES = {
    "SAVED": ("Preparing application", "application"),
    "APPLIED": ("Applied", "offer"),
    "INTERVIEW": ("Interviewing", "offer"),
    "OFFERED": ("Offer received", "approval"),
    "NOC_PENDING": ("NOC pending", "noc"),
    "NOC_CHANGES": ("NOC: changes requested", "offer"),
    "ONGOING": ("Internship ongoing", "progress"),
    "COMPLETED": ("Report submitted", "evaluation"),
    "GRADE_PENDING": ("Grade awaiting sign-off", "grade"),
    "GRADE_CHANGES": ("Re-evaluation", "evaluation"),
    "GRADED": ("Graded", "done"),
    "NOT_SELECTED": ("Not selected", "stop"),
    "WITHDRAWN": ("Withdrawn", "stop"),
    "NOC_REJECTED": ("NOC rejected", "stop"),
}

# stages where an agent (not a human) acts next
AGENT_STAGES = {"OFFERED": "approval", "COMPLETED": "evaluation", "GRADE_CHANGES": "evaluation"}

JOURNEY = ["SAVED", "APPLIED", "INTERVIEW", "OFFERED", "NOC_PENDING", "ONGOING", "COMPLETED",
           "GRADE_PENDING", "GRADED"]


def graph() -> dict:
    return {"nodes": NODES, "edges": [{"from": a, "to": b, "label": l} for a, b, l in EDGES],
            "stages": {k: {"label": v[0], "node": v[1]} for k, v in STAGES.items()},
            "journey": JOURNEY}
