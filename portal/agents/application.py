"""Application Processing Agent: prepares the application kit for one
posting (tailored cover letter, resume tips, interview prep, checklist).
It never submits anything to an employer."""

from __future__ import annotations

import json
from datetime import date

from .. import db
from ..guardrails import mask_student, unmask, wrap_untrusted
from ..runtime import Agent, step


class ApplicationProcessingAgent(Agent):
    name = "Application Processing Agent"
    skill = "application-processing"
    tools = ["read_document"]
    description = ("Prepares a tailored cover letter, resume tips and interview questions for a "
                   "chosen internship, plus a document checklist. Never submits applications.")

    def checklist(self, student: dict, opp: dict, kit: dict) -> list[dict]:
        deadline_ok = not opp.get("deadline") or opp["deadline"] >= date.today().isoformat()
        return [
            {"item": "Resume uploaded", "ok": bool(student.get("resume_text"))},
            {"item": "Tailored cover letter", "ok": bool(kit.get("cover_letter"))},
            {"item": "Academic details complete", "ok": all(student.get(k) is not None for k in
                                                            ("usn", "cgpa", "semester", "attendance_pct"))},
            {"item": f"Before deadline ({opp.get('deadline') or 'not stated'})", "ok": deadline_ok},
        ]

    @step
    def prepare(self, record: dict) -> dict:
        student = db.get_student(record["student_id"])
        opp = db.get_opportunity(record["opportunity_id"])
        match = record.get("match") or {}
        past = self.memory.recall(student["id"], f"{opp['company']} {opp['title']} application outcome",
                                  k=3)
        self.tool("read_document", {"name": "internship_policy.md"}, record["id"])
        prof = student.get("resume_profile") or {}
        have = match.get("have") or student.get("skills", [])[:4]

        def fallback():
            first_project = (prof.get("projects") or [{}])[0]
            proj = first_project.get("title", "my academic projects")
            cover = (f"Dear Hiring Team at {opp['company']},\n\n"
                     f"I am {{{{STUDENT_NAME}}}}, a semester {student['semester']} {student['department']} "
                     f"student, and I would like to apply for the {opp['title']} internship. "
                     f"I have worked with {', '.join(have[:4]) or 'the core tools of my branch'}, most "
                     f"recently in {proj}. {first_project.get('description', '')[:200]}\n\n"
                     f"I am keen to learn {', '.join((match.get('missing') or [])[:2]) or 'from your team'} "
                     f"and can commit for {opp.get('duration_weeks') or 'the full'} weeks.\n\n"
                     "Thank you for your time.\n\nSincerely,\n{{STUDENT_NAME}}")
            return {"cover_letter": cover,
                    "resume_tips": [f"Move '{proj}' to the top of your projects section."] +
                                   [f"Add the keyword '{m}' only if you have used it." for m in
                                    (match.get("missing") or [])[:2]],
                    "interview_prep": [f"Walk me through {proj}. What was the hardest part?",
                                       f"Why do you want to intern at {opp['company']}?"] +
                                      [f"How have you used {h}?" for h in have[:2]]}

        prompt = ("STUDENT (personal details removed):\n" + json.dumps(mask_student(student)) +
                  "\n\nMATCH ANALYSIS: " + json.dumps({k: match.get(k) for k in
                                                        ("have", "missing", "highlight")}) +
                  "\n\n" + wrap_untrusted(opp) +
                  "\n\nPAST OUTCOMES TO LEARN FROM (memory): " + json.dumps([p["content"] for p in past]) +
                  '\n\nReturn {"cover_letter": "...", "resume_tips": ["..."], "interview_prep": ["..."]}')
        out, mode = self.think(prompt, fallback, record["id"])
        prev = record.get("application") or {}
        kit = {"cover_letter": unmask(out.get("cover_letter", ""), student),
               "resume_tips": out.get("resume_tips", [])[:4],
               "interview_prep": out.get("interview_prep", [])[:5],
               "version": prev.get("version", 0) + 1, "mode": mode, "prepared_at": db.now()}
        kit["checklist"] = self.checklist(student, opp, kit)
        db.update("records", record["id"], {"application": kit, "updated_at": db.now()})
        self.log("kit_prepared", {"version": kit["version"], "memory_used": len(past), "mode": mode},
                 record["id"])
        return kit
