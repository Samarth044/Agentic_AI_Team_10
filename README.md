# InternTrack: Internship Application & Tracking Portal (Worklet 10)

*Internship discovery to final grade in one tracked record* (PPT slide 15).

A web portal for students, the department internship coordinator, an industry
mentor and an admin. AI agents do the work behind the scenes; a named human
approves the NOC and the final grade. The 12 course concepts and 14 labs are
built into the backend, not shown as separate demos.

## Run it

```powershell
pip install -r requirements.txt
cd frontend; npm install; npm run build; cd ..
python -m uvicorn portal.main:app --port 8000
```

Open http://127.0.0.1:8000. Put `GROQ_API_KEY=...` in `.env`. Without a working
key every agent falls back to rule-based logic and the UI marks that output "offline".

| Demo login | Password | Role |
|---|---|---|
| ananya@college.edu | student123 | Student (the one demo profile) |
| coordinator@college.edu | faculty123 | Department internship coordinator |
| arjun.mehta@industry.com | mentor123 | Industry mentor |
| admin@college.edu | admin123 | Admin |

On first start the agents read Ananya's resume and match her: **2 AI calls**.
To show the flow live, register a new student and upload
`samples/resumes/priya_sharma.docx`.

**All 12 agents in one click:** agents are event-driven, so after startup only
Resume, Discovery and Eligibility have run. **Agent activity** lists all 12 with
"ran N×" or "waiting" plus what triggers each one. As admin, **▶ Run demo journey**
drives the full lifecycle for real (apply → offer → NOC → logs → report → rating →
grade, plus chat, panel, research, a rule draft and a health check): about 19 AI
calls, under a minute, every run labelled `[Demo]`. It leaves the Zoho internship
free so you can still apply to it live.

**Show the agents working:** click **Show agent log** (top bar, any page). A live
panel shows each run, which agent was called, which skill it loaded, each MCP
tool call, each AI call (model, time, tokens), memory reads/writes and human
decisions. **Agent activity** in the sidebar has the full log with filters and a
per-run trace; the admin also sees the exact prompts and responses.

**Tests:** `python -m pytest tests/test_portal.py` (10 end-to-end tests, offline, tools over real MCP).

## Keeping API use low

- One demo student; the startup sweep makes 2 AI calls.
- gpt-oss models run with low reasoning effort; at most 2 calls at once; back-off on rate limits.
- Re-matching only sends new or changed postings to the AI; unchanged ones keep their stored analysis.
- Changing CGPA / attendance / backlogs re-runs the rules engine only (no AI).
- The Progress Agent calls the AI only when a new weekly log arrives; the scheduler
  re-checks rules without the AI.
- Company research is cached for a week; the Ops diagnosis is cached until signals change.

A full lifecycle (resume → match → panel → research → apply → offer → NOC →
4 weekly logs → report → rating → grade, plus a rule draft and a health check)
took **20 AI calls, about 21k tokens, 39 seconds** in testing.

## The agents (12, plus 4 parallel reviewers)

| Agent | File | What it does |
|---|---|---|
| **Opportunity Discovery** ★ | `portal/agents/discovery.py` | Gathers postings, removes duplicates, blocks scams, ranks each one (match %, have / lack, why, how to improve) |
| **Eligibility Verification** ★ | `portal/agents/eligibility.py` | Versioned rules engine (college policy + employer criteria); lists every shortfall; no AI, so it can't be prompt-injected |
| **Application Processing** ★ | `portal/agents/application.py` | Cover letter, resume tips, interview questions, checklist; never submits |
| **Approval** ★ | `portal/agents/approval.py` | Checks the offer before the NOC and the draft grade before publishing; recommends; enforces who may decide |
| **Progress Tracking** ★ | `portal/agents/progress.py` | Milestones, 30 hrs/week and missing-week checks (rules), CO mapping (AI), AT_RISK / DELAYED |
| **Evaluation** ★ | `portal/agents/evaluation.py` | 100-mark rubric draft; AI rates two parts, Python computes marks and grade |
| Resume Agent | `portal/agents/resume.py` | Parses PDF / DOCX / TXT into skills with evidence, projects, roles, tips |
| Career Assistant | `portal/agents/assistant.py` | Student chat with real function calling and memory |
| Expert Panel (+4 reviewers) | `portal/agents/panel.py` | Skills / academic / safety / career reviewers in parallel |
| Company Research Agent | `portal/agents/research.py` | Cited briefing from an evidence table |
| Policy Agent | `portal/agents/policy.py` | Plain-English rule → tested, versioned rule |
| Ops Agent | `portal/agents/ops.py` | Diagnoses a failed deployment, fixes after approval |

★ = the six Worklet 10 agents from PPT slide 15.

## MCP (concept 5 / lab 5)

`mcp-server/portal_mcp_server.py` is a real MCP server (official Python SDK,
stdio). The portal starts it as a child process and connects with an MCP client
(`portal/mcp_client.py`: `initialize` → `tools/list` → `tools/call`). **Every
agent tool call goes over this connection**: file tools (college documents,
resume text extraction), SQLite tools (read-only queries, student record) and API
tools (campus postings, public job boards, Wikipedia). Each call is logged with
`transport: mcp` and its latency. Admin → *Agents, MCP & runtime → MCP server*
shows the live handshake, the tools the server lists, and lets you call any tool.
External clients work too: `npx @modelcontextprotocol/inspector python mcp-server/portal_mcp_server.py`.

## OpenClaw-style runtime (concept 6 / lab 6)

Modelled on OpenClaw's design, where one Gateway sits in front of an agent runtime
(`portal/runtime.py`):

- **Interface:** the `Gateway` turns every web request, chat message, background
  event and scheduler sweep into a **run** (run id, channel, session).
- **Runtime:** each agent method is a `@step`. It is announced (`called`), timed and
  recorded (`finished` / `failed`), joins the current run, and keeps the run
  across parallel branches.
- **Skills:** `skills/*/SKILL.md`. Only name and description are always known; the
  body is loaded into the prompt when the owning agent runs (`skill_loaded` in the log).
- **Tools:** an allow-list per agent; calls outside it are blocked; calls go over MCP.
- **Memory:** session memory per run (saved with the run) plus long-term memory per
  student in SQLite and a Markdown file `data/memory/<student>.md`.
- **Audit log:** append-only, in SQLite and `logs/portal-audit.jsonl`.

## Where each lab lives

| Lab | Where it is in the product |
|---|---|
| 1 Agent vs chatbot | Coordinator loop GOAL → PLAN → ACT → OBSERVE → IMPROVE on every run (it widens the search when there is no strong match). The Career Assistant asks a clarifying question when a request is vague, then plans and uses tools. |
| 2 Tool-using agent | Career Assistant function calling: calculator, college policy file, internship search, applications, skill gaps. |
| 3 Skill creation | 9 agent skills in `skills/`, including the reusable `company-research-summary`. |
| 4 Memory & retrieval | Session state per run vs. stored reference (preferences, remarks, outcomes) recalled by relevance. Try "remember I only want remote roles" in the chat. |
| 5 MCP-style connector | Real MCP server with File + SQLite + API tools; every agent tool call goes through it. |
| 6 OpenClaw runtime | Gateway → run → agent step → skill → tools → memory → audit (`portal/runtime.py`). |
| 7 Node graph | `portal/graph.py` routes each record through agent nodes and human gates; progress stepper on every record. |
| 8 Parallel swarm | Expert panel review on each internship: 4 reviewers in parallel, merge, critique, resolve. |
| 9 Deep research | Company insights: question → search → extract → compare → synthesize, with sources. |
| 10 Cloud ops agent | Admin → System health: observe, diagnose, apply a whitelisted fix after approval. |
| 11 Agentic SDLC | Eligibility rules: requirement → design → tests → impact preview → human publish → re-check. |
| 12 Safety & governance | NOC / grade gates, role permissions, PII masking, scam and injection blocking, audit, rollback, evaluation checks. |
| 13 Discipline-specific agents | The six Worklet 10 agents. |
| 14 Capstone | The whole portal. Admin → Overview has a live table of all 14 with evidence counts. |

## Notes

- 16 college postings with real company career links (one duplicate and one scam
  with a prompt injection, both caught). Public boards are filtered to English,
  reachable, technical internships. A free Adzuna or JSearch key adds Indian listings.
- Rubric weights (25/30/25/20) and the 30 hrs/week target are placeholders in
  `portal/config.py`; confirm them with the faculty.
