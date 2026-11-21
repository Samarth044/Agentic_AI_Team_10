"""Memory & context (course concept 4).

- SessionMemory: short-term state for ONE run (plan, observations, counters,
  skills loaded). Saved with the run when it ends, then never fed back in.
- LongTermMemory: stored reference that survives restarts (preferences the
  student tells the assistant, coordinator remarks, past outcomes). Kept in
  SQLite and mirrored to a human-readable Markdown file per student
  (data/memory/<student>.md), the way OpenClaw keeps MEMORY.md.
- Controlled retrieval: agents recall only the top-k entries that share words
  with the current task, never the whole history.
"""

from __future__ import annotations

import re

from . import context, db
from .config import DATA_DIR
from .guardrails import audit

MEMORY_DIR = DATA_DIR / "memory"
_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "at", "is", "with", "my", "me", "i"}


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP and len(w) > 1}


class SessionMemory:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.state: dict = {"observations": [], "counters": {}, "skills_loaded": []}

    def note(self, observation: str) -> None:
        self.state["observations"].append(observation)

    def bump(self, key: str, n: int = 1) -> None:
        self.state["counters"][key] = self.state["counters"].get(key, 0) + n

    def snapshot(self) -> dict:
        return self.state


class LongTermMemory:
    @staticmethod
    def remember(student_id: str, kind: str, content: str) -> None:
        db.insert("memory", {"student_id": student_id, "kind": kind, "content": content, "ts": db.now()})
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        path = MEMORY_DIR / f"{student_id}.md"
        if not path.exists():
            path.write_text(f"# Long-term memory: {student_id}\n\n", encoding="utf-8")
        with path.open("a", encoding="utf-8") as f:
            f.write(f"- {db.now()[:16]} [{kind}] {content}\n")
        audit("memory", "Memory", "remembered", {"student_id": student_id, "kind": kind,
                                                 "content": content[:200]}, run_id=context.run_id())

    @staticmethod
    def recall(student_id: str, query: str, k: int = 3, kind: str | None = None) -> list[dict]:
        """Keyword-overlap retrieval: score = shared words, newest wins ties."""
        sql = "SELECT * FROM memory WHERE student_id = ?"
        params: tuple = (student_id,)
        if kind:
            sql += " AND kind = ?"
            params += (kind,)
        rows = db.query(sql + " ORDER BY id DESC", params)
        q = _tokens(query)
        scored = [(len(q & _tokens(r["content"])), r) for r in rows]
        hits = [dict(r, score=s) for s, r in sorted(scored, key=lambda x: -x[0]) if s > 0][:k]
        audit("memory", "Memory", "recalled", {"student_id": student_id, "query": query[:120],
                                               "stored": len(rows), "returned": len(hits),
                                               "hits": [h["content"][:80] for h in hits]},
              run_id=context.run_id())
        return hits

    @staticmethod
    def all_for(student_id: str) -> list[dict]:
        return db.query("SELECT * FROM memory WHERE student_id = ? ORDER BY id DESC", (student_id,))
