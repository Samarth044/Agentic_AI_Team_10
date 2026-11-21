"""Internship Portal Coordinator: the workflow engine (course concepts 1 and 7).

Every piece of work enters through the Gateway as a run and follows the agent
loop: GOAL -> PLAN -> ACT -> OBSERVE -> IMPROVE (revise when the result is
not good enough). Agents run on their own in three ways:

1. Event-driven: a person's action triggers the next agent (resume upload ->
   Resume Agent -> Discovery -> Eligibility; offer -> Approval Agent; weekly
   log -> Progress Agent; report + rating -> Evaluation Agent -> Approval Agent).
2. Background worker: slow agent work runs off the request thread.
3. Scheduler (channel "scheduler"): every N minutes, re-match students when
   postings change and remind interns about overdue logs. It only calls the AI
   when something actually changed.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from . import db
from .agents import (ApprovalAgent, EvaluationAgent, OpportunityDiscoveryAgent,
                     ProgressTrackingAgent, ResumeAgent)
from .config import BOARD_SYNC_HOURS, SCHEDULER_ENABLED, SCHEDULER_MINUTES
from .graph import AGENT_STAGES
from .guardrails import audit
from .notify import notify_student
from .runtime import gateway

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="agents")
_student_locks: dict[str, threading.Lock] = {}


def submit(fn, *args):
    """Run agent work in the background. It gets its own run (worker threads start
    with an empty context), because the request that queued it finishes first."""
    def wrapped():
        try:
            fn(*args)
        except Exception as e:  # noqa: BLE001
            audit("system", "Coordinator", "background_error", {"fn": fn.__name__, "error": str(e)[:300]})
    return _pool.submit(wrapped)


def _set_status(student_id: str, status: str, message: str) -> None:
    db.update("students", student_id, {"agent_status": status, "agent_message": message})


# ------------------------------------------------------------ student pipeline

def process_student(student_id: str, filename: str | None = None, full: bool = True,
                    channel: str = "web", reason: str = "") -> dict:
    """Resume -> discovery & matching -> eligibility for one student."""
    lock = _student_locks.setdefault(student_id, threading.Lock())
    with lock:
        student = db.get_student(student_id)
        goal = f"Find the best internships for {student['name']}" + (f" ({reason})" if reason else "")
        with gateway.run(goal, channel=channel, actor=student["name"], student_id=student_id) as run:
            try:
                parse = bool(filename or (student.get("resume_text") and not student.get("resume_profile")))
                run.step("PLAN", ("Resume Agent reads the resume -> " if parse else "") +
                         "Discovery Agent ranks postings -> Eligibility Agent checks each -> notify strong matches")
                if parse:
                    _set_status(student_id, "parsing", "Reading your resume…")
                    prof = ResumeAgent().run(student, filename)
                    run.step("OBSERVE", f"Resume Agent found {len(prof.get('skills') or [])} skills and "
                                        f"{len(prof.get('projects') or [])} projects")
                    full = True
                student = db.get_student(student_id)
                if not student.get("skills"):
                    _set_status(student_id, "idle", "Upload your resume or add skills to get matches")
                    run.step("OBSERVE", "No skills yet; stopping until the student adds a resume")
                    return {"run_id": run.run_id}
                _set_status(student_id, "matching", "Matching you with internships…")
                res = OpportunityDiscoveryAgent().run(student, full=full)
                run.step("OBSERVE", f"Ranked {res['ranked']} posting(s) ({res.get('cached', 0)} unchanged, kept); "
                                    f"eligible for {res['eligible']}; {res['new_strong']} new strong match(es)")
                strong = db.one("SELECT COUNT(*) AS n FROM matches WHERE student_id = ? AND score >= 60 AND "
                                "json_extract(eligibility, '$.status') = 'ELIGIBLE'", (student_id,))["n"]
                if strong == 0:
                    run.step("IMPROVE", "No strong eligible match: widen the search to public job boards")
                    sync = OpportunityDiscoveryAgent().sync_boards()
                    if sync.get("added"):
                        res = OpportunityDiscoveryAgent().run(db.get_student(student_id), full=False)
                    run.step("OBSERVE", f"Job boards added {sync.get('added', 0)} posting(s)")
                _set_status(student_id, "idle", f"Matched against your internships; eligible for {res['eligible']}")
                return {"run_id": run.run_id, **res}
            except Exception as e:
                _set_status(student_id, "error", f"Agents hit a problem: {str(e)[:120]}")
                run.step("OBSERVE", f"Failed: {e}")
                raise


def recheck_eligibility_only(student_id: str) -> None:
    """Academic details changed: rules only, no AI call."""
    from .agents import EligibilityVerificationAgent
    s = db.get_student(student_id)
    with gateway.run(f"Re-check eligibility for {s['name']} (academic details changed)",
                     actor=s["name"], student_id=student_id) as run:
        run.step("PLAN", "Rules engine only; the AI analysis of each posting is unchanged")
        n = EligibilityVerificationAgent().recheck_all(student_id)
        run.step("OBSERVE", f"Re-checked {n} posting(s)")
    _set_status(student_id, "idle", "Eligibility updated")


def rematch_all(reason: str) -> None:
    for s in db.query("SELECT id FROM students WHERE resume_profile IS NOT NULL"):
        process_student(s["id"], full=False, channel="event", reason=reason)


# ------------------------------------------------------------ record events

def react(record_id: str, remarks: str = "", actor: str = "system") -> list[str]:
    """Called after every human action on a record: run whichever agent is next."""
    rec = db.get_record(record_id)
    done = []
    with gateway.run(f"Advance {record_id} after a human action (stage {rec['stage']})", channel="event",
                     actor=actor, student_id=rec["student_id"], record_id=record_id) as run:
        node = "progress" if rec["stage"] == "ONGOING" else AGENT_STAGES.get(rec["stage"])
        run.step("PLAN", f"Stage {rec['stage']} -> next node: {node or 'a person (waiting)'}")
        for _ in range(4):
            rec = db.get_record(record_id)
            stage = rec["stage"]
            if stage == "ONGOING":
                agent = ProgressTrackingAgent()
                if rec.get("milestones") is None:
                    agent.plan(rec)
                    done.append("Progress Agent planned your milestones")
                h = agent.analyze(db.get_record(record_id))
                done.append(f"Progress Agent updated your progress health ({h['status'].replace('_', ' ').lower()})")
                break
            node = AGENT_STAGES.get(stage)
            if node == "approval":
                ApprovalAgent().review_offer(rec)
                done.append("Approval Agent checked the offer and sent it to your coordinator")
            elif node == "evaluation":
                ev = EvaluationAgent().run(rec, remarks)
                if not ev:
                    done.append("Evaluation Agent is " + EvaluationAgent().ready(rec))
                    break
                ApprovalAgent().review_grade(db.get_record(record_id), ev)
                done.append(f"Evaluation Agent drafted grade {ev['grade']} ({ev['total']}/100) for sign-off")
            else:
                break
        for d in done:
            run.step("ACT", d, record_id)
        run.step("OBSERVE", f"Record now at {db.get_record(record_id)['stage']}; waiting for a person", record_id)
    return done


# ------------------------------------------------------------ scheduler

def sweep(sync_boards: bool = True) -> dict:
    out = {}
    with gateway.run("Scheduled sweep: fresh postings, current matches, interns on track",
                     channel="scheduler", actor="Scheduler") as run:
        last = db.get_meta("boards_synced")
        stale = not last or datetime.fromisoformat(last) < datetime.now(timezone.utc) - timedelta(hours=BOARD_SYNC_HOURS)
        run.step("PLAN", ("Sync job boards (last sync over a day ago) -> " if sync_boards and stale else "") +
                 "re-match only students affected by changes -> check ongoing internships")
        if sync_boards and stale:
            out["sync"] = OpportunityDiscoveryAgent().sync_boards()
        changed = db.get_meta("opps_changed") or ""
        touched = 0
        for s in db.query("SELECT id, matched_at, resume_text, resume_profile FROM students"):
            if s["resume_text"] and not s["resume_profile"]:
                process_student(s["id"], channel="scheduler", reason="new resume")
                touched += 1
            elif s["resume_profile"] and (s["matched_at"] or "") < changed:
                process_student(s["id"], full=False, channel="scheduler", reason="postings changed")
                touched += 1
        reminders = 0
        for r in db.query("SELECT * FROM records WHERE stage = 'ONGOING'"):
            h = ProgressTrackingAgent().analyze(r)   # no AI call unless there is a new log
            if h["missing_weeks"]:
                reminders += 1
                opp = db.get_opportunity(r["opportunity_id"])
                notify_student(r["student_id"], f"Reminder: weekly log for week {h['missing_weeks'][0]} at "
                                                f"{opp['company']} is overdue", f"#/records/{r['id']}")
        run.step("OBSERVE", f"{touched} student(s) re-matched; {reminders} overdue-log reminder(s)")
    out.update({"rematched": touched, "reminders": reminders})
    return out


def start_scheduler() -> None:
    if not SCHEDULER_ENABLED:
        return

    def loop():
        time.sleep(3)
        while True:
            try:
                sweep()
            except Exception as e:  # noqa: BLE001
                audit("system", "Scheduler", "sweep_error", {"error": str(e)[:300]})
            time.sleep(SCHEDULER_MINUTES * 60)

    threading.Thread(target=loop, daemon=True, name="scheduler").start()
