"""Portal end-to-end tests (offline, no LLM, tools over real MCP):
register -> resume -> matches -> apply -> offer -> NOC -> logs -> report ->
rating -> grade, plus runtime/MCP, permission, guardrail, policy and
assistant checks."""

import base64
import os
import tempfile
import time
from pathlib import Path

os.environ["PORTAL_DB"] = str(Path(tempfile.mkdtemp()) / "test_portal.db")
os.environ["PORTAL_SCHEDULER"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from portal import config  # noqa: E402

config.GROQ_API_KEY = ""  # tests run offline even when .env holds a real key

from portal import coordinator, db  # noqa: E402
from portal.main import app  # noqa: E402

c = TestClient(app)


def login(email, pw):
    r = c.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def H(role):
    return {"stu": ("ananya@college.edu", "student123"), "fac": ("coordinator@college.edu", "faculty123"),
            "men": ("arjun.mehta@industry.com", "mentor123"), "adm": ("admin@college.edu", "admin123")}[role]


def h(role):
    return login(*H(role))


def wait_idle(headers, timeout=20):
    for _ in range(timeout * 4):
        st = c.get("/api/me", headers=headers).json()["student"]
        if st["agent_status"] in ("idle", "error"):
            return st
        time.sleep(0.25)
    return st


def register(name, email, dept, cgpa, backlogs, resume: bytes):
    tok = c.post("/api/auth/register", json={"name": name, "email": email, "password": "secret1",
                                              "department": dept, "semester": 6}).json()["token"]
    hh = {"Authorization": "Bearer " + tok}
    c.put("/api/profile", headers=hh, json={"cgpa": cgpa, "attendance_pct": 80, "active_backlogs": backlogs})
    c.post("/api/profile/resume", headers=hh, json={"filename": "cv.txt",
                                                    "content_base64": base64.b64encode(resume).decode()})
    return hh, wait_idle(hh)


@pytest.fixture(scope="module", autouse=True)
def seeded():
    coordinator.sweep(sync_boards=False)  # parses the demo resume and matches the demo student


def test_one_demo_student_and_wrong_password():
    assert db.one("SELECT COUNT(*) AS n FROM students")["n"] >= 1
    assert c.post("/api/auth/login", json={"email": "ananya@college.edu", "password": "x"}).status_code == 401
    assert c.get("/api/me").status_code == 401


def test_resume_parsed_and_matched():
    me = c.get("/api/me", headers=h("stu")).json()["student"]
    assert {"python", "react", "machine learning"} <= set(me["skills"])
    assert len(me["resume_profile"]["projects"]) >= 2
    items = c.get("/api/internships", headers=h("stu")).json()["items"]
    assert items and items == sorted(items, key=lambda i: -i["score"])
    ids = {i["id"] for i in items}
    assert "cp-108" not in ids and "cp-109" not in ids          # scam blocked, duplicate collapsed
    assert "react" in next(i for i in items if i["id"] == "cp-102")["have"]


def test_tools_go_over_mcp_and_runs_are_logged():
    tools = db.query("SELECT json_extract(detail, '$.transport') AS t FROM audit WHERE kind = 'tool'")
    assert tools and all(t["t"] == "mcp" for t in tools)
    st = c.get("/api/admin/mcp", headers=h("adm")).json()
    assert st["connected"] and {"sql_query", "read_document", "campus_postings"} <= {t["name"] for t in st["tools"]}
    agents_called = {r["actor"] for r in db.query("SELECT actor FROM audit WHERE kind = 'agent' AND action = 'called'")}
    assert {"Resume Agent", "Opportunity Discovery Agent"} <= agents_called
    feed = c.get("/api/activity", headers=h("stu")).json()
    assert any(e["kind"] == "run" for e in feed) and any(e["kind"] == "agent" for e in feed)


def test_incremental_rematch_skips_unchanged_postings():
    stu = h("stu")
    c.post("/api/profile/rematch", headers=stu)
    wait_idle(stu)
    plan = db.query("SELECT detail FROM audit WHERE actor = 'Opportunity Discovery Agent' AND action = 'plan' "
                    "ORDER BY id DESC LIMIT 1")[0]["detail"]
    assert plan["to_rank"] == 0 and plan["cached"] > 0


def test_eligibility_reasons_and_privacy():
    hh, st = register("Rahul Test", "rahul.t@x.com", "ECE", 6.9, 1,
                      b"SKILLS\nEmbedded C, Arduino, ESP32, MQTT, Python\nPROJECTS\nSmart irrigation\n- ESP32 + MQTT")
    assert st["agent_status"] == "idle" and "esp32" in st["skills"]
    items = c.get("/api/internships", headers=hh).json()["items"]
    bosch = next(i for i in items if i["id"] == "cp-103")
    assert bosch["eligibility"] == "NOT_ELIGIBLE" and "CGPA" in bosch["eligibility_summary"]
    r = c.post("/api/internships/cp-103/apply", headers=hh)
    assert r.status_code == 400 and "not eligible" in r.json()["detail"]
    rid = c.post("/api/internships/cp-106/apply", headers=h("stu")).json()["record_id"]
    assert c.get(f"/api/records/{rid}", headers=hh).status_code == 403
    assert c.post("/api/profile/resume", headers=hh, json={"filename": "cv.exe", "content_base64": "eA=="}).status_code == 400


def test_full_lifecycle():
    stu, fac, men = h("stu"), h("fac"), h("men")
    rid = c.post("/api/internships/cp-102/apply", headers=stu).json()["record_id"]
    d = c.get(f"/api/records/{rid}", headers=stu).json()
    assert d["record"]["stage"] == "SAVED" and "Zoho" in d["record"]["application"]["cover_letter"]
    assert c.post(f"/api/records/{rid}/status", headers=stu, json={"stage": "APPLIED"}).status_code == 400
    c.post(f"/api/records/{rid}/status", headers=stu, json={"stage": "APPLIED", "applied_on": "2026-11-01"})
    res = c.post(f"/api/records/{rid}/offer", headers=stu,
                 json={"offer_ref": "ZOHO-1", "start_date": "2026-10-20", "duration_weeks": 8, "stipend": "20000"}).json()
    assert res["stage"] == "NOC_PENDING"
    assert c.post(f"/api/records/{rid}/decision", headers=men, json={"gate": "NOC", "decision": "APPROVED"}).status_code == 403
    assert c.post(f"/api/records/{rid}/decision", headers=fac, json={"gate": "NOC", "decision": "APPROVED"}).status_code == 400
    res = c.post(f"/api/records/{rid}/decision", headers=fac,
                 json={"gate": "NOC", "decision": "APPROVED", "mentor_id": "u-men-1"}).json()
    assert res["stage"] == "ONGOING"
    d = c.get(f"/api/records/{rid}", headers=stu).json()
    assert "NO OBJECTION CERTIFICATE" in d["record"]["noc"]["letter"] and d["record"]["milestones"]
    for w, hrs in [(1, 32), (2, 18), (4, 31)]:
        c.post(f"/api/records/{rid}/logs", headers=stu, json={"week": w, "hours": hrs, "tasks": "Built React dashboard and REST API"})
    hl = c.get(f"/api/records/{rid}", headers=stu).json()["record"]["progress_health"]
    assert 3 in hl["missing_weeks"] and any("Week 2" in s for s in hl["shortfalls"]) and hl["status"] != "ON_TRACK"
    log_id = c.get(f"/api/records/{rid}", headers=men).json()["logs"][0]["id"]
    assert c.post(f"/api/logs/{log_id}/verify", headers=men, json={"remarks": "good"}).status_code == 200
    res = c.post(f"/api/records/{rid}/report", headers=stu, json={
        "summary": "Built analytics dashboards in React with REST APIs, improved SQL performance and documented the work."}).json()
    assert res["stage"] == "COMPLETED"
    res = c.post(f"/api/records/{rid}/rating", headers=men, json={"score": 8, "feedback": "Solid"}).json()
    assert res["stage"] == "GRADE_PENDING"
    res = c.post(f"/api/records/{rid}/decision", headers=fac,
                 json={"gate": "GRADE", "decision": "CHANGES_REQUESTED", "remarks": "Recheck technical depth"}).json()
    assert res["stage"] == "GRADE_PENDING"
    c.post(f"/api/records/{rid}/decision", headers=fac, json={"gate": "GRADE", "decision": "APPROVED"})
    d = c.get(f"/api/records/{rid}", headers=stu).json()
    assert d["record"]["stage"] == "GRADED" and len(d["evaluations"]) == 2 and d["evaluations"][-1]["status"] == "FINAL"
    decisions = [(a["gate"], a["decision"]) for a in d["approvals"]]
    assert ("NOC", "APPROVED") in decisions and ("GRADE", "CHANGES_REQUESTED") in decisions
    # every agent of the worklet ran for this record
    actors = {r["actor"] for r in db.query("SELECT DISTINCT actor FROM audit WHERE kind = 'agent' AND action = 'called'")}
    assert {"Application Processing Agent", "Approval Agent", "Progress Tracking Agent", "Evaluation Agent"} <= actors
    assert any("final grade" in n["text"].lower() for n in c.get("/api/notifications", headers=stu).json())


def test_assistant_uses_tools_and_memory():
    stu = h("stu")
    r = c.post("/api/assistant", headers=stu, json={"message": "what is 30 * 12"}).json()
    assert "360" in r["reply"] and r["tools"][0]["tool"] == "calculator"
    r = c.post("/api/assistant", headers=stu, json={"message": "remember I only want remote roles"}).json()
    assert r["tools"][0]["tool"] == "remember"
    assert (config.DATA_DIR / "memory" / "s-1.md").read_text(encoding="utf-8").count("remote") >= 1
    r = c.post("/api/assistant", headers=stu, json={"message": "find react internships"}).json()
    assert r["tools"][0]["tool"] == "search_internships"


def test_policy_rule_publish_and_rollback():
    fac = h("fac")
    p = c.post("/api/rules/propose", headers=fac, json={"requirement": "CGPA must be at least 9.0"}).json()
    assert p["ok"] and p["spec"]["field"] == "cgpa"
    assert c.post("/api/rules/publish", headers=h("stu"), json={"spec": p["spec"]}).status_code == 403
    c.post("/api/rules/publish", headers=fac, json={"spec": p["spec"]})
    items = c.get("/api/internships", headers=h("stu")).json()["items"]
    assert all(i["eligibility"] == "NOT_ELIGIBLE" for i in items)   # 8.6 < 9.0 college rule
    assert c.post("/api/rules/policy_cgpa/rollback", headers=fac).json()["active_version"] is None


def test_faculty_posts_internship_and_scam_blocked():
    fac = h("fac")
    ok = c.post("/api/opportunities", headers=fac, json={"title": "QA Intern", "company": "Acme", "url": "https://acme.test/jobs",
                                                         "required_skills": ["python"], "description": "Testing web apps"}).json()
    assert ok["outcome"] == "added"
    bad = c.post("/api/opportunities", headers=fac, json={"title": "Easy Intern", "company": "Scammy", "url": "https://s.test",
                                                          "description": "Pay registration fee, no interview"}).json()
    assert bad["outcome"] == "blocked"


def test_admin_tools_and_safety():
    adm = h("adm")
    assert "error" in c.post("/api/admin/tools/sql_query", headers=adm, json={"sql": "DELETE FROM records"}).json()
    safety = c.get("/api/admin/safety", headers=adm).json()
    assert all(e["passed"] for e in safety["evals"]), [e for e in safety["evals"] if not e["passed"]]
    dx = c.get("/api/admin/health", headers=adm).json()["diagnosis"]
    assert any(f["fix"] == "run_migrations" for f in dx["findings"])
    assert c.get("/api/admin/overview", headers=h("fac")).status_code == 403


def test_demo_journey_runs_every_agent():
    from portal.demo import STATUS, run_journey
    run_journey()
    assert STATUS["state"] == "done", STATUS
    roster = c.get("/api/activity/agents", headers=h("adm")).json()
    assert roster["ran"] == roster["total"] == 12, [a["name"] for a in roster["agents"] if not a["calls"]]
    assert all(r["calls"] for r in roster["reviewers"])
    assert db.one("SELECT COUNT(*) AS n FROM runs WHERE channel = 'demo'")["n"] > 0
    assert db.get_record(STATUS["record_id"])["stage"] == "GRADED"
