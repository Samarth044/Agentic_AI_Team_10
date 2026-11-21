"""Policy Agent (course concept: agentic SDLC). A coordinator writes an
eligibility rule in plain English; the agent turns it into a tested rule:

requirements -> design -> implement -> test -> impact preview -> human publish -> monitor
"""

from __future__ import annotations

import re

from .. import db, rules
from ..guardrails import audit
from ..runtime import Agent, step

_FIELD_WORDS = {"cgpa": "cgpa", "gpa": "cgpa", "attendance": "attendance_pct",
                "backlog": "active_backlogs", "semester": "semester", "sem ": "semester"}
_OP_WORDS = [(r"at least|minimum|min\.?|>=|not less than|or more|or above", ">="),
             (r"at most|maximum|max\.?|<=|not more than|or less|or fewer|no more than", "<="),
             (r"more than|above|greater than|>", ">"), (r"less than|below|fewer than|<", "<")]
LIMITS = {"cgpa": (0, 10), "attendance_pct": (0, 100), "active_backlogs": (0, 20), "semester": (1, 8)}


def parse_requirement(text: str) -> dict | None:
    t = text.lower() + " "
    field = next((f for w, f in _FIELD_WORDS.items() if w in t), None)
    num = re.search(r"(\d+(?:\.\d+)?)", t)
    op = next((o for pat, o in _OP_WORDS if re.search(pat, t)), None)
    if not (field and num):
        return None
    return {"field": field, "op": op or ("<=" if field == "active_backlogs" else ">="),
            "value": float(num.group(1))}


def validate(spec: dict) -> list[str]:
    errs = []
    if spec.get("field") not in LIMITS:
        errs.append("field must be cgpa, attendance_pct, active_backlogs or semester")
    if spec.get("op") not in (">=", "<=", ">", "<"):
        errs.append("operator must be one of >= <= > <")
    try:
        v = float(spec.get("value"))
        lo, hi = LIMITS.get(spec.get("field"), (0, 100))
        if not lo <= v <= hi:
            errs.append(f"value {v:g} is outside {lo}-{hi}")
    except (TypeError, ValueError):
        errs.append("value must be a number")
    return errs


def make_rule(spec: dict) -> dict:
    label = rules.FIELDS.get(spec["field"], spec["field"])
    return {"rule_key": f"policy_{spec['field']}", "scope": "institution", "field": spec["field"],
            "op": spec["op"], "value": float(spec["value"]), "posting_field": None, "spec": spec,
            "name": f"{label} {spec['op']} {float(spec['value']):g} (college policy)"}


def run_tests(rule: dict) -> list[dict]:
    v = rule["value"]
    step = 0.1 if rule["field"] == "cgpa" else 1
    expect = {">=": (True, True, False), ">": (False, True, False),
              "<=": (True, False, True), "<": (False, False, True)}[rule["op"]]
    base = {"cgpa": 8.0, "attendance_pct": 90, "active_backlogs": 0, "semester": 6, "department": "CSE"}
    out = []
    for x, e in zip((v, round(v + step, 2), round(v - step, 2)), expect):
        got = rules.check(rule, {**base, rule["field"]: x}, None)["status"]
        out.append({"case": f"{rules.FIELDS.get(rule['field'])} = {x:g}", "expect": "PASS" if e else "FAIL",
                    "got": got, "passed": (got == "PASS") == e})
    return out


class PolicyAgent(Agent):
    name = "Policy Agent"
    skill = ""
    tools = []
    description = ("Turns an eligibility rule written in plain English into a validated, tested, "
                   "versioned rule that a coordinator publishes (and can roll back).")

    @step
    def propose(self, requirement: str) -> dict:
        stages = []
        story, mode = self.think(
            f"REQUIREMENT: {requirement}\nYou are a business analyst for a college internship portal. "
            'Return {"user_story": "As a ... I want ... so that ...", "acceptance_criteria": ["Given ... when ... then ..."]}',
            lambda: {"user_story": f"As the internship coordinator I want '{requirement}' enforced so "
                                   "that only eligible students get an NOC.",
                     "acceptance_criteria": ["A student exactly at the limit is handled as the operator says",
                                             "A student beyond the limit gets an explicit shortfall"]},
            fast=True)
        stages.append({"stage": "Requirement", "output": story, "mode": mode})
        spec, mode = self.think(
            f"REQUIREMENT: {requirement}\nAllowed fields: cgpa, attendance_pct, active_backlogs, semester. "
            'Allowed operators: >=, <=, >, <. Return {"field": ..., "op": ..., "value": number}',
            lambda: parse_requirement(requirement) or {}, fast=True)
        errs = validate(spec)
        if errs:
            parsed = parse_requirement(requirement)
            if parsed and not validate(parsed):
                spec, errs = parsed, []
        stages.append({"stage": "Design", "output": spec, "errors": errs, "mode": mode})
        if errs:
            return {"ok": False, "stages": stages, "error": "; ".join(errs)}
        rule = make_rule(spec)
        stages.append({"stage": "Implement", "output": rule["name"]})
        tests = run_tests(rule)
        stages.append({"stage": "Test", "output": tests, "passed": all(t["passed"] for t in tests)})
        impact = [{"student": s["name"], "value": s[rule["field"]],
                   "result": rules.check(rule, s, None)["status"]} for s in db.query("SELECT * FROM students")]
        stages.append({"stage": "Impact preview", "output": impact})
        for s in stages:  # SDLC stages, shown in the activity log
            out = s["output"]
            text = (out.get("user_story") if isinstance(out, dict) and "user_story" in out else
                    f"{sum(t['passed'] for t in out)}/{len(out)} tests passed" if s["stage"] == "Test" else
                    f"{len(out)} students previewed" if s["stage"] == "Impact preview" else str(out)[:160])
            audit("loop", self.name, s["stage"].upper(), {"text": text})
        audit("loop", self.name, "HUMAN GATE", {"text": "Waiting for the coordinator to publish the rule"})
        self.log("rule_proposed", {"requirement": requirement, "rule": rule["name"]})
        return {"ok": all(t["passed"] for t in tests), "stages": stages, "spec": spec, "rule": rule["name"]}

    @step
    def publish(self, spec: dict, user: dict) -> dict:
        errs = validate(spec)
        if errs:
            raise ValueError("; ".join(errs))
        rule = make_rule(spec)
        if not all(t["passed"] for t in run_tests(rule)):
            raise ValueError("generated tests failed; publishing blocked")
        released = rules.release(rule, user["name"])
        audit("human", user["name"], "rule_published", {"rule": released["name"], "version": released["version"]})
        return released
