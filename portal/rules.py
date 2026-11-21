"""Eligibility rules engine (deterministic, versioned, rollback-able).

Rules live in the `rules` table so the Policy Agent can publish new ones and
coordinators can roll them back."""

from __future__ import annotations

import operator

from . import db

_OPS = {">=": operator.ge, "<=": operator.le, ">": operator.gt, "<": operator.lt,
        "==": operator.eq}
FIELDS = {"cgpa": "CGPA", "attendance_pct": "Attendance %", "active_backlogs": "Active backlogs",
          "semester": "Semester", "department": "Branch"}


def active_rules() -> list[dict]:
    return db.query("SELECT * FROM rules WHERE active = 1 ORDER BY id")


def all_rules() -> list[dict]:
    return db.query("SELECT * FROM rules ORDER BY rule_key, version")


def check(rule: dict, student: dict, opp: dict | None) -> dict:
    field = rule["field"]
    label = FIELDS.get(field, field)
    actual = student.get(field)
    if rule["scope"] == "institution":
        required = rule["value"]
    else:
        required = (opp or {}).get(rule["posting_field"])
    base = {"rule": rule["rule_key"], "name": rule["name"], "scope": rule["scope"],
            "version": rule.get("version", "draft"), "required": required, "actual": actual}
    if required in (None, "", []):
        return {**base, "status": "NOT_STATED", "message": f"{label}: not stated by employer"}
    if actual in (None, ""):
        return {**base, "status": "FAIL", "message": f"{label} missing: add it to your profile"}
    fmt = lambda v: f"{float(v):g}" if isinstance(v, (int, float)) else str(v)  # noqa: E731
    if rule["op"] == "in":
        ok = actual in required
        msg = (f"Branch {actual} is eligible" if ok else
               f"Branch shortfall: {actual} is not in {', '.join(required)}")
    else:
        ok = _OPS[rule["op"]](float(actual), float(required))
        if ok:
            msg = f"{label} {fmt(actual)} meets {rule['op']} {fmt(required)}"
        else:
            gap = round(float(actual) - float(required), 2)
            msg = f"{label} shortfall: you have {fmt(actual)}, required {rule['op']} {fmt(required)} ({gap:+g})"
    return {**base, "status": "PASS" if ok else "FAIL", "message": msg}


def evaluate(student: dict, opp: dict | None, rules: list[dict] | None = None) -> list[dict]:
    return [check(r, student, opp) for r in (rules if rules is not None else active_rules())]


def release(rule: dict, created_by: str) -> dict:
    """Release a new rule version; older versions of the same key are deactivated."""
    prev = db.one("SELECT MAX(version) AS v FROM rules WHERE rule_key = ?", (rule["rule_key"],))
    version = (prev["v"] or 0) + 1
    db.execute("UPDATE rules SET active = 0 WHERE rule_key = ?", (rule["rule_key"],))
    db.insert("rules", {**rule, "active": 1, "version": version, "created_by": created_by,
                        "created_at": db.now()})
    return db.one("SELECT * FROM rules WHERE rule_key = ? AND version = ?",
                  (rule["rule_key"], version))


def rollback(rule_key: str) -> dict:
    """Deactivate the current version and re-activate the previous one (if any)."""
    versions = db.query("SELECT * FROM rules WHERE rule_key = ? ORDER BY version DESC", (rule_key,))
    if not versions:
        raise ValueError("unknown rule")
    current = next((v for v in versions if v["active"]), None)
    db.execute("UPDATE rules SET active = 0 WHERE rule_key = ?", (rule_key,))
    older = [v for v in versions if current and v["version"] < current["version"]]
    if older:
        db.execute("UPDATE rules SET active = 1 WHERE id = ?", (older[0]["id"],))
        return {"rule_key": rule_key, "active_version": older[0]["version"]}
    return {"rule_key": rule_key, "active_version": None}
