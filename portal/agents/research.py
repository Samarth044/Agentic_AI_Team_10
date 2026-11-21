"""Company Research Agent (course concept: deep research).

question -> search -> extract -> compare -> synthesize, with an evidence
table. The briefing may only cite evidence rows (E1, E2, ...). Results are
cached for a week per company."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from .. import db
from ..guardrails import audit
from ..runtime import Agent, step


class CompanyResearchAgent(Agent):
    name = "Company Research Agent"
    skill = "company-research-summary"
    tools = ["wikipedia_summary", "sql_query"]
    description = ("Researches a company for students: public sources plus the portal's own history, "
                   "an evidence table and a short cited briefing.")

    @step
    def run(self, company: str, force: bool = False) -> dict:
        company = re.sub(r"[^A-Za-z0-9 &().-]", "", company).strip()[:60]
        if not company:
            raise ValueError("company name required")
        cached = db.one("SELECT * FROM research WHERE company = ?", (company,))
        if cached and not force and datetime.fromisoformat(cached["ts"]) > \
                datetime.now(timezone.utc) - timedelta(days=7):
            return cached["data"]
        steps = []

        def note(phase: str, text: str) -> None:  # research loop stage, visible live in the log
            steps.append({"phase": phase, "text": text})
            audit("loop", self.name, phase.upper(), {"text": text})

        questions = [f"What does {company} do?", f"What internships does {company} offer our students?",
                     f"How have our students fared with {company} before?",
                     f"Are there any risk signals about {company} postings?"]
        note("Question", " / ".join(questions))

        base = company.split("(")[0].strip()
        wiki = self.tool("wikipedia_summary", {"topic": base})
        if not wiki.get("found") and " " in base:
            wiki = self.tool("wikipedia_summary", {"topic": base.split()[0]})
        like = base.replace("'", "")
        posts = self.tool("sql_query", {"sql": "SELECT id, title, stipend, duration_weeks, min_cgpa, flags, "
                                               f"source FROM opportunities WHERE company LIKE '%{like}%'"}
                          ).get("rows", [])
        hist = self.tool("sql_query", {"sql": "SELECT r.stage FROM records r JOIN opportunities o ON "
                                              f"r.opportunity_id = o.id WHERE o.company LIKE '%{like}%'"}
                         ).get("rows", [])
        note("Search", f"Wikipedia: {'found' if wiki.get('found') else 'no page'}; "
                       f"portal: {len(posts)} postings, {len(hist)} applications")
        ev = []
        if wiki.get("found"):
            for s in re.split(r"(?<=\.)\s+", wiki.get("extract", ""))[:2]:
                ev.append({"claim": s, "source": "Wikipedia", "url": wiki.get("url", ""), "confidence": "Medium"})
        for p in posts:
            ev.append({"claim": f"{p['title']}: {p['stipend']}, {p['duration_weeks'] or '?'} weeks, "
                                f"min CGPA {p['min_cgpa'] or 'not stated'}",
                       "source": f"Portal posting ({p['source']})", "url": "",
                       "confidence": "High" if p["source"] in ("campus", "faculty") else "Medium"})
            if p["flags"]:
                ev.append({"claim": f"Posting flagged: {', '.join(p['flags'])}", "source": "Portal safety checks",
                           "url": "", "confidence": "High"})
        if hist:
            stages = sorted({h["stage"].replace("_", " ").lower() for h in hist})
            ev.append({"claim": f"{len(hist)} student application(s) tracked; stages: {', '.join(stages)}",
                       "source": "Portal records", "url": "", "confidence": "High"})
        for i, e in enumerate(ev, 1):
            e["id"] = f"E{i}"
        note("Extract", f"{len(ev)} evidence rows")
        stipends = [int(re.sub(r"\D", "", p["stipend"])) for p in posts
                    if re.search(r"\d", p["stipend"] or "") and not re.search(r"(?i)fee", p["stipend"])]
        comparison = (f"Stipend ₹{min(stipends):,} to ₹{max(stipends):,} per month across {len(stipends)} "
                      "posting(s)" if stipends else "No stipend data to compare")
        note("Compare", comparison)
        gaps = [q for q, ok in zip(questions, [wiki.get("found"), posts, hist, True]) if not ok]

        def fallback():
            return {"briefing": " ".join(f"{e['claim']} [{e['id']}]" for e in ev[:5]) or
                    f"No evidence found for {company}.",
                    "recommendation": "Check the company's careers page before applying."}

        out, mode = self.think(f"COMPANY: {company}\nQUESTIONS: {questions}\nEVIDENCE: {json.dumps(ev)}\n"
                               f"COMPARISON: {comparison}\nUNANSWERED: {gaps}\n"
                               'Return {"briefing": "max 110 words, [E#] after every claim", '
                               '"recommendation": "one sentence for the student"}', fallback)
        note("Synthesize", "Briefing written from the evidence table only")
        data = {"company": company, "evidence": ev, "comparison": comparison, "unanswered": gaps,
                "briefing": out.get("briefing", ""), "recommendation": out.get("recommendation", ""),
                "steps": steps, "mode": mode, "researched_at": db.now()}
        db.execute("INSERT INTO research (company, data, ts) VALUES (?, ?, ?) ON CONFLICT(company) "
                   "DO UPDATE SET data = excluded.data, ts = excluded.ts",
                   (company, json.dumps(data), db.now()))
        self.log("researched", {"company": company, "evidence": len(ev), "mode": mode})
        return data
