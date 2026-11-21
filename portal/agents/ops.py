"""Ops Agent (course concept: cloud operations agent) for the portal's own
deployment: observe health signals and the deployment log, reason about
the cause, and act only after an admin approves, using a whitelist of
safe, idempotent fixes."""

from __future__ import annotations

import json
import re

from .. import config, db, llm
from ..config import DOCS_DIR, FRONTEND_DIST, SKILLS_DIR
from ..guardrails import audit
from ..runtime import Agent, step

REQUIRED_TABLES = ["users", "students", "opportunities", "matches", "records", "approvals",
                   "progress_logs", "evaluations", "memory", "audit", "rules", "notifications"]
AGENT_SKILLS = ["resume-parsing", "opportunity-discovery", "application-processing", "approval",
                "progress-tracking", "internship-evaluation", "career-assistant",
                "company-research-summary"]
_CACHE: dict = {}
FIXES = {
    "run_migrations": {"label": "Create missing tables (CREATE TABLE IF NOT EXISTS)", "risk": "Low",
                       "rollback": "No data changes; nothing to roll back"},
    "restore_documents": {"label": "Restore missing college documents from the seed folder", "risk": "Low",
                          "rollback": "Delete the restored files"},
}


class OpsAgent(Agent):
    name = "Ops Agent"
    skill = ""
    tools = []
    description = ("Watches the portal's health, diagnoses failed deployments and applies "
                   "whitelisted fixes only after an admin approves.")

    def observe(self) -> dict:
        tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
        errors = db.one("SELECT COUNT(*) AS n FROM audit WHERE action = 'llm_error_fallback' OR "
                        "(kind = 'tool' AND detail LIKE '%\"ok\": false%')")["n"]
        seed_docs = [p.name for p in (db.SEED_DIR / "docs").glob("*")]
        log_path = DOCS_DIR / "failed_deploy.log"
        return {
            "missing_tables": [t for t in REQUIRED_TABLES if t not in tables],
            "llm_key_set": bool(config.GROQ_API_KEY), "llm_last_error": llm.last_error,
            "missing_skills": [s for s in AGENT_SKILLS if not (SKILLS_DIR / s / "SKILL.md").exists()],
            "missing_docs": [d for d in seed_docs if not (DOCS_DIR / d).exists()],
            "frontend_built": (FRONTEND_DIST / "index.html").exists(),
            "recent_errors": errors,
            "boards_synced": db.get_meta("boards_synced"),
            "deploy_log": log_path.read_text(encoding="utf-8") if log_path.exists() else "",
        }

    @step
    def diagnose(self, signals: dict) -> dict:
        key = json.dumps({k: v for k, v in signals.items() if k not in ("recent_errors", "boards_synced")}, sort_keys=True, default=str)
        if key in _CACHE:  # same signals as last time: reuse the diagnosis, no model call
            return {**_CACHE[key], "cached": True}
        findings = []
        log = signals["deploy_log"]
        for m in re.finditer(r"no such table: (\w+)", log):
            findings.append({"signal": m.group(0), "cause": f"Schema not migrated: table '{m.group(1)}' "
                             "did not exist when the app started", "fix": "run_migrations"})
        if signals["missing_tables"]:
            findings.append({"signal": f"live DB missing {signals['missing_tables']}",
                             "cause": "Schema not migrated on this instance", "fix": "run_migrations"})
        if "GROQ_API_KEY not set" in log or not signals["llm_key_set"]:
            findings.append({"signal": "GROQ_API_KEY not set", "cause": "Secret not injected; agents run "
                             "on deterministic fallbacks", "fix": None,
                             "manual": "Add GROQ_API_KEY to .env or the secret store and restart"})
        if signals["llm_last_error"]:
            findings.append({"signal": signals["llm_last_error"][:100], "cause": "LLM provider rejected "
                             "the last call", "fix": None, "manual": "Check the API key / quota"})
        if signals["missing_docs"]:
            findings.append({"signal": f"missing documents {signals['missing_docs']}",
                             "cause": "Document store incomplete", "fix": "restore_documents"})
        if signals["missing_skills"]:
            findings.append({"signal": f"missing skills {signals['missing_skills']}",
                             "cause": "Skill files not shipped", "fix": None,
                             "manual": "Restore the skills/ folder from the repository"})
        if not signals["frontend_built"]:
            findings.append({"signal": "frontend/dist missing", "cause": "React UI not built", "fix": None,
                             "manual": "cd frontend; npm install; npm run build"})
        out, mode = self.think(
            f"DEPLOY LOG:\n{log}\nSIGNALS: { {k: v for k, v in signals.items() if k != 'deploy_log'} }\n"
            f"FINDINGS: {findings}\nAllowed fixes: {list(FIXES)}\n"
            'Return {"root_cause": "one sentence", "explanation": "2 sentences"}',
            lambda: {"root_cause": findings[0]["cause"] if findings else "No problems detected",
                     "explanation": f"{len(findings)} finding(s) from log patterns and health signals."},
            fast=True)
        proposed = sorted({f["fix"] for f in findings if f.get("fix")})
        self.log("diagnosed", {"findings": len(findings), "proposed": proposed})
        _CACHE.clear()
        _CACHE[key] = {"findings": findings, "root_cause": out.get("root_cause"),
                "explanation": out.get("explanation"), "mode": mode,
                "proposed_fixes": [{"action": a, **FIXES[a]} for a in proposed]}
        return _CACHE[key]

    @step
    def apply(self, action: str, approver: dict) -> dict:
        if action not in FIXES:
            raise ValueError("fix not in the approved whitelist")
        before = self.observe()
        if action == "run_migrations":
            db.init_db()
        else:
            db._seed_docs()
        after = self.observe()
        audit("human", approver["name"], f"ops_fix_{action}", {"rollback": FIXES[action]["rollback"]})
        return {"action": action, "before": {k: before[k] for k in ("missing_tables", "missing_docs")},
                "after": {k: after[k] for k in ("missing_tables", "missing_docs")}}
