"""Central configuration for the Internship Application & Tracking Portal (Worklet 10)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=True)  # .env wins over stale machine-level variables

DATA_DIR = ROOT / "data"
DOCS_DIR = DATA_DIR / "docs"          # sandbox for the file-reader tool
RESUME_DIR = DATA_DIR / "resumes"
DB_PATH = Path(os.getenv("PORTAL_DB", DATA_DIR / "portal.db"))
SKILLS_DIR = ROOT / "skills"
FRONTEND_DIST = ROOT / "frontend" / "dist"

# Groq retired llama-3.3-70b / llama-3.1-8b on 2026-08-16; gpt-oss are the
# recommended replacements. Both are overridable from .env.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
MODEL_PRIMARY = os.getenv("GROQ_MODEL_PRIMARY", "openai/gpt-oss-120b")
MODEL_FAST = os.getenv("GROQ_MODEL_FAST", "openai/gpt-oss-20b")

# Background scheduler (autonomous sweeps). Tests switch it off.
SCHEDULER_ENABLED = os.getenv("PORTAL_SCHEDULER", "1") == "1"
SCHEDULER_MINUTES = int(os.getenv("PORTAL_SCHEDULER_MINUTES", "30"))
BOARD_SYNC_HOURS = 24

# Institution policy (confirm with faculty; one place to change).
WEEKLY_HOURS_TARGET = 30
MIN_MATCH_TO_SHOW = 35           # matches below this are hidden from the student
NOTIFY_MATCH = 70                # notify a student about new postings at/above this

COURSE_OUTCOMES = {
    "CO1": "Apply engineering knowledge to solve real industry problems",
    "CO2": "Use modern tools and technologies used in industry",
    "CO3": "Communicate and document work professionally",
    "CO4": "Work in teams and follow professional ethics",
}

# Evaluation rubric (100 marks). Weights must be confirmed by the faculty.
RUBRIC = {
    "weekly_consistency": {"label": "Weekly progress & consistency", "max": 25},
    "technical_depth": {"label": "Technical depth & deliverables", "max": 30},
    "mentor_evaluation": {"label": "Industry mentor evaluation", "max": 25},
    "report_presentation": {"label": "Final report & presentation", "max": 20},
}
GRADE_BANDS = [(90, "S"), (80, "A"), (70, "B"), (60, "C"), (50, "D"), (0, "F")]

# Role-based permissions, checked by the API on every action.
PERMISSIONS = {
    "student": ["edit_profile", "apply", "track", "submit_log", "submit_report", "assistant"],
    "faculty": ["decide_noc", "decide_grade", "post_opportunity", "manage_rules", "view_students",
                "sync_boards"],
    "mentor": ["verify_log", "mentor_rating"],
    "admin": ["view_students", "post_opportunity", "manage_rules", "sync_boards", "ops_apply",
              "reset_demo", "view_system"],
}
