"""Career Assistant: the student's chat agent.

Course concepts it carries:
- agent vs chatbot: asks a clarifying question when a request is vague,
  then plans, calls tools, observes the results and answers from them
- tool use: real function calling over student-scoped tools
- memory: recent conversation (short-term) + remembered preferences and
  past outcomes retrieved by relevance (long-term)
"""

from __future__ import annotations

import json
import re

from .. import connector, db, llm
from ..config import MIN_MATCH_TO_SHOW
from ..guardrails import mask_text
from ..runtime import Agent, load_skill, step

SPECS = [
    ("search_internships", "Search the student's ranked internship matches.",
     {"query": {"type": "string", "description": "keywords, e.g. 'machine learning bengaluru'"},
      "eligible_only": {"type": "boolean"}}, []),
    ("internship_details", "Full details and fit analysis for one internship.",
     {"opportunity_id": {"type": "string"}}, ["opportunity_id"]),
    ("my_applications", "The student's tracked applications and their status.", {}, []),
    ("skill_gaps", "Skills the student lacks most often across good matches.", {}, []),
    ("college_policy", "Read the college internship policy.", {}, []),
    ("calculator", "Exact arithmetic.", {"expression": {"type": "string"}}, ["expression"]),
    ("remember", "Save a lasting preference or fact the student tells you.",
     {"fact": {"type": "string"}}, ["fact"]),
]


class CareerAssistant(Agent):
    name = "Career Assistant"
    skill = "career-assistant"
    tools = ["calculator", "read_document"]
    description = ("Chat agent for students: clarifies vague requests, searches matches, checks "
                   "eligibility and policy with tools, and remembers preferences across sessions.")

    def __init__(self, student: dict, **kw):
        super().__init__(**kw)
        self.student = student

    # ------------------------------------------------------------ tools
    def _matches(self) -> list[dict]:
        return db.query("SELECT m.*, o.title, o.company, o.location, o.mode, o.stipend, o.duration_weeks, "
                        "o.url FROM matches m JOIN opportunities o ON o.id = m.opportunity_id "
                        "WHERE m.student_id = ? AND o.status = 'open' ORDER BY m.score DESC",
                        (self.student["id"],))

    def t_search_internships(self, query: str = "", eligible_only: bool = False) -> dict:
        words = [w for w in re.findall(r"[a-z0-9+#]+", (query or "").lower()) if len(w) > 2
                 and w not in {"internship", "internships", "intern", "find", "show", "me", "any", "for"}]
        out = []
        for m in self._matches():
            if m["score"] < MIN_MATCH_TO_SHOW:
                continue
            if eligible_only and m["eligibility"]["status"] != "ELIGIBLE":
                continue
            text = f"{m['title']} {m['company']} {m['location']} {m['mode']} {' '.join(m['have'] + m['missing'])}".lower()
            if words and not any(w in text for w in words):
                continue
            out.append({"id": m["opportunity_id"], "title": m["title"], "company": m["company"],
                        "location": m["location"], "match": m["score"],
                        "eligibility": m["eligibility"]["status"], "stipend": m["stipend"],
                        "have": m["have"][:5], "missing": m["missing"][:5]})
        return {"results": out[:6], "total": len(out)}

    def t_internship_details(self, opportunity_id: str) -> dict:
        o = db.get_opportunity(opportunity_id)
        m = db.get_match(self.student["id"], opportunity_id)
        if not o or not m:
            return {"error": "not found"}
        return {"title": o["title"], "company": o["company"], "location": o["location"],
                "duration_weeks": o["duration_weeks"], "stipend": o["stipend"], "deadline": o["deadline"],
                "apply_link": o["url"], "match": m["score"], "why": m["why"], "improve": m["improve"],
                "have": m["have"], "missing": m["missing"], "eligibility": m["eligibility"]["summary"],
                "shortfalls": m["eligibility"]["shortfalls"]}

    def t_my_applications(self) -> dict:
        rows = db.query("SELECT r.id, r.stage, o.title, o.company FROM records r JOIN opportunities o "
                        "ON o.id = r.opportunity_id WHERE r.student_id = ?", (self.student["id"],))
        return {"applications": rows}

    def t_skill_gaps(self) -> dict:
        return {"gaps": skill_gaps(self.student["id"])[:6]}

    def t_college_policy(self) -> dict:
        return {"policy": self.tool("read_document", {"name": "internship_policy.md"}).get("content", "")}

    def t_calculator(self, expression: str) -> dict:
        return self.tool("calculator", {"expression": expression})

    def t_remember(self, fact: str) -> dict:
        self.memory.remember(self.student["id"], "preference", mask_text(fact, self.student)[:300])
        return {"saved": True}

    def _run_tool(self, name: str, args: dict) -> dict:
        fn = getattr(self, f"t_{name}", None)
        if not fn:
            return {"error": "unknown tool"}
        try:
            res = fn(**args)
        except Exception as e:  # noqa: BLE001
            res = {"error": str(e)}
        self.log(name, {"args": args, "result_preview": json.dumps(res, default=str)[:300]}, kind="tool")
        return res

    # ------------------------------------------------------------ chat
    def _context(self, message: str) -> str:
        s = self.student
        mem = self.memory.recall(s["id"], message, k=4)
        prefs = [m["content"] for m in self.memory.all_for(s["id"]) if m["kind"] == "preference"][:5]
        return (f"STUDENT: {s['department']} semester {s['semester']}, CGPA {s['cgpa']}, attendance "
                f"{s['attendance_pct']}%, skills: {', '.join((s.get('skills') or [])[:15])}. "
                f"Preferred domains: {s.get('preferred_domains')}; locations: {s.get('preferred_locations')}.\n"
                f"REMEMBERED PREFERENCES: {json.dumps(prefs)}\n"
                f"RELEVANT MEMORY: {json.dumps([m['content'] for m in mem])}")

    @step
    def chat(self, message: str) -> dict:
        sid = self.student["id"]
        history = db.query("SELECT role, content FROM chat_messages WHERE student_id = ? ORDER BY id DESC "
                           "LIMIT 10", (sid,))[::-1]
        db.insert("chat_messages", {"student_id": sid, "role": "user", "content": message, "ts": db.now()})
        used: list[dict] = []
        reply, mode = None, "offline"
        if llm.available():
            try:
                reply = self._llm_loop(message, history, used)
                mode = "llm"
            except Exception as e:  # noqa: BLE001
                llm._fail(e)
                used.clear()
        if reply is None:
            reply = self._offline(message, used)
        db.insert("chat_messages", {"student_id": sid, "role": "assistant", "content": reply,
                                    "tools": [u["tool"] for u in used], "ts": db.now()})
        return {"reply": reply, "tools": used, "mode": mode}

    def _llm_loop(self, message: str, history: list[dict], used: list[dict]) -> str:
        specs = [{"type": "function", "function": {"name": n, "description": d, "parameters": {
            "type": "object", "properties": p, "required": r}}} for n, d, p, r in SPECS]
        messages = [{"role": "system", "content": load_skill(self.skill) + "\n\n" + self._context(message)}]
        messages += [{"role": h["role"], "content": mask_text(h["content"], self.student)} for h in history]
        messages.append({"role": "user", "content": mask_text(message, self.student)})
        for _ in range(5):
            msg = llm.chat_tools(self.name, messages, specs)
            if not msg.tool_calls:
                return msg.content or ""
            messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls]})
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                res = self._run_tool(tc.function.name, args)
                used.append({"tool": tc.function.name, "args": args})
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps(res, default=str)[:4000]})
        return "I looked this up but need you to narrow it down a little. What domain or company?"

    def _offline(self, message: str, used: list[dict]) -> str:
        q = message.lower()

        def use(name, **args):
            used.append({"tool": name, "args": args})
            return self._run_tool(name, args)

        if re.search(r"\b(remember|i prefer|i like|i want only|note that)\b", q):
            use("remember", fact=message)
            return "Noted. I will keep that in mind for future suggestions."
        expr = re.search(r"[\d.]+(?:\s*[-+*/%]\s*[\d.()]+)+", message)
        if expr:
            r = use("calculator", expression=expr.group(0))
            return f"{expr.group(0)} = {r.get('result', r.get('error'))}"
        if re.search(r"applica|status|track|applied", q):
            apps = use("my_applications")["applications"]
            if not apps:
                return "You have not started any applications yet. Open a match and click Apply."
            return "Your applications: " + "; ".join(f"{a['title']} at {a['company']} ({a['stage'].replace('_', ' ').lower()})" for a in apps)
        if re.search(r"skill|learn|lack|improve|gap", q):
            gaps = use("skill_gaps")["gaps"]
            return ("Skills that would open up the most internships for you: " +
                    ", ".join(f"{g['skill']} ({g['count']} postings)" for g in gaps)) if gaps else \
                "Upload your resume first so I can compare your skills with the postings."
        if re.search(r"policy|attendance|noc|hours|rule|grade|marks", q):
            pol = use("college_policy")["policy"]
            lines = [l[2:] for l in pol.splitlines() if l.startswith("- ")]
            words = set(re.findall(r"[a-z]{4,}", q))
            hits = [l for l in lines if words & set(re.findall(r"[a-z]{4,}", l.lower()))] or lines[:3]
            return "From the college policy: " + " ".join(hits[:3])
        words = [w for w in re.findall(r"[a-z]{3,}", q) if w not in
                 {"find", "show", "internship", "internships", "some", "good", "for", "the", "want", "any", "can", "you", "help"}]
        if not words and not self.student.get("preferred_domains"):
            return "Happy to help. Which field are you interested in (for example web, ML, IoT, design), and where would you like to work?"
        res = use("search_internships", query=" ".join(words))
        if not res["results"]:
            res = use("search_internships", query="")
            lead = "I found nothing for that exact search, so here are your best overall matches: "
        else:
            lead = f"I found {res['total']} matching internships. Top ones: "
        return lead + "; ".join(f"{r['title']} at {r['company']} ({r['match']:.0f}% match, "
                                f"{r['eligibility'].replace('_', ' ').lower()})" for r in res["results"][:4])


def skill_gaps(student_id: str) -> list[dict]:
    """Missing skills weighted by how many good matches need them (deterministic)."""
    counts: dict[str, dict] = {}
    for m in db.query("SELECT m.missing, m.score, o.title FROM matches m JOIN opportunities o ON "
                      "o.id = m.opportunity_id WHERE m.student_id = ? AND o.status = 'open' AND m.score >= ?",
                      (student_id, MIN_MATCH_TO_SHOW)):
        for s in m["missing"] or []:
            c = counts.setdefault(s, {"skill": s, "count": 0, "examples": []})
            c["count"] += 1
            if len(c["examples"]) < 3:
                c["examples"].append(m["title"])
    return sorted(counts.values(), key=lambda c: -c["count"])
