"""Demo journey: one click drives the full internship lifecycle through the real API,
so every agent runs for real (about 20 AI calls). The actions a person would
normally take (apply, approve, log a week) are scripted, and every run is
labelled "[Demo]" with channel "demo" so the log never pretends a human clicked."""

from __future__ import annotations

import threading
from datetime import date, timedelta

from . import db
from .guardrails import audit

_lock = threading.Lock()
STATUS = {"state": "idle", "step": "", "done": 0, "total": 0, "error": "", "record_id": None}


def _pick_opportunity(student_id: str) -> dict | None:
    """Best eligible internship the student has not applied to yet. Zoho (cp-102) is
    kept free so it can still be applied to live during the review."""
    for m in db.query("SELECT m.opportunity_id, m.score, m.eligibility FROM matches m JOIN opportunities o ON "
                      "o.id = m.opportunity_id WHERE m.student_id = ? AND o.status = 'open' ORDER BY m.score DESC",
                      (student_id,)):
        if m["eligibility"]["status"] != "ELIGIBLE" or m["opportunity_id"] == "cp-102":
            continue
        if not db.one("SELECT id FROM records WHERE student_id = ? AND opportunity_id = ?",
                      (student_id, m["opportunity_id"])):
            return db.get_opportunity(m["opportunity_id"])
    return None


def run_journey() -> None:
    from fastapi.testclient import TestClient
    from .main import _session, app

    if not _lock.acquire(blocking=False):
        return
    try:
        c = TestClient(app)  # in-process requests; no lifespan, so no second scheduler
        demo = {"X-Demo": "1"}
        S = {**demo, "Authorization": "Bearer " + _session("u-stu-1")}
        F = {**demo, "Authorization": "Bearer " + _session("u-fac-1")}
        M = {**demo, "Authorization": "Bearer " + _session("u-men-1")}
        A = {**demo, "Authorization": "Bearer " + _session("u-adm-1")}

        def ok(r):
            if r.status_code >= 400:
                raise RuntimeError(f"{r.request.method} {r.request.url.path}: {r.json().get('detail', r.text)}")
            return r.json()

        opp = _pick_opportunity("s-1")
        if not opp:
            raise RuntimeError("No eligible internship left for the demo student (reset demo data first)")
        weeks = opp["duration_weeks"] or 8
        start = (date.today() - timedelta(days=21)).isoformat()
        rid = None

        def apply():
            nonlocal rid
            rid = ok(c.post(f"/api/internships/{opp['id']}/apply", headers=S))["record_id"]
            STATUS["record_id"] = rid

        steps = [
            ("Career Assistant: student asks a question",
             lambda: ok(c.post("/api/assistant", headers=S, json={"message": "Which internships fit me best? Remember I prefer Bengaluru."}))),
            ("Expert Panel: 4 reviewers in parallel", lambda: ok(c.post(f"/api/internships/{opp['id']}/panel", headers=S))),
            ("Company Research Agent", lambda: ok(c.post("/api/research", headers=S, json={"company": opp["company"]}))),
            ("Application Processing Agent: student clicks Apply", apply),
            ("Student marks it applied", lambda: ok(c.post(f"/api/records/{rid}/status", headers=S,
                                                          json={"stage": "APPLIED", "applied_on": date.today().isoformat()}))),
            ("Approval Agent: student records the offer", lambda: ok(c.post(f"/api/records/{rid}/offer", headers=S, json={
                "offer_ref": f"OL-{opp['id'].upper()}", "start_date": start, "duration_weeks": weeks, "stipend": opp["stipend"]}))),
            ("Coordinator approves the NOC -> Progress Agent plans", lambda: ok(c.post(f"/api/records/{rid}/decision", headers=F,
                                                                                       json={"gate": "NOC", "decision": "APPROVED", "mentor_id": "u-men-1"}))),
            *[(f"Progress Agent: week {w} log", (lambda w=w: ok(c.post(f"/api/records/{rid}/logs", headers=S, json={
                "week": w, "hours": 32, "tasks": f"Week {w}: built features, wrote tests and reviewed code with my mentor",
                "artifacts": "https://github.com/demo/repo"})))) for w in (1, 2, 3)],
            ("Mentor verifies the logs", lambda: [ok(c.post(f"/api/logs/{l['id']}/verify", headers=M, json={"remarks": "Good work"}))
                                                  for l in ok(c.get(f"/api/records/{rid}", headers=M))["logs"]]),
            ("Student submits the final report", lambda: ok(c.post(f"/api/records/{rid}/report", headers=S, json={
                "summary": "Delivered three features end to end with tests, improved a slow query by 40% and documented the work "
                           "for the team. Presented a demo at the end of the internship."}))),
            ("Evaluation Agent: mentor gives the rating", lambda: ok(c.post(f"/api/records/{rid}/rating", headers=M,
                                                                           json={"score": 8.5, "feedback": "Reliable and quick learner"}))),
            ("Coordinator signs off the grade", lambda: ok(c.post(f"/api/records/{rid}/decision", headers=F,
                                                                 json={"gate": "GRADE", "decision": "APPROVED"}))),
            ("Policy Agent: coordinator drafts a rule", lambda: ok(c.post("/api/rules/propose", headers=F,
                                                                         json={"requirement": "Minimum attendance of 80% is required"}))),
            ("Ops Agent: admin checks system health", lambda: ok(c.get("/api/admin/health", headers=A))),
        ]
        STATUS.update(state="running", done=0, total=len(steps), error="", record_id=None)
        audit("system", "Demo journey", "started", {"opportunity": opp["id"], "steps": len(steps)})
        for i, (label, fn) in enumerate(steps):
            STATUS["step"] = label
            fn()
            STATUS["done"] = i + 1
        STATUS.update(state="done", step="Finished: all agents have run")
        audit("system", "Demo journey", "finished", {"record": rid})
    except Exception as e:  # noqa: BLE001
        STATUS.update(state="error", error=str(e)[:300])
        audit("system", "Demo journey", "failed", {"error": str(e)[:300]})
    finally:
        _lock.release()
