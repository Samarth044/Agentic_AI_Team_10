"""Agent runtime, modelled on OpenClaw (course concept 6).

OpenClaw puts one long-running Gateway in front of an agent runtime:

  channel (web UI / chat / scheduler) -> Gateway -> run (run id + session)
      -> agent loop: load skill -> assemble context -> model -> tools -> persist

This module is that runtime for the portal:

  Interface  `gateway.run(...)`: every request from a channel becomes a run
             with a run id, a session (student) and lifecycle events.
  Runtime    `Agent` base class + `@step`: every agent call is announced,
             timed and recorded ("Resume Agent called -> finished in 2.1s").
  Skills     SKILL.md files, only name/description always known; the body is
             loaded into the prompt when the owning agent runs.
  Tools      an allow-list per agent; calls go over MCP (portal/connector.py).
  Memory     session memory per run + long-term memory (SQLite + Markdown files).
  Audit log  every event goes to the `audit` table and logs/portal-audit.jsonl.
"""

from __future__ import annotations

import contextvars
import functools
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from pathlib import Path

import yaml

from . import connector, context, db, llm
from .config import SKILLS_DIR
from .guardrails import audit
from .memory import LongTermMemory, SessionMemory


def new_run_id() -> str:
    return "RUN-" + uuid.uuid4().hex[:8].upper()


# ================================================================== interface: Gateway

class Run:
    def __init__(self, goal: str, channel: str, actor: str, student_id: str | None, record_id: str | None):
        self.run_id = new_run_id()
        self.goal, self.channel, self.actor = goal, channel, actor
        self.student_id, self.record_id = student_id, record_id
        self.session = SessionMemory(self.run_id)
        self.started = time.perf_counter()

    def step(self, phase: str, text: str, record_id: str | None = None) -> None:
        """Coordinator loop phases: GOAL, PLAN, ACT, OBSERVE, IMPROVE."""
        self.session.note(f"{phase}: {text}")
        audit("loop", "Coordinator", phase, {"text": text}, record_id or self.record_id, self.run_id)


class Gateway:
    """Single entry point for all work. Channels: web (a person clicked something),
    chat (career assistant), scheduler (background sweep), event (agent-to-agent)."""

    @contextmanager
    def run(self, goal: str, channel: str = "web", actor: str = "system",
            student_id: str | None = None, record_id: str | None = None, generic: bool = False):
        parent = context.current.get()
        if parent is not None:  # nested call: stay inside the parent run
            if getattr(parent, "generic", False):  # request-level run: add the specific goal
                parent.goal, parent.channel, parent.generic = f"{parent.goal} → {goal}", channel, False
                goal = parent.goal
                db.update("runs", parent.run_id, {"goal": goal, "channel": channel}, key_col="run_id")
                audit("run", "Gateway", "run_named", {"goal": goal, "channel": channel}, record_id, parent.run_id)
            self.attach(parent, student_id, record_id)
            yield parent
            return
        r = Run(goal, channel, actor, student_id, record_id)
        r.generic = generic
        db.insert("runs", {"run_id": r.run_id, "goal": goal, "channel": channel, "actor": actor,
                           "student_id": student_id, "record_id": record_id, "status": "running",
                           "started_at": db.now()})
        token = context.current.set(r)
        audit("run", "Gateway", "run_started", {"goal": goal, "channel": channel, "actor": actor},
              record_id, r.run_id)
        status = "done"
        try:
            yield r
        except Exception as e:
            status = "failed"
            audit("run", "Gateway", "run_failed", {"error": str(e)[:300]}, record_id, r.run_id)
            raise
        finally:
            ms = round((time.perf_counter() - r.started) * 1000)
            db.update("runs", r.run_id, {"status": status, "finished_at": db.now(), "ms": ms,
                                         "student_id": r.student_id, "record_id": r.record_id,
                                         "session": r.session.snapshot()}, key_col="run_id")
            audit("run", "Gateway", "run_finished", {"status": status, "ms": ms,
                                                     "session_notes": len(r.session.state["observations"])},
                  r.record_id, r.run_id)
            context.current.reset(token)

    @staticmethod
    def attach(run: Run, student_id: str | None, record_id: str | None) -> None:
        if student_id and not run.student_id:
            run.student_id = student_id
        if record_id and not run.record_id:
            run.record_id = record_id


gateway = Gateway()


def parallel(fn, items, workers: int = 4) -> list:
    """Parallel branches that stay inside the current run (context is copied per task)."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(contextvars.copy_context().run, fn, x) for x in items]
        return [f.result() for f in futures]


# ================================================================== skills

def parse_skill(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8-sig")
    meta: dict = {}
    body = text
    if text.startswith("---"):
        _, front, body = text.split("---", 2)
        try:
            meta = yaml.safe_load(front) or {}
        except yaml.YAMLError:  # unquoted colons in a description: fall back to key: value lines
            for line in front.strip().splitlines():
                if ":" in line and not line.startswith(" "):
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
    return meta, body.strip()


def skill_catalog() -> list[dict]:
    """Progressive disclosure, level 1: only name + description of every skill."""
    used = {r["skill"]: r["n"] for r in db.query(
        "SELECT json_extract(detail, '$.skill') AS skill, COUNT(*) AS n FROM audit "
        "WHERE action = 'skill_loaded' GROUP BY skill")}
    out = []
    for p in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        meta, body = parse_skill(p)
        out.append({"folder": p.parent.name, "name": meta.get("name", p.parent.name),
                    "description": str(meta.get("description", "")).strip(),
                    "owner": meta.get("owner", ""), "chars": len(body), "loaded": used.get(p.parent.name, 0)})
    return out


def load_skill(folder: str) -> str:
    """Level 2: full body, loaded only when the agent that owns it runs."""
    return parse_skill(SKILLS_DIR / folder / "SKILL.md")[1]


# ================================================================== runtime: agents

def _subject(args) -> tuple[str | None, str | None]:
    """Find the student / record an agent call is about (for the session and the log)."""
    sid = rid = None
    for a in args:
        if isinstance(a, dict):
            if str(a.get("id", "")).startswith("IR-"):
                rid, sid = a["id"], a.get("student_id")
            elif "usn" in a and a.get("id"):
                sid = a["id"]
            elif a.get("student_id"):
                sid = a["student_id"]
    return sid, rid


def _summary(out) -> str:
    if out is None:
        return "nothing to do yet"
    if isinstance(out, str):
        return out[:120]
    if isinstance(out, list):
        return f"{len(out)} items"
    if isinstance(out, dict):
        keys = ("status", "verdict", "grade", "total", "ranked", "eligible", "new_strong", "version",
                "fetched", "added", "root_cause", "stage", "ok")
        parts = [f"{k}={out[k]}" for k in keys if k in out and not isinstance(out[k], (dict, list))]
        if "skills" in out and isinstance(out["skills"], list):
            parts.append(f"skills={len(out['skills'])}")
        if "projects" in out and isinstance(out["projects"], list):
            parts.append(f"projects={len(out['projects'])}")
        return ", ".join(parts)[:160] or "done"
    return str(out)[:120]


def step(fn):
    """Runtime hook around an agent's public method: opens a run if none is active,
    logs 'called' / 'finished' / 'failed' with timing so the activity log shows
    exactly which agent ran, with which skill and tools."""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        sid, rid = _subject(args)
        outer = context.current.get()
        cm = gateway.run(f"{self.name}: {fn.__name__.replace('_', ' ')}", channel="web",
                         student_id=sid, record_id=rid) if outer is None else nullcontext(outer)
        with cm as run:
            gateway.attach(run, sid, rid)
            self.run_id, self.session = run.run_id, run.session
            audit("agent", self.name, "called", {"method": fn.__name__, "skill": self.skill or None,
                                                 "tools": self.tools}, rid, run.run_id)
            t = time.perf_counter()
            try:
                out = fn(self, *args, **kwargs)
            except Exception as e:
                audit("agent", self.name, "failed", {"method": fn.__name__, "error": str(e)[:200]}, rid, run.run_id)
                raise
            audit("agent", self.name, "finished", {"method": fn.__name__,
                                                   "ms": round((time.perf_counter() - t) * 1000),
                                                   "result": _summary(out)}, rid, run.run_id)
            return out
    wrapper.is_step = True
    return wrapper


class Agent:
    name = "Agent"
    skill = ""
    tools: list[str] = []
    description = ""

    def __init__(self, session: SessionMemory | None = None, run_id: str = ""):
        run = context.current.get()
        self.run_id = run_id or (run.run_id if run else "")
        self.session = session or (run.session if run else SessionMemory(self.run_id))
        self.memory = LongTermMemory

    def log(self, action: str, detail: dict | None = None, record_id: str | None = None,
            kind: str = "agent") -> None:
        audit(kind, self.name, action, detail, record_id, self.run_id or context.run_id())

    def tool(self, name: str, args: dict | None = None, record_id: str | None = None) -> dict:
        """Tool use is limited to the agent's allow-list; the call itself goes over MCP."""
        if name not in self.tools:
            self.log("tool_denied", {"tool": name}, record_id, kind="guardrail")
            raise PermissionError(f"{self.name} may not use tool {name}")
        return connector.call(name, args, self.name, self.run_id or context.run_id(), record_id)

    def think(self, user: str, fallback, record_id: str | None = None,
              fast: bool = False) -> tuple[dict, str]:
        """Assemble context (skill + task) and ask the model."""
        system = "You are a helpful agent."
        if self.skill:
            system = load_skill(self.skill)
            loaded = self.session.state.setdefault("skills_loaded", [])
            if self.skill not in loaded:
                loaded.append(self.skill)
                self.log("skill_loaded", {"skill": self.skill, "chars": len(system)}, record_id)
        return llm.chat_json(self.name, system, user, fallback, fast=fast,
                             run_id=self.run_id or context.run_id(), record_id=record_id)

    @classmethod
    def card(cls) -> dict:
        steps = [n for n, f in vars(cls).items() if getattr(f, "is_step", False)]
        return {"name": cls.name, "skill": cls.skill, "tools": cls.tools, "description": cls.description,
                "methods": steps}


def runtime_overview() -> dict:
    count = lambda sql: db.one(sql)["n"]  # noqa: E731
    return {
        "runs": count("SELECT COUNT(*) AS n FROM runs"),
        "agent_calls": count("SELECT COUNT(*) AS n FROM audit WHERE kind = 'agent' AND action = 'called'"),
        "llm_calls": count("SELECT COUNT(*) AS n FROM audit WHERE kind = 'llm'"),
        "tool_calls": count("SELECT COUNT(*) AS n FROM audit WHERE kind = 'tool'"),
        "mcp_calls": count("SELECT COUNT(*) AS n FROM audit WHERE kind = 'tool' AND "
                           "json_extract(detail, '$.transport') = 'mcp'"),
        "memories": count("SELECT COUNT(*) AS n FROM memory"),
        "channels": [dict(r) for r in db.query("SELECT channel, COUNT(*) AS n FROM runs GROUP BY channel")],
    }


__all__ = ["gateway", "Agent", "step", "parallel", "load_skill", "skill_catalog", "new_run_id", "json"]
