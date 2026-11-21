"""Approval Agent: checks an offer before the NOC and a draft grade before
publication, writes a recommendation and routes it to the student's
coordinator. Only that named human can decide. Approval events are
append-only rows in `approvals`."""

from __future__ import annotations

import json
import re
from datetime import date

from .. import db
from ..guardrails import Forbidden, audit
from ..notify import notify, notify_student
from ..runtime import Agent, step
from . import set_stage
from .eligibility import EligibilityVerificationAgent

GATES = {
    "NOC": {"stage": "NOC_PENDING", "label": "NOC approval",
            "next": {"APPROVED": "ONGOING", "CHANGES_REQUESTED": "NOC_CHANGES",
                     "REJECTED": "NOC_REJECTED"}},
    "GRADE": {"stage": "GRADE_PENDING", "label": "Grade sign-off",
              "next": {"APPROVED": "GRADED", "CHANGES_REQUESTED": "GRADE_CHANGES"}},
}


def trail(record_id: str) -> list[dict]:
    return db.query("SELECT * FROM approvals WHERE record_id = ? ORDER BY id", (record_id,))


def _int(v) -> int | None:
    m = re.search(r"\d+", str(v or ""))
    return int(m.group(0)) if m else None


class ApprovalAgent(Agent):
    name = "Approval Agent"
    skill = "approval"
    tools = ["read_document"]
    description = ("Checks offers before the NOC and draft grades before publication, writes a "
                   "recommendation, drafts the NOC and routes each case to the named coordinator.")

    def _route(self, record: dict, gate: str, issues: list[str], context: dict) -> str:
        student = db.get_student(record["student_id"])
        faculty = db.get_user(student["faculty_id"])
        out, mode = self.think(
            f"GATE: {GATES[gate]['label']}\nCHECK RESULTS (deterministic): {json.dumps(issues)}\n"
            f"CONTEXT: {json.dumps(context, default=str)[:2500]}\n"
            'Return {"recommendation": "APPROVE" or "REVIEW_ISSUES", "summary": "2 sentences"}',
            lambda: {"recommendation": "REVIEW_ISSUES" if issues else "APPROVE",
                     "summary": "; ".join(issues) if issues else "All checks passed."},
            record["id"], fast=True)
        rec = "REVIEW_ISSUES" if issues else out.get("recommendation", "APPROVE")  # issues can't be hidden
        text = f"{rec}: {out.get('summary', '')}"
        db.insert("approvals", {"record_id": record["id"], "gate": gate, "decision": "PENDING",
                                "actor_id": "agent", "actor_name": self.name, "actor_role": "agent",
                                "agent_recommendation": text,
                                "remarks": f"Routed to {faculty['name']}", "ts": db.now()})
        set_stage(record["id"], GATES[gate]["stage"])
        opp = db.get_opportunity(record["opportunity_id"])
        notify(faculty["id"], f"{GATES[gate]['label']} needed: {student['name']} at {opp['company']}",
               f"#/records/{record['id']}")
        self.log("routed", {"gate": gate, "to": faculty["name"], "issues": issues, "mode": mode},
                 record["id"])
        return text

    # ------------------------------------------------------------ NOC
    @step
    def review_offer(self, record: dict) -> str:
        student = db.get_student(record["student_id"])
        opp = db.get_opportunity(record["opportunity_id"])
        offer = record.get("offer") or {}
        issues = []
        elig = EligibilityVerificationAgent().check_many(student, [opp])["results"][opp["id"]]
        issues += [f"Eligibility: {s}" for s in elig["shortfalls"]]
        if not offer.get("offer_ref"):
            issues.append("No offer letter reference")
        try:
            start = date.fromisoformat(offer.get("start_date") or "")
            if (date.today() - start).days > 30:
                issues.append(f"Start date {start} is more than 30 days in the past")
        except ValueError:
            issues.append("Offer has no valid start date")
        if opp.get("duration_weeks") and _int(offer.get("duration_weeks")) != opp["duration_weeks"]:
            issues.append(f"Offer is {offer.get('duration_weeks')} weeks; posting said "
                          f"{opp['duration_weeks']} weeks")
        if re.search(r"(?i)fee|deposit", str(offer.get("stipend", ""))):
            issues.append("Offer mentions a fee or deposit (not allowed by college policy)")
        self.tool("read_document", {"name": "noc_template.md"}, record["id"])
        return self._route(record, "NOC", issues, {"offer": offer, "posting": {
            "title": opp["title"], "company": opp["company"], "stipend": opp["stipend"],
            "duration_weeks": opp["duration_weeks"]}, "eligibility": elig["summary"]})

    def noc_letter(self, record: dict, coordinator: dict, mentor: dict | None) -> str:
        student = db.get_student(record["student_id"])
        opp = db.get_opportunity(record["opportunity_id"])
        offer = record.get("offer") or {}
        tmpl = self.tool("read_document", {"name": "noc_template.md"}, record["id"]).get("content", "")
        return tmpl.format(noc_ref=f"NOC/{date.today().year}/{record['id']}",
                           date=date.today().strftime("%d %b %Y"), name=student["name"],
                           usn=student["usn"], semester=student["semester"],
                           department=student["department"], role=opp["title"],
                           company=opp["company"], start_date=offer.get("start_date", "-"),
                           weeks=offer.get("duration_weeks", "-"),
                           mentor=mentor["name"] if mentor else "to be assigned",
                           justification="", coordinator=coordinator["name"])

    # ------------------------------------------------------------ grade
    @step
    def review_grade(self, record: dict, evaluation: dict) -> str:
        issues = []
        h = record.get("progress_health") or {}
        if h.get("missing_weeks"):
            issues.append(f"Missing weekly logs: weeks {h['missing_weeks']}")
        if h.get("weeks_logged") and h.get("verified_logs", 0) < h["weeks_logged"]:
            issues.append(f"Only {h.get('verified_logs', 0)} of {h['weeks_logged']} logs verified by mentor")
        return self._route(record, "GRADE", issues, {"total": evaluation["total"],
                                                     "grade": evaluation["grade"],
                                                     "scores": evaluation["scores"]})

    # ------------------------------------------------------------ human decision
    @step
    def decide(self, record: dict, gate: str, decision: str, user: dict, remarks: str,
               mentor_id: str | None = None) -> str:
        student = db.get_student(record["student_id"])
        if user["role"] != "faculty" or user["id"] != student["faculty_id"]:
            audit("guardrail", user["name"], "gate_denied", {"gate": gate}, record["id"])
            raise Forbidden("Only the student's internship coordinator can decide this")
        g = GATES.get(gate)
        if not g or record["stage"] != g["stage"]:
            raise ValueError(f"This record is not waiting for {gate}")
        if decision not in g["next"]:
            raise ValueError(f"{decision} is not allowed here")
        if decision != "APPROVED" and not (remarks or "").strip():
            raise ValueError("Please add remarks when rejecting or requesting changes")
        extra = {}
        opp = db.get_opportunity(record["opportunity_id"])
        if gate == "NOC" and decision == "APPROVED":
            mentor = db.get_user(mentor_id or "")
            if not mentor or mentor["role"] != "mentor":
                raise ValueError("Choose the industry mentor for this intern")
            extra = {"mentor_id": mentor["id"],
                     "noc": {"ref": f"NOC/{date.today().year}/{record['id']}",
                             "issued_by": user["name"], "issued_at": db.now(),
                             "letter": self.noc_letter(record, user, mentor)}}
            notify(mentor["id"], f"New intern assigned: {student['name']} ({opp['title']})",
                   f"#/records/{record['id']}")
        pending = [a for a in trail(record["id"]) if a["gate"] == gate and a["decision"] == "PENDING"]
        db.insert("approvals", {"record_id": record["id"], "gate": gate, "decision": decision,
                                "actor_id": user["id"], "actor_name": user["name"],
                                "actor_role": user["title"],
                                "agent_recommendation": pending[-1]["agent_recommendation"] if pending else "",
                                "remarks": remarks, "ts": db.now()})
        new_stage = g["next"][decision]
        set_stage(record["id"], new_stage, **extra)
        if gate == "GRADE" and decision == "APPROVED":
            ev = db.one("SELECT id, grade FROM evaluations WHERE record_id = ? ORDER BY version DESC LIMIT 1",
                        (record["id"],))
            db.update("evaluations", ev["id"], {"status": "FINAL"})
        audit("human", user["name"], f"{gate}_{decision}", {"remarks": remarks}, record["id"])
        what = "Your NOC" if gate == "NOC" else "Your final grade"
        verb = {"APPROVED": "was approved" if gate == "NOC" else "is published",
                "REJECTED": "was rejected", "CHANGES_REQUESTED": "needs changes"}[decision]
        notify_student(student["id"], f"{what} for {opp['company']} {verb}"
                       + (f": {remarks}" if remarks else ""), f"#/records/{record['id']}")
        if remarks.strip():
            self.memory.remember(student["id"], "faculty_remark",
                                 f"{g['label']} {decision} for {opp['company']} {opp['title']}: {remarks}")
        return new_stage
