"""Opportunity Discovery Agent: aggregates postings, removes duplicates,
blocks unsafe ones, and ranks every open posting for a student with LLM
matching (relevance, skills you have, skills you lack, how to improve)."""

from __future__ import annotations

import json
import re

from .. import db, taxonomy
from ..config import NOTIFY_MATCH
from ..guardrails import mask_student, posting_flags
from ..notify import notify_student
from ..runtime import Agent, parallel, step
from .eligibility import EligibilityVerificationAgent

CHUNK = 16


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def required_skills(opp: dict) -> list[str]:
    return opp.get("required_skills") or taxonomy.find_skills(f"{opp['title']} {opp['description']}")


def split_skills(student_skills: list[str], required: list[str]) -> tuple[list[str], list[str]]:
    have, missing = [], []
    for r in required:
        (have if any(taxonomy.same(r, s) for s in student_skills) else missing).append(r)
    return have, missing


def preference_fit(student: dict, opp: dict) -> int:
    """Deterministic: location / remote preference."""
    locs = [l.strip().lower() for l in (student.get("preferred_locations") or "").split(",") if l.strip()]
    where = f"{opp.get('location', '')} {opp.get('mode', '')}".lower()
    if opp.get("mode") == "remote" or "remote" in where:
        return 100 if student.get("open_to_remote") else 50
    if not locs:
        return 70
    return 100 if any(l in where for l in locs) else 40


def heuristic_match(student: dict, opp: dict) -> dict:
    req = required_skills(opp)
    have, missing = split_skills(student.get("skills") or [], req)
    skills_fit = round(100 * len(have) / len(req)) if req else 40
    words = set(re.findall(r"[a-z]{3,}", ((student.get("preferred_domains") or "") + " " +
                " ".join((student.get("resume_profile") or {}).get("domains", []))).lower()))
    words -= {"and", "the", "development", "systems"}
    text = f"{opp['title']} {opp['description']}".lower()
    hits = sum(1 for w in words if w in text)
    role_fit = min(100, 35 + 25 * hits)
    why = (f"You already have {', '.join(have[:4])}, which this role uses." if have
           else "Few of the listed skills appear in your resume yet.")
    improve = (f"Learn {', '.join(missing[:3])} to close the gap." if missing
               else "You cover every listed skill; highlight your best project.")
    return {"skills_fit": skills_fit, "role_fit": role_fit, "have": have, "missing": missing,
            "why": why, "improve": improve, "highlight": ""}


class OpportunityDiscoveryAgent(Agent):
    name = "Opportunity Discovery Agent"
    skill = "opportunity-discovery"
    tools = ["campus_postings", "live_job_boards"]
    description = ("Aggregates internships from the college and public job boards, removes "
                   "duplicates, blocks scams, and ranks every posting for each student.")

    # ------------------------------------------------------------ postings
    def store_posting(self, p: dict) -> tuple[str, str]:
        """Insert/update one posting. Returns (id, outcome)."""
        key = (_norm(p["title"]), _norm(p["company"]))
        for o in db.query("SELECT id, title, company FROM opportunities"):
            if o["id"] != p["id"] and (_norm(o["title"]), _norm(o["company"])) == key:
                self.log("duplicate_skipped", {"id": p["id"], "duplicate_of": o["id"]})
                return o["id"], "duplicate"
        flags = posting_flags(p)
        row = {k: p.get(k) for k in ("title", "company", "location", "mode", "duration_weeks",
                                     "stipend", "deadline", "description", "required_skills",
                                     "min_cgpa", "max_active_backlogs", "eligible_branches",
                                     "min_semester", "source", "url", "posted_by")}
        row.update({"flags": flags, "status": "blocked" if flags else "open",
                    "retrieved_at": db.now()})
        if flags:
            self.log("posting_blocked", {"id": p["id"], "flags": flags})
        if db.get_opportunity(p["id"]):
            db.update("opportunities", p["id"], row)
            return p["id"], "updated"
        db.insert("opportunities", {"id": p["id"], **row})
        db.set_meta("opps_changed", db.now())
        return p["id"], "blocked" if flags else "added"

    @step
    def sync_boards(self) -> dict:
        domains = set()
        for s in db.query("SELECT preferred_domains FROM students"):
            domains |= {d.strip() for d in (s["preferred_domains"] or "").split(",") if d.strip()}
        res = self.tool("live_job_boards", {"keywords": sorted(domains)[:6] or ["software"]})
        counts: dict[str, int] = {}
        reasons: dict[str, int] = {}
        for p in res.get("postings", []):
            why_not = self.not_relevant(p)
            if why_not:
                counts["skipped"] = counts.get("skipped", 0) + 1
                key = why_not.split(" (")[0]
                reasons[key] = reasons.get(key, 0) + 1
                continue
            p["required_skills"] = p.get("required_skills") or taxonomy.find_skills(
                f"{p['title']} {p['description']}")[:8]
            _, outcome = self.store_posting(p)
            counts[outcome] = counts.get(outcome, 0) + 1
        if reasons:  # one summary line instead of one line per skipped posting
            self.log("postings_filtered", {"skipped": sum(reasons.values()),
                                           "reasons": ", ".join(f"{k}: {v}" for k, v in reasons.items())})
        db.set_meta("boards_synced", db.now())
        self.log("boards_synced", {"fetched": res.get("count", 0), **counts,
                                   "error": res.get("error", "")})
        return {"fetched": res.get("count", 0), **counts, "error": res.get("error")}

    _NON_ENGLISH = re.compile(r"(?i)\b(praktikum|praktikant|werkstudent|stagiaire|afstudeerstage|"
                              r"stage\b|m/w/d|w/m/d|bewerbung|unternehmen)")
    _INDIA = re.compile(r"(?i)india|bengaluru|bangalore|pune|hyderabad|chennai|mumbai|delhi|noida|"
                        r"gurgaon|gurugram|kolkata|hubballi|dharwad|anywhere|worldwide|apac|asia")

    def not_relevant(self, p: dict) -> str:
        """Board postings worth showing to an Indian engineering student: English,
        reachable (India or remote-worldwide), and actually technical."""
        text = f"{p['title']} {p.get('description', '')}"
        loc = p.get("location") or ""
        if self._NON_ENGLISH.search(p["title"]):
            return "not in English"
        restricted = re.search(r"(?i)\b(usa?|united states|uk|europe|eu|germany|canada|latam|americas)\b", loc)
        if not self._INDIA.search(loc) and not (p.get("mode") == "remote" and not restricted):
            return f"location not reachable ({loc})"
        if len(taxonomy.find_skills(text)) < 2:
            return "not a technical role"
        return ""

    # ------------------------------------------------------------ ranking
    def _rank_chunk(self, student: dict, chunk: list[dict]) -> tuple[dict, str]:
        listing = [{"id": o["id"], "title": o["title"], "company": o["company"],
                    "location": o["location"], "required_skills": required_skills(o),
                    "description": (o["description"] or "")[:350]} for o in chunk]
        prompt = ("STUDENT (personal details removed):\n" + json.dumps(mask_student(student)) +
                  "\n\n<postings>\n" + json.dumps(listing) + "\n</postings>\n\n"
                  'Return {"matches": [{"id", "skills_fit": 0-100, "role_fit": 0-100, '
                  '"have": [skills the student has that the posting needs], '
                  '"missing": [skills the posting needs that the student lacks], '
                  '"why": "1-2 sentences, second person", "improve": "1 sentence", '
                  '"highlight": "which of the student\'s projects to mention"}]} for EVERY posting.')
        data, mode = self.think(prompt, lambda: {"matches": [{"id": o["id"], **heuristic_match(student, o)}
                                                            for o in chunk]})
        return {m.get("id"): m for m in data.get("matches", []) if isinstance(m, dict)}, mode

    @step
    def run(self, student: dict, full: bool = True) -> dict:
        """Rank open postings for one student. full=False only sends postings that are
        new or changed since the last match to the model (keeps API use low)."""
        opps = self.tool("campus_postings", {}).get("postings") or []
        opps = [o for o in opps if o.get("status", "open") == "open"]
        opps += db.query("SELECT * FROM opportunities WHERE status = 'open' AND source NOT IN ('campus', 'faculty')")
        if not student.get("skills"):
            return {"ranked": 0, "eligible": 0, "new_strong": 0}
        stored = {m["opportunity_id"]: m for m in db.query("SELECT * FROM matches WHERE student_id = ?",
                                                             (student["id"],))}
        todo = opps if full else [o for o in opps if o["id"] not in stored
                                  or (o.get("retrieved_at") or "") > (stored[o["id"]]["computed_at"] or "")]
        self.log("plan", {"postings": len(opps), "to_rank": len(todo), "cached": len(opps) - len(todo)})
        chunks = [todo[i:i + CHUNK] for i in range(0, len(todo), CHUNK)]
        results = parallel(lambda c: self._rank_chunk(student, c), chunks, workers=2) if chunks else []
        todo_ids = {o["id"] for o in todo}
        llm_by_id, modes = {}, set()
        for by_id, mode in results:
            llm_by_id.update(by_id)
            modes.add(mode)
        elig_all = EligibilityVerificationAgent().check_many(student, opps)["results"]
        eligible, new_hits = 0, []
        known = student.get("skills") or []
        resume = (student.get("resume_text") or "").lower()
        for o in opps:
            if o["id"] not in todo_ids:  # unchanged: keep the stored AI analysis, re-check rules only
                elig = elig_all[o["id"]]
                eligible += elig["status"] == "ELIGIBLE"
                db.update("matches", stored[o["id"]]["id"], {"eligibility": elig})
                continue
            h = heuristic_match(student, o)
            m = {**h, **{k: v for k, v in llm_by_id.get(o["id"], {}).items() if v not in (None, "")}}
            # Verify the LLM's "have" list against the real profile: anything not
            # shown in the skills or resume text moves to "missing" (no hallucinated skills).
            shown = lambda x: any(taxonomy.same(x, s) for s in known) or bool(  # noqa: E731
                re.search(taxonomy._pattern(x), resume))
            claimed = [taxonomy.norm(x) for x in (m.get("have") or []) + (m.get("missing") or [])]
            m["have"] = list(dict.fromkeys(x for x in claimed if shown(x)))
            m["missing"] = list(dict.fromkeys(x for x in claimed if not shown(x)))
            clamp = lambda v: max(0, min(100, int(float(v))))  # noqa: E731
            # skills fit is the share of required skills the student really has; no evidence = low
            n_have, n_miss = len(m["have"]), len(m["missing"])
            sk = round(100 * n_have / (n_have + n_miss)) if n_have + n_miss else 15
            rf, pf = clamp(m["role_fit"]), preference_fit(student, o)
            score = round(0.55 * sk + 0.30 * rf + 0.15 * pf, 1)  # final score is Python, not LLM
            elig = elig_all[o["id"]]
            eligible += elig["status"] == "ELIGIBLE"
            row = {"score": score, "skills_fit": sk, "role_fit": rf, "pref_fit": pf,
                   "have": m["have"], "missing": m["missing"],
                   "why": m.get("why", ""), "improve": m.get("improve", ""),
                   "highlight": m.get("highlight", ""), "eligibility": elig,
                   "mode": "llm" if o["id"] in llm_by_id else "offline", "computed_at": db.now()}
            existing = db.get_match(student["id"], o["id"])
            if existing:
                db.update("matches", existing["id"], row)
                notified = existing["notified"]
            else:
                db.insert("matches", {"student_id": student["id"], "opportunity_id": o["id"], **row})
                notified = 0
            if not notified and score >= NOTIFY_MATCH and elig["status"] == "ELIGIBLE":
                new_hits.append(o)
                db.execute("UPDATE matches SET notified = 1 WHERE student_id = ? AND opportunity_id = ?",
                           (student["id"], o["id"]))
        if new_hits:
            names = ", ".join(f"{o['title']} at {o['company']}" for o in new_hits[:2])
            more = f" and {len(new_hits) - 2} more" if len(new_hits) > 2 else ""
            notify_student(student["id"], f"New strong match: {names}{more}", "#/internships")
        db.update("students", student["id"], {"matched_at": db.now()})
        self.log("matched", {"student": student["id"], "postings": len(opps), "eligible": eligible,
                             "new_strong": len(new_hits), "mode": sorted(modes)})
        return {"ranked": len(todo), "cached": len(opps) - len(todo), "eligible": eligible,
                "new_strong": len(new_hits)}

    # ------------------------------------------------------------ faculty posting
    @step
    def extract_posting(self, text: str) -> dict:
        """Turn a pasted job description into posting fields for the coordinator to review."""
        import sys
        from ..config import ROOT
        sys.path.insert(0, str(ROOT / "mcp-server"))
        from schema import extract_academic_requirements

        def fallback():
            req = extract_academic_requirements(text)
            first = next((l.strip() for l in text.splitlines() if l.strip()), "Internship")
            comp = re.search(r"(?i)\bat ([A-Z][\w&. ]{2,40})", text)
            return {"title": first[:80], "company": comp.group(1).strip() if comp else "",
                    "location": "", "mode": "remote" if re.search(r"(?i)remote", text) else "onsite",
                    "duration_weeks": req["internship_duration_weeks"], "stipend": req["stipend_inr"] or "",
                    "deadline": "", "required_skills": taxonomy.find_skills(text),
                    "min_cgpa": req["min_cgpa"], "max_active_backlogs": req["max_active_backlogs"],
                    "eligible_branches": req["eligible_branches"], "min_semester": req["min_semester"]}

        data, mode = self.think(
            "<posting_text>\n" + text[:6000] + "\n</posting_text>\nExtract the internship posting. "
            'Return {"title", "company", "location", "mode": "onsite|hybrid|remote", '
            '"duration_weeks": int|null, "stipend": str, "deadline": "YYYY-MM-DD"|"", '
            '"required_skills": [lowercase], "min_cgpa": float|null, "max_active_backlogs": int|null, '
            '"eligible_branches": subset of ["CSE","AI","ECE","ME","CE"], "min_semester": int|null}. '
            "Use null when the text does not state a value. Never invent cutoffs.", fallback, fast=True)
        data["required_skills"] = [taxonomy.norm(s) for s in data.get("required_skills") or []]
        data["mode_used"] = mode
        return data
