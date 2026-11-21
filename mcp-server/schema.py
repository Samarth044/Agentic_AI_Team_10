"""Normalized data models shared by every job-source adapter and Worklet 10 agent.

COURSE CONCEPT (MCP / NxM problem): each job board has its own response
shape. Adapters normalize everything into this single Job / InternshipOpportunity
model, so the agents integrate with ONE schema instead of N board formats x M consumers.
"""

from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone

from pydantic import BaseModel, Field

EMPLOYMENT_TYPES = ("full-time", "part-time", "internship", "contract", "unknown")
REMOTE_TYPES = ("onsite", "hybrid", "remote", "unknown")


class Job(BaseModel):
    """One job or internship posting, normalized across all sources."""

    id: str
    title: str
    company: str
    employment_type: str = "unknown"
    location: str = ""
    remote: str = "unknown"
    industry: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    description: str = ""
    url: str
    source: str
    publisher: str | None = None
    posted_at: datetime | None = None

    # --- Worklet 10: Internship & Academic Eligibility Extensions ---
    # All fields have safe defaults so existing 11 board adapters work untouched.
    min_cgpa: float | None = None
    max_active_backlogs: int | None = None
    eligible_branches: list[str] = Field(default_factory=list)
    min_semester: int | None = None
    internship_duration_weeks: int | None = None
    stipend_inr: str | None = None
    eligibility_raw_text: str = ""
    freshness_status: str = "verified"  # "verified", "unverified_external", "source_unavailable"
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InternshipOpportunity(Job):
    """Explicit Worklet 10 InternshipOpportunity record alias/subclass
    preserving full compatibility with Job while exposing internship helpers."""

    opportunity_type: str = "internship"


class SearchQuery(BaseModel):
    """What the agent asks the MCP server for, built from profile prefs."""

    keywords: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    remote_only: bool = False
    limit_per_source: int = 25
    page: int = 1


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_INTERNSHIP_RE = re.compile(
    r"\bintern(?:ship)?s?\b|\bco[-\s]?ops?\b|\btrainee\b|\bapprentice(?:ship)?\b",
    re.IGNORECASE,
)

# Regex patterns for deterministic extraction of academic eligibility criteria
_CGPA_RE = re.compile(
    r"(?:cgpa|gpa|cpi)\s*(?:of\s*|>=?|above|minimum|min\.?|at\s+least|:)?\s*(\d+(?:\.\d+)?)\s*(?:/\s*10)?",
    re.IGNORECASE,
)
_GPA_4_SCALE_RE = re.compile(
    r"(\d\.\d+)\s*/\s*4\.0\s*(?:gpa|cgpa)",
    re.IGNORECASE,
)
_NO_BACKLOG_RE = re.compile(
    r"\b(?:no|zero|0)\s+(?:active\s+|current\s+)?(?:backlogs?|arrears?)\b",
    re.IGNORECASE,
)
_MAX_BACKLOG_RE = re.compile(
    r"(?:maximum|max|up\s+to|<=?)\s*(\d+)\s+(?:active\s+)?(?:backlogs?|arrears?)",
    re.IGNORECASE,
)
_SEMESTER_RE = re.compile(
    r"\b([3-8])(?:rd|th)\s+sem(?:ester)?\b|\bsem(?:ester)?\s*([3-8])\b",
    re.IGNORECASE,
)
_WEEKS_DURATION_RE = re.compile(
    r"\b(\d{1,2})\s*(?:to\s*\d{1,2}\s*)?weeks?\b",
    re.IGNORECASE,
)
_MONTHS_DURATION_RE = re.compile(
    r"\b(\d{1,2})\s*(?:to\s*\d{1,2}\s*)?months?\b",
    re.IGNORECASE,
)
_STIPEND_INR_RE = re.compile(
    r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\s*-\s*[\d,]+)?(?:\s*k)?)\s*(?:/\s*(?:month|mo|pm)|per\s+month)?",
    re.IGNORECASE,
)
_STIPEND_USD_RE = re.compile(
    r"\$\s*([\d,]+(?:\s*-\s*[\d,]+)?)\s*(?:/\s*(?:month|mo|hr|hour|yr|year)|per\s+(?:month|hour))?",
    re.IGNORECASE,
)

_BRANCH_KEYWORDS: dict[str, tuple[str, ...]] = {
    "CSE": ("computer science", "cse", "cs", "information science", "ise", "it", "information technology", "software engineering"),
    "AI": ("artificial intelligence", "ai", "machine learning", "aiml", "ai & ml", "data science", "ds"),
    "ECE": ("electronics", "ece", "electrical", "eee", "telecommunication", "robotics"),
    "ME": ("mechanical", "mechatronics"),
    "CE": ("civil",),
}


def strip_html(text: str) -> str:
    """Job boards return HTML descriptions; agents want plain text."""
    text = html.unescape(text or "")
    text = _TAG_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def make_job_id(url: str, title: str = "", company: str = "") -> str:
    """Stable job id: hash of the canonical URL (fallback: title+company)."""
    basis = url.split("?")[0].rstrip("/").lower() or f"{title}|{company}".lower()
    return hashlib.sha1(basis.encode()).hexdigest()[:16]


def dedupe(jobs: list[Job]) -> list[Job]:
    """Merge duplicates across sources: first by id (URL hash), then by a
    normalized (title, company) key — the same role posted on two boards
    collapses to one record. Deterministic code, not LLM judgment."""
    seen_ids: set[str] = set()
    seen_tc: set[tuple[str, str]] = set()
    out: list[Job] = []
    for job in jobs:
        tc = (job.title.strip().lower(), job.company.strip().lower())
        if job.id in seen_ids or tc in seen_tc:
            continue
        seen_ids.add(job.id)
        seen_tc.add(tc)
        out.append(job)
    return out


def guess_employment_type(text: str) -> str:
    """Best-effort employment-type inference from free text."""
    if _INTERNSHIP_RE.search(text or ""):
        return "internship"
    t = (text or "").lower()
    if "part-time" in t or "part time" in t:
        return "part-time"
    if "contract" in t or "freelance" in t:
        return "contract"
    if "full-time" in t or "full time" in t or "full_time" in t:
        return "full-time"
    return "unknown"


def extract_academic_requirements(description: str, title: str = "") -> dict:
    """Deterministically extract institutional & internship eligibility criteria
    (CGPA, backlogs, branches, semester, duration, stipend) from posting text.
    Never fabricates requirements: if not stated by the employer, leaves fields None
    so the Eligibility Verification Agent can distinguish 'not stated by employer'
    from 'student does not meet requirement'."""
    combined = f"{title}\n{description or ''}"
    snippets: list[str] = []

    # 1. Minimum CGPA (normalized to 10-point scale)
    min_cgpa: float | None = None
    m_gpa4 = _GPA_4_SCALE_RE.search(combined)
    if m_gpa4:
        val4 = float(m_gpa4.group(1))
        min_cgpa = round((val4 / 4.0) * 9.5, 2)
        snippets.append(f"GPA: {m_gpa4.group(0)} (~{min_cgpa}/10)")
    else:
        m_cgpa = _CGPA_RE.search(combined)
        if m_cgpa:
            val = float(m_cgpa.group(1))
            if 0 < val <= 4.0 and "4.0" in combined:
                min_cgpa = round((val / 4.0) * 9.5, 2)
            elif 0 < val <= 10.0:
                min_cgpa = val
            if min_cgpa is not None:
                snippets.append(f"Min CGPA: {min_cgpa}")

    # 2. Active Backlogs
    max_backlogs: int | None = None
    if _NO_BACKLOG_RE.search(combined):
        max_backlogs = 0
        snippets.append("Max Backlogs: 0 (No active backlogs)")
    else:
        m_bl = _MAX_BACKLOG_RE.search(combined)
        if m_bl:
            max_backlogs = int(m_bl.group(1))
            snippets.append(f"Max Backlogs: {max_backlogs}")

    # 3. Minimum Semester
    min_semester: int | None = None
    m_sem = _SEMESTER_RE.search(combined)
    if m_sem:
        sem_str = m_sem.group(1) or m_sem.group(2)
        if sem_str:
            min_semester = int(sem_str)
            snippets.append(f"Min Semester: {min_semester}")

    # 4. Eligible Branches
    lower_text = combined.lower()
    branches: list[str] = []
    for code, kw_list in _BRANCH_KEYWORDS.items():
        if any(re.search(rf"\b{re.escape(kw)}\b", lower_text) for kw in kw_list):
            branches.append(code)
    if branches:
        snippets.append(f"Branches: {', '.join(branches)}")

    # 5. Internship Duration (in weeks)
    duration_weeks: int | None = None
    m_wk = _WEEKS_DURATION_RE.search(combined)
    if m_wk:
        w = int(m_wk.group(1))
        if 2 <= w <= 52:
            duration_weeks = w
            snippets.append(f"Duration: {w} weeks")
    if duration_weeks is None:
        m_mo = _MONTHS_DURATION_RE.search(combined)
        if m_mo:
            mo = int(m_mo.group(1))
            if 1 <= mo <= 12:
                duration_weeks = mo * 4
                snippets.append(f"Duration: {mo} months (~{duration_weeks} weeks)")

    # 6. Stipend
    stipend: str | None = None
    m_inr = _STIPEND_INR_RE.search(combined)
    if m_inr:
        stipend = f"₹{m_inr.group(1).strip()}/mo"
    else:
        m_usd = _STIPEND_USD_RE.search(combined)
        if m_usd:
            stipend = f"${m_usd.group(1).strip()}"

    return {
        "min_cgpa": min_cgpa,
        "max_active_backlogs": max_backlogs,
        "eligible_branches": branches,
        "min_semester": min_semester,
        "internship_duration_weeks": duration_weeks,
        "stipend_inr": stipend,
        "eligibility_raw_text": " | ".join(snippets) if snippets else "Standard employer criteria (no explicit academic cutoff stated)",
    }


def enrich_job_for_internship(job: Job) -> Job:
    """Populate Worklet 10 academic/internship fields on a Job instance
    without overwriting values already set by an adapter or coordinator override."""
    extracted = extract_academic_requirements(job.description, job.title)
    updates: dict = {}
    for k, v in extracted.items():
        current = getattr(job, k, None)
        if current in (None, "", []) and v not in (None, "", []):
            updates[k] = v
    if job.salary_min and not job.stipend_inr and not updates.get("stipend_inr"):
        if job.salary_max and job.salary_max != job.salary_min:
            updates["stipend_inr"] = f"${job.salary_min:,} - ${job.salary_max:,}"
        else:
            updates["stipend_inr"] = f"${job.salary_min:,}"
    if updates:
        return job.model_copy(update=updates)
    return job