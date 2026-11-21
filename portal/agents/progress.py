"""Progress Tracking Agent: milestone plan, hour and missing-week
shortfalls (rules), CO mapping and a short narrative (LLM).
Health status is decided by Python rules, never by an LLM guess."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta

from .. import db
from ..config import COURSE_OUTCOMES, WEEKLY_HOURS_TARGET
from ..guardrails import mask_text
from ..notify import notify, notify_student
from ..runtime import Agent, step

_CO_KEYWORDS = {
    "CO1": ["model", "algorithm", "design", "solve", "implement", "build", "built", "analysis",
            "fea", "debug", "fix", "optimi"],
    "CO2": ["python", "react", "docker", "git", "sql", "ansys", "solidworks", "aws", "tool", "api",
            "esp32", "matlab"],
    "CO3": ["report", "document", "presentation", "present", "demo", "wiki", "readme", "slides"],
    "CO4": ["team", "meeting", "standup", "review", "pair", "client", "mentor"],
}


def logs_for(record_id: str) -> list[dict]:
    return db.query("SELECT * FROM progress_logs WHERE record_id = ? ORDER BY week", (record_id,))


def heuristic_cos(tasks: str) -> list[str]:
    t = (tasks or "").lower()
    return [co for co, kws in _CO_KEYWORDS.items() if any(k in t for k in kws)] or ["CO1"]


def start_of(offer: dict) -> date | None:
    try:
        return date.fromisoformat(offer.get("start_date") or "")
    except ValueError:
        return None


def expected_weeks(offer: dict, today: date | None = None) -> int:
    weeks = int(offer.get("duration_weeks") or 8)
    start = start_of(offer)
    today = today or date.today()
    if not start or today < start:
        return 0
    return min(weeks, (today - start).days // 7 + 1)


def health(logs: list[dict], offer: dict, today: date | None = None) -> dict:
    exp = expected_weeks(offer, today)
    logged = {l["week"] for l in logs}
    due = max(exp - 1, max(logged | {0}))  # the current week is not overdue yet
    missing = [w for w in range(1, due + 1) if w not in logged]
    shortfalls = [f"Week {l['week']}: {l['hours']:g} hrs logged vs {WEEKLY_HOURS_TARGET} hrs target"
                  for l in logs if l["hours"] < WEEKLY_HOURS_TARGET]
    status = "DELAYED" if len(missing) >= 2 else "AT_RISK" if (missing or shortfalls) else "ON_TRACK"
    return {"status": status, "missing_weeks": missing, "shortfalls": shortfalls,
            "weeks_logged": len(logs), "expected_weeks": exp,
            "duration_weeks": int(offer.get("duration_weeks") or 8),
            "total_hours": sum(l["hours"] for l in logs),
            "verified_logs": sum(1 for l in logs if l["mentor_verified"])}


class ProgressTrackingAgent(Agent):
    name = "Progress Tracking Agent"
    skill = "progress-tracking"
    tools = ["sql_query"]
    description = ("Plans milestones after the NOC, checks weekly hours and missing logs against "
                   "policy, maps work to course outcomes and flags interns who are at risk.")

    @step
    def plan(self, record: dict) -> list[dict]:
        offer = record.get("offer") or {}
        weeks = int(offer.get("duration_weeks") or 8)
        start = start_of(offer) or date.today()
        plan = [("Joining report & work plan", 1), ("Mid-term review with mentor", max(2, weeks // 2)),
                ("Final report & presentation", weeks)]
        ms = [{"name": n, "week": w, "due": (start + timedelta(weeks=w)).isoformat(), "status": "PENDING"}
              for n, w in plan]
        db.update("records", record["id"], {"milestones": ms, "updated_at": db.now()})
        self.log("milestones_planned", {"weeks": weeks}, record["id"])
        return ms

    @step
    def analyze(self, record: dict) -> dict:
        rid = re.sub(r"[^A-Z0-9-]", "", record["id"])
        self.tool("sql_query", {"sql": f"SELECT week, hours FROM progress_logs WHERE record_id = '{rid}'"},
                  record["id"])
        logs = logs_for(record["id"])
        offer = record.get("offer") or {}
        h = health(logs, offer)
        student = db.get_student(record["student_id"])
        entries = [{"week": l["week"], "hours": l["hours"],
                    "tasks": mask_text(l["tasks"], student)[:500],
                    "learnings": mask_text(l.get("learnings") or "", student)[:200]} for l in logs]

        def fallback():
            return {"co_mapping": {str(l["week"]): heuristic_cos(l["tasks"]) for l in logs},
                    "summary": f"{len(logs)} weekly logs, {h['total_hours']:g} hours so far.",
                    "blockers": h["shortfalls"][:3]}

        prev_h = record.get("progress_health") or {}
        if logs and prev_h.get("logs_analyzed") == len(logs):
            # nothing new since the last analysis: re-check the rules only, no model call
            out, mode = {"co_mapping": {str(l["week"]): l["co_mapping"] for l in logs},
                         "summary": prev_h.get("summary", ""), "blockers": prev_h.get("blockers", [])}, prev_h.get("mode")
        elif logs:
            out, mode = self.think(
                "COURSE OUTCOMES: " + json.dumps(COURSE_OUTCOMES) + "\nWEEKLY LOGS:\n" + json.dumps(entries) +
                f"\nRULE-BASED STATUS (final, do not change): {h['status']}\n"
                'Return {"co_mapping": {"<week>": ["CO1", ...]}, "summary": "2-3 sentences", "blockers": ["..."]}',
                fallback, record["id"], fast=True)
        else:
            out, mode = fallback(), "offline"
        co_map = out.get("co_mapping") or {}
        for l in logs:
            db.update("progress_logs", l["id"], {"co_mapping": co_map.get(str(l["week"])) or heuristic_cos(l["tasks"])})
        ms = record.get("milestones") or self.plan(record)
        logged = {l["week"] for l in logs}
        for m in ms:
            if m["name"].startswith("Final"):
                m["status"] = "DONE" if (record.get("final_report") or {}).get("summary") else "PENDING"
            else:
                m["status"] = "DONE" if any(w >= m["week"] for w in logged) else "PENDING"
        h.update({"summary": out.get("summary", ""), "blockers": out.get("blockers", []), "mode": mode,
                  "analyzed_at": db.now(), "logs_analyzed": len(logs)})
        prev = (record.get("progress_health") or {}).get("status")
        db.update("records", record["id"], {"progress_health": h, "milestones": ms, "updated_at": db.now()})
        if h["status"] != "ON_TRACK" and h["status"] != prev:
            opp = db.get_opportunity(record["opportunity_id"])
            msg = (f"Internship at {opp['company']} is {h['status'].replace('_', ' ').lower()}: "
                   + "; ".join((h["missing_weeks"] and [f"missing weeks {h['missing_weeks']}"] or []) + h["shortfalls"][:1]))
            notify_student(record["student_id"], msg, f"#/records/{record['id']}")
            notify(record.get("mentor_id"), f"{student['name']}: {msg}", f"#/records/{record['id']}")
        self.log("progress_analyzed", {"status": h["status"], "missing": h["missing_weeks"]}, record["id"])
        return h
