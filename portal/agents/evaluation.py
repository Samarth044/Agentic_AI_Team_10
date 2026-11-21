"""Evaluation Agent: rubric-based draft grade. The LLM only rates the two
qualitative parts (0-10); marks, total and letter grade are Python.
The grade stays a draft until the coordinator signs it off."""

from __future__ import annotations

import json

from .. import db
from ..config import COURSE_OUTCOMES, GRADE_BANDS, RUBRIC, WEEKLY_HOURS_TARGET
from ..guardrails import mask_text
from ..runtime import Agent, step
from .progress import health, logs_for


def letter(total: float) -> str:
    return next(g for cut, g in GRADE_BANDS if total >= cut)


def weekly_marks(h: dict, duration: int) -> float:
    coverage = min(1.0, h["weeks_logged"] / max(1, duration))
    hours = min(1.0, h["total_hours"] / max(1, WEEKLY_HOURS_TARGET * duration))
    return round(15 * coverage + 10 * hours, 1)


def compute(ratings: dict, mentor_score: float, h: dict, duration: int) -> dict:
    r = lambda k: max(0.0, min(10.0, float(ratings.get(k) or 0)))  # noqa: E731
    scores = {"weekly_consistency": weekly_marks(h, duration),
              "technical_depth": round(3.0 * r("technical"), 1),
              "mentor_evaluation": round(2.5 * max(0.0, min(10.0, float(mentor_score))), 1),
              "report_presentation": round(2.0 * r("report"), 1)}
    total = round(sum(scores.values()), 1)
    return {"scores": scores, "total": total, "grade": letter(total)}


class EvaluationAgent(Agent):
    name = "Evaluation Agent"
    skill = "internship-evaluation"
    tools = ["read_document"]
    description = ("Drafts the final internship grade on the 100-mark rubric from weekly logs, the "
                   "mentor rating and the final report, then sends it for coordinator sign-off.")

    def ready(self, record: dict) -> str | None:
        fr = record.get("final_report") or {}
        if not fr.get("summary"):
            return "waiting for the final report"
        if fr.get("mentor_score") is None:
            return "waiting for the mentor's rating"
        return None

    @step
    def run(self, record: dict, remarks: str = "") -> dict | None:
        waiting = self.ready(record)
        if waiting:
            self.log("waiting", {"reason": waiting}, record["id"])
            return None
        report = record["final_report"]
        student = db.get_student(record["student_id"])
        offer = record.get("offer") or {}
        duration = int(offer.get("duration_weeks") or 8)
        logs = logs_for(record["id"])
        h = health(logs, offer)
        self.tool("read_document", {"name": "internship_policy.md"}, record["id"])
        evidence = [{"week": l["week"], "hours": l["hours"], "tasks": mask_text(l["tasks"], student)[:300],
                     "artifacts": l["artifacts"], "mentor_remarks": l["mentor_remarks"],
                     "cos": l["co_mapping"]} for l in logs]

        def fallback():
            arts = sum(1 for l in logs if (l["artifacts"] or "").strip())
            return {"technical": min(10, 4 + arts + len(logs) // 3),
                    "report": min(10, 4 + len(report.get("summary", "")) // 150),
                    "justification": f"{len(logs)} weekly logs with {arts} artifact links; mentor rated "
                                     f"{report['mentor_score']}/10.",
                    "co_attainment": {co: "Met" for co in COURSE_OUTCOMES}}

        out, mode = self.think(
            "RUBRIC: " + json.dumps(RUBRIC) + "\nCOURSE OUTCOMES: " + json.dumps(COURSE_OUTCOMES) +
            "\nWEEKLY EVIDENCE:\n" + json.dumps(evidence) + "\nFINAL REPORT SUMMARY:\n" +
            mask_text(report.get("summary", ""), student)[:2500] +
            f"\nMENTOR RATING: {report['mentor_score']}/10, feedback: {report.get('mentor_feedback', '')}\n"
            f"COORDINATOR REMARKS TO ADDRESS: {remarks or 'none'}\n"
            'Return {"technical": 0-10, "report": 0-10, "justification": "3-4 sentences", '
            '"co_attainment": {"CO1": "Met|Partially met|Not met", ...}}', fallback, record["id"])
        result = compute(out, report["mentor_score"], h, duration)
        prev = db.one("SELECT MAX(version) AS v FROM evaluations WHERE record_id = ?", (record["id"],))
        ev = {"record_id": record["id"], "version": (prev["v"] or 0) + 1, "scores": result["scores"],
              "total": result["total"], "grade": result["grade"],
              "justification": json.dumps({"text": out.get("justification", ""),
                                           "co_attainment": out.get("co_attainment", {}),
                                           "ratings": {"technical": out.get("technical"),
                                                       "report": out.get("report")},
                                           "remarks_addressed": remarks, "mode": mode}),
              "status": "DRAFT", "mentor_score": report["mentor_score"], "created_at": db.now()}
        db.insert("evaluations", ev)
        self.log("grade_drafted", {"total": result["total"], "grade": result["grade"],
                                   "version": ev["version"]}, record["id"])
        return ev
