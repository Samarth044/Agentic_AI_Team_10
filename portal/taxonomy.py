"""Skill vocabulary used by the deterministic fallbacks (resume parsing,
posting extraction, skill matching) when the LLM is unavailable."""

from __future__ import annotations

import re

SKILLS = {
    "Programming": ["python", "java", "c++", "c", "c#", "javascript", "typescript", "go", "kotlin",
                    "embedded c", "matlab", "r", "bash", "sql"],
    "Web": ["react", "angular", "vue", "node.js", "express", "flask", "django", "fastapi", "html",
            "css", "rest api", "graphql", "next.js", "tailwind"],
    "Data & AI": ["machine learning", "deep learning", "nlp", "computer vision", "pandas", "numpy",
                  "scikit-learn", "tensorflow", "keras", "pytorch", "data analysis", "excel",
                  "power bi", "tableau", "statistics", "matplotlib", "llm"],
    "Cloud & DevOps": ["docker", "kubernetes", "aws", "azure", "gcp", "linux", "git", "ci/cd",
                       "jenkins", "terraform", "redis", "mysql", "postgresql", "mongodb", "sqlite"],
    "CS fundamentals": ["data structures", "algorithms", "problem solving", "oop", "dbms",
                        "operating systems", "computer networks"],
    "Electronics": ["arduino", "esp32", "raspberry pi", "iot", "mqtt", "microcontrollers", "can",
                    "pcb design", "kicad", "verilog", "systemverilog", "vhdl", "fpga",
                    "digital electronics", "plc", "sensors", "signal processing"],
    "Mechanical": ["solidworks", "catia", "autocad", "ansys", "fea", "cfd", "cad", "gd&t",
                   "lean manufacturing", "six sigma", "5s", "creo", "fusion 360"],
}

ALIASES = {"js": "javascript", "reactjs": "react", "react.js": "react", "sklearn": "scikit-learn",
           "ml": "machine learning", "dl": "deep learning", "postgres": "postgresql",
           "nodejs": "node.js", "ms excel": "excel", "rest": "rest api", "restful": "rest api",
           "esp-32": "esp32", "pid": "control systems"}

ALL = sorted({s for group in SKILLS.values() for s in group}, key=len, reverse=True)


def _pattern(skill: str) -> str:
    left = r"(?<![a-z0-9])" if skill[0].isalnum() else ""
    right = r"(?![a-z0-9+#])" if skill[-1].isalnum() else ""
    return left + re.escape(skill) + right


def find_skills(text: str) -> list[str]:
    t = (text or "").lower()
    for a, canon in ALIASES.items():
        t = re.sub(_pattern(a), canon, t)
    found = []
    for s in ALL:
        if s in ("c", "r", "go", "can"):  # too ambiguous as bare words; need context
            if not re.search(rf"(?:languages?|skills?)[^\n]*{_pattern(s)}", t) and \
                    not re.search(rf"{_pattern(s)} (?:bus|programming|language)", t):
                continue
        if re.search(_pattern(s), t):
            found.append(s)
    return sorted(set(found), key=lambda x: ALL.index(x))


def category(skill: str) -> str:
    for cat, items in SKILLS.items():
        if skill.lower() in items:
            return cat
    return "Other"


def norm(skill: str) -> str:
    s = skill.strip().lower()
    return ALIASES.get(s, s)


def same(a: str, b: str) -> bool:
    """Equal, or one is a whole word/phrase inside the other
    ("scikit-learn" ~ "scikit-learn library", but "sql" !~ "sqlite")."""
    a, b = norm(a), norm(b)
    if a == b:
        return True
    if len(a) <= 2 or len(b) <= 2:
        return False
    short, long_ = sorted((a, b), key=len)
    return bool(re.search(_pattern(short), long_))
