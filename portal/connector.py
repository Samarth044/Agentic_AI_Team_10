"""One MCP-style connector exposing File, SQLite and API tools behind a
single `call(tool, args)` interface with JSON schemas.

Agents never open files, run SQL or call HTTP directly; they go through
this connector, so every tool call is permission-scoped and audited.
`mcp-server/portal_mcp_server.py` publishes the same tools over real MCP."""

from __future__ import annotations

import ast
import asyncio
import io
import json
import operator
import os
import re
import sys
import time
import zipfile

import httpx

from . import db
from .config import DOCS_DIR, RESUME_DIR, ROOT
from .guardrails import audit

# ------------------------------------------------------------ calculator

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
        ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("only numbers and + - * / % ** are allowed")


def calculator(expression: str) -> dict:
    """Safe arithmetic (no eval())."""
    return {"expression": expression, "result": round(_eval(ast.parse(expression, mode="eval").body), 4)}


# ------------------------------------------------------------ file tools

def list_documents() -> dict:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    return {"documents": sorted(p.name for p in DOCS_DIR.iterdir() if p.is_file())}


def read_document(name: str) -> dict:
    """Sandboxed: only files directly inside data/docs can be read."""
    path = (DOCS_DIR / name).resolve()
    if path.parent != DOCS_DIR.resolve() or not path.is_file():
        raise ValueError(f"document '{name}' not found")
    return {"name": name, "content": path.read_text(encoding="utf-8")[:6000]}


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


def extract_resume_text(filename: str) -> dict:
    """Read an uploaded resume (PDF, DOCX or TXT) from the resume store."""
    path = (RESUME_DIR / filename).resolve()
    if path.parent != RESUME_DIR.resolve() or not path.is_file():
        raise ValueError("resume file not found")
    data = path.read_bytes()
    ext = path.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    elif ext == ".docx":
        text = _docx_text(data)
    else:
        text = data.decode("utf-8", "ignore")
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) < 50:
        raise ValueError("could not read text from this file (is it a scanned image?)")
    return {"filename": filename, "chars": len(text), "text": text[:15000]}


# ------------------------------------------------------------ SQLite tools

_ALLOWED_TABLES = {"opportunities", "matches", "records", "approvals", "progress_logs",
                   "evaluations", "rules"}


def sql_query(sql: str) -> dict:
    """Read-only SELECT over portal tables. Writes and the users/students tables are refused."""
    s = sql.strip().rstrip(";")
    if not re.match(r"(?is)^select\b", s) or ";" in s or re.search(
            r"(?i)\b(insert|update|delete|drop|alter|attach|pragma|create|replace)\b", s):
        raise ValueError("only a single read-only SELECT statement is allowed")
    tables = set(re.findall(r"(?i)\b(?:from|join)\s+([a-z_]+)", s))
    if not tables <= _ALLOWED_TABLES:
        raise ValueError(f"tables not allowed: {sorted(tables - _ALLOWED_TABLES)}")
    rows = db.query(s if re.search(r"(?i)\blimit\b", s) else s + " LIMIT 50")
    return {"rows": rows, "count": len(rows)}


def get_student(student_id: str) -> dict:
    s = db.get_student(student_id)
    if not s:
        raise ValueError("unknown student")
    return {k: s[k] for k in ("id", "department", "semester", "cgpa", "active_backlogs",
                              "attendance_pct", "skills", "preferred_domains")}


# ------------------------------------------------------------ API tools

def campus_postings(keyword: str = "") -> dict:
    """Internships posted by the college placement cell / faculty."""
    rows = db.query("SELECT * FROM opportunities WHERE source IN ('campus', 'faculty')")
    if keyword:
        kw = keyword.lower()
        rows = [p for p in rows if kw in f"{p['title']} {p['company']} {p['description']}".lower()]
    return {"postings": rows, "count": len(rows)}


def _from_job(j, source_name: str) -> dict:
    return {"id": f"ext-{j.id}", "title": j.title, "company": j.company,
            "location": j.location or "Remote", "mode": j.remote if j.remote != "unknown" else "remote",
            "duration_weeks": j.internship_duration_weeks, "stipend": j.stipend_inr or "Not stated",
            "deadline": "", "description": (j.description or "")[:2500], "required_skills": [],
            "min_cgpa": j.min_cgpa, "max_active_backlogs": j.max_active_backlogs,
            "eligible_branches": j.eligible_branches, "min_semester": j.min_semester,
            "source": source_name, "url": j.url}


def live_job_boards(keywords: list[str], limit: int = 40) -> dict:
    """Public job boards (Remotive, Arbeitnow, RemoteOK; JSearch / Adzuna India if keys are set),
    filtered to internships. Read-only GET requests."""
    sys.path.insert(0, str(ROOT / "mcp-server"))
    try:
        from schema import SearchQuery, dedupe, enrich_job_for_internship, guess_employment_type
        from adapters.arbeitnow import ArbeitnowAdapter
        from adapters.jsearch import JSearchAdapter
        from adapters.remoteok import RemoteOKAdapter
        from adapters.remotive import RemotiveAdapter
    except Exception as e:  # noqa: BLE001
        return {"postings": [], "count": 0, "error": f"adapters unavailable: {e}"}

    async def run():
        q = SearchQuery(keywords=[f"{k} intern" for k in keywords] + ["intern", "internship"],
                        limit_per_source=60)
        adapters = [RemotiveAdapter(), ArbeitnowAdapter(), RemoteOKAdapter()]
        js = JSearchAdapter(employment_types=["internship"])
        if js.available():
            adapters.append(js)
        res = await asyncio.gather(*(a.search(q) for a in adapters), return_exceptions=True)
        return [j for r in res if isinstance(r, list) for j in r]

    try:
        # the MCP server calls tools from inside its own event loop, so run ours on a thread
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(1) as ex:
            jobs = dedupe(ex.submit(asyncio.run, run()).result(120))
    except Exception as e:  # noqa: BLE001
        return {"postings": [], "count": 0, "error": str(e)[:200]}
    out = [_from_job(enrich_job_for_internship(j), j.source) for j in jobs
           if j.employment_type == "internship" or guess_employment_type(j.title) == "internship"]
    out += adzuna_india(keywords).get("postings", [])
    return {"postings": out[:limit], "count": len(out[:limit])}


def adzuna_india(keywords: list[str]) -> dict:
    """Adzuna India internships (free key: ADZUNA_APP_ID / ADZUNA_APP_KEY)."""
    app_id, key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
    if not (app_id and key):
        return {"postings": [], "count": 0, "note": "Adzuna key not configured"}
    out = []
    for kw in (keywords or ["engineering"])[:3]:
        try:
            r = httpx.get("https://api.adzuna.com/v1/api/jobs/in/search/1", timeout=15, params={
                "app_id": app_id, "app_key": key, "what": f"{kw} intern", "results_per_page": 20,
                "content-type": "application/json"})
            for j in r.json().get("results", []):
                out.append({"id": f"adz-{j['id']}", "title": j.get("title", ""),
                            "company": (j.get("company") or {}).get("display_name", ""),
                            "location": (j.get("location") or {}).get("display_name", "India"),
                            "mode": "onsite", "duration_weeks": None,
                            "stipend": f"₹{int(j['salary_min']):,}/yr" if j.get("salary_min") else "Not stated",
                            "deadline": "", "description": j.get("description", "")[:2500],
                            "required_skills": [], "min_cgpa": None, "max_active_backlogs": None,
                            "eligible_branches": [], "min_semester": None, "source": "adzuna",
                            "url": j.get("redirect_url", "")})
        except Exception:  # noqa: BLE001
            continue
    return {"postings": out, "count": len(out)}


def wikipedia_summary(topic: str) -> dict:
    """Public Wikipedia REST summary (company research)."""
    title = topic.strip().replace(" ", "_")
    try:
        r = httpx.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}",
                      # Wikimedia's robot policy requires a UA with contact info
                      headers={"User-Agent": "InternshipPortal/1.0 (college project; admin@college.edu)"},
                      timeout=10, follow_redirects=True)
        if r.status_code != 200:
            return {"found": False, "topic": topic}
        d = r.json()
        if d.get("type") == "disambiguation":
            return {"found": False, "topic": topic}
        return {"found": True, "topic": topic, "title": d.get("title"),
                "extract": d.get("extract", "")[:1200],
                "url": d.get("content_urls", {}).get("desktop", {}).get("page", "")}
    except Exception as e:  # noqa: BLE001
        return {"found": False, "topic": topic, "error": str(e)[:120]}


# ------------------------------------------------------------ registry

TOOLS = {
    "calculator": (calculator, "Safe arithmetic calculator", "compute",
                   {"expression": {"type": "string"}}, ["expression"]),
    "list_documents": (list_documents, "List college documents (policy, templates)", "file", {}, []),
    "read_document": (read_document, "Read a college document", "file",
                      {"name": {"type": "string"}}, ["name"]),
    "extract_resume_text": (extract_resume_text, "Extract text from an uploaded resume", "file",
                            {"filename": {"type": "string"}}, ["filename"]),
    "sql_query": (sql_query, "Read-only SELECT over portal tables", "sqlite",
                  {"sql": {"type": "string"}}, ["sql"]),
    "get_student": (get_student, "Academic record of one student", "sqlite",
                    {"student_id": {"type": "string"}}, ["student_id"]),
    "campus_postings": (campus_postings, "Internships posted by the college", "api",
                        {"keyword": {"type": "string"}}, []),
    "live_job_boards": (live_job_boards, "Internships from public job boards", "api",
                        {"keywords": {"type": "array", "items": {"type": "string"}}}, ["keywords"]),
    "wikipedia_summary": (wikipedia_summary, "Wikipedia summary of a company", "api",
                          {"topic": {"type": "string"}}, ["topic"]),
}


def list_tools() -> list[dict]:
    return [{"name": n, "description": d, "category": c,
             "input_schema": {"type": "object", "properties": p, "required": req}}
            for n, (_, d, c, p, req) in TOOLS.items()]


USE_MCP = os.getenv("PORTAL_MCP", "1") == "1"


def call(tool: str, args: dict | None = None, actor: str = "agent",
         run_id: str | None = None, record_id: str | None = None) -> dict:
    """Run one tool. Goes over MCP (tools/call to the portal MCP server); falls back
    to running the same function in-process only if the MCP server is down."""
    from . import context
    from .mcp_client import ToolError, Unavailable, client
    if tool not in TOOLS:
        raise ValueError(f"unknown tool {tool}")
    args = args or {}
    run_id = run_id or context.run_id()
    started = time.perf_counter()
    transport = "mcp" if USE_MCP else "in-process"
    try:
        if USE_MCP:
            try:
                result = client.call(tool, args)
            except Unavailable as e:
                audit("guardrail", "MCP client", "mcp_unavailable", {"error": str(e)}, record_id, run_id)
                transport = "in-process (MCP down)"
                result = TOOLS[tool][0](**args)
        else:
            result = TOOLS[tool][0](**args)
        ms = round((time.perf_counter() - started) * 1000)
        # resume text holds personal data: log only its size
        preview = (f"{result.get('chars')} chars" if tool == "extract_resume_text"
                   else json.dumps(result, default=str)[:300])
        audit("tool", actor, tool, {"args": args, "ok": True, "transport": transport, "ms": ms,
                                    "result_preview": preview}, record_id, run_id)
        return result
    except (ToolError, Exception) as e:  # noqa: BLE001
        audit("tool", actor, tool, {"args": args, "ok": False, "transport": transport, "error": str(e)},
              record_id, run_id)
        return {"error": str(e)}
