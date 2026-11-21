"""Resume Agent: reads the uploaded resume and builds a structured profile
(summary, skills with evidence, projects, education, suggested roles)."""

from __future__ import annotations

import re

from .. import db, taxonomy
from ..guardrails import mask_text
from ..runtime import Agent, step

_HEADING = re.compile(r"^[A-Z][A-Z &/,-]{3,40}$")


def _sections(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"_top": []}
    cur = "_top"
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _HEADING.match(line) and len(line.split()) <= 5:
            cur = line.lower()
            out[cur] = []
        else:
            out[cur].append(line)
    return out


def heuristic_profile(text: str) -> dict:
    secs = _sections(text)
    skills = taxonomy.find_skills(text)
    lines = text.splitlines()

    def evidence(skill: str) -> str:
        for l in lines:
            if re.search(taxonomy._pattern(skill), l.lower()):
                return l.strip()[:140]
        return ""

    projects, cur = [], None
    for l in next((v for k, v in secs.items() if "project" in k), []):
        if l.startswith(("-", "â€¢", "*")):
            if cur:
                cur["description"] += (" " if cur["description"] else "") + l.lstrip("-â€¢* ")
        else:
            cur = {"title": l, "description": "", "skills": taxonomy.find_skills(l)}
            projects.append(cur)
    for p in projects:
        p["skills"] = sorted(set(p["skills"]) | set(taxonomy.find_skills(p["description"])))
    edu = [{"degree": l, "institution": "", "year": "", "score": ""}
           for l in next((v for k, v in secs.items() if "education" in k), [])][:3]
    achievements = [l.lstrip("-â€¢* ") for k, v in secs.items()
                    if any(w in k for w in ("achievement", "activit", "certif")) for l in v][:6]
    cats = {}
    for s in skills:
        cats[taxonomy.category(s)] = cats.get(taxonomy.category(s), 0) + 1
    domains = [c for c, _ in sorted(cats.items(), key=lambda x: -x[1])][:3]
    return {
        "headline": f"{domains[0] if domains else 'Engineering'} student",
        "summary": (f"Student with {len(skills)} technical skills, strongest in "
                    f"{', '.join(domains) or 'general engineering'}, and {len(projects)} projects."),
        "skills": [{"name": s, "level": "intermediate", "evidence": evidence(s)} for s in skills],
        "projects": projects[:6], "experience": [], "education": edu,
        "certifications": [a for a in achievements if re.search(r"(?i)certif|nptel|belt", a)],
        "achievements": [a for a in achievements if not re.search(r"(?i)certif|nptel|belt", a)],
        "domains": domains, "suggested_roles": [f"{d} intern" for d in domains[:2]],
        "resume_tips": (["Add measurable results (numbers) to each project."]
                        if not re.search(r"\d+%|\d+\+", text) else [])
                       + (["List your tools/skills in a separate SKILLS section."]
                          if not any("skill" in k for k in secs) else []),
    }


class ResumeAgent(Agent):
    name = "Resume Agent"
    skill = "resume-parsing"
    tools = ["extract_resume_text"]
    description = ("Reads the uploaded resume (PDF/DOCX/TXT), extracts skills with evidence, "
                   "projects, education and suggested roles, and builds the student profile.")

    @step
    def run(self, student: dict, filename: str | None = None) -> dict:
        text = student.get("resume_text") or ""
        if filename:
            res = self.tool("extract_resume_text", {"filename": filename})
            if res.get("error"):
                raise ValueError(res["error"])
            text = res["text"]
        if not text.strip():
            raise ValueError("No resume text to analyse")
        masked = mask_text(text, student)
        prompt = ("<resume>\n" + masked[:12000] + "\n</resume>\n\n"
                  "Return JSON with keys: headline, summary (2-3 sentences), "
                  'skills [{"name", "level": "beginner|intermediate|advanced", "evidence": '
                  '"short quote from the resume"}], projects [{"title", "description", "skills": []}], '
                  'experience [{"role", "organization", "duration", "highlights"}], '
                  'education [{"degree", "institution", "year", "score"}], certifications [], '
                  "achievements [], domains [], suggested_roles [], resume_tips [] (max 3).")
        prof, mode = self.think(prompt, lambda: heuristic_profile(text))
        # keep skill names consistent and lowercase; drop empties
        seen, skills = set(), []
        for s in prof.get("skills") or []:
            name = taxonomy.norm(s.get("name", "") if isinstance(s, dict) else str(s))
            if name and name not in seen:
                seen.add(name)
                skills.append(s if isinstance(s, dict) else {"name": name})
                skills[-1]["name"] = name
        prof["skills"] = skills
        # LLMs sometimes return objects where the UI expects strings; flatten them
        flat = lambda v: " · ".join(str(x) for x in v.values() if x) if isinstance(v, dict) else str(v)  # noqa: E731
        for k in ("certifications", "achievements", "domains", "suggested_roles", "resume_tips"):
            prof[k] = [flat(x) for x in prof.get(k) or [] if x]
        for e in prof.get("education") or []:
            for f in ("degree", "institution", "year", "score"):
                if isinstance(e, dict) and re.fullmatch(r"\[.*\]", str(e.get(f, "")).strip()):
                    e[f] = ""  # drop "[University Name]"-style placeholders
        for k in ("summary", "headline"):
            prof[k] = (prof.get(k) or "").replace("{{STUDENT_NAME}}", student["name"].split()[0])
        prof["mode"] = mode
        prof["parsed_at"] = db.now()
        db.update("students", student["id"], {"resume_text": text, "resume_profile": prof,
                                               "skills": [s["name"] for s in skills],
                                               "updated_at": db.now()})
        self.log("resume_parsed", {"student": student["id"], "skills": len(skills),
                                   "projects": len(prof.get("projects") or []), "mode": mode})
        return prof
