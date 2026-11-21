"""Eligibility Verification Agent: college + employer rules, deterministic.

The LLM is never asked whether a student is eligible, so a posting cannot
talk its way past a cutoff. 'Not stated by employer' is reported
separately from 'student does not meet it'."""

from __future__ import annotations

from .. import db, rules
from ..runtime import Agent, step


class EligibilityVerificationAgent(Agent):
    name = "Eligibility Verification Agent"
    skill = ""
    tools = ["get_student"]
    description = ("Checks attendance, semester, CGPA, backlogs and branch against college policy "
                   "and the employer's criteria with a versioned rules engine; lists every shortfall.")

    @step
    def check_many(self, student: dict, opps: list[dict]) -> dict:
        """One step per student: check every posting, report the outcome."""
        self.tool("get_student", {"student_id": student["id"]})
        rule_set = rules.active_rules()
        out = {o["id"]: self.check(student, o, rule_set) for o in opps}
        ok = sum(r["status"] == "ELIGIBLE" for r in out.values())
        self.log("checked", {"postings": len(out), "eligible": ok, "not_eligible": len(out) - ok,
                             "rules": len(rule_set)})
        return {"eligible": ok, "not_eligible": len(out) - ok, "results": out}

    def check(self, student: dict, opp: dict, rule_set: list[dict] | None = None) -> dict:
        checks = rules.evaluate(student, opp, rule_set)
        fails = [c for c in checks if c["status"] == "FAIL"]
        status = "NOT_ELIGIBLE" if fails else "ELIGIBLE"
        not_stated = [c["name"] for c in checks if c["status"] == "NOT_STATED"]
        if fails:
            summary = "; ".join(c["message"] for c in fails)
        elif not_stated and len(not_stated) == sum(1 for c in checks if c["scope"] == "posting"):
            summary = "Meets college policy. The employer states no academic cutoffs."
        else:
            summary = "Meets college policy and every criterion the employer states."
        return {"status": status, "checks": checks, "shortfalls": [c["message"] for c in fails],
                "not_stated": not_stated, "summary": summary, "checked_at": db.now()}

    @step
    def recheck_all(self, student_id: str | None = None) -> int:
        """Called when a rule is published / rolled back, or a student's academic details change."""
        n = 0
        rule_set = rules.active_rules()
        sql, params = "SELECT id, student_id, opportunity_id FROM matches", ()
        if student_id:
            sql, params = sql + " WHERE student_id = ?", (student_id,)
        for m in db.query(sql, params):
            s, o = db.get_student(m["student_id"]), db.get_opportunity(m["opportunity_id"])
            if s and o:
                db.update("matches", m["id"], {"eligibility": self.check(s, o, rule_set)})
                n += 1
        self.log("eligibility_rechecked", {"matches": n})
        return n
