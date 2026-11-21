---
name: progress-tracking
description: Map an intern's weekly logs to course outcomes CO1-CO4 and write a short progress summary with blockers. Use after a weekly log is submitted or verified. The health status is decided by rules, not by this skill.
version: 1.0.0
owner: Progress Tracking Agent
---

# Progress tracking

**Deterministic part (Python):** weekly hours vs the 30-hour target,
missing weeks, and health status:
- `DELAYED` if two or more weeks are missing
- `AT_RISK` if one week is missing or any week is under 30 hours
- `ON_TRACK` otherwise

**Your part:** CO mapping and a narrative.

**Inputs:** course outcomes, weekly logs (week, hours, tasks), the
rule-based status.

**Tools:** `sql_query` (read-only).

## Procedure
1. For each week, list the course outcomes the tasks give evidence for:
   CO1 problem solving / engineering, CO2 modern tools, CO3 documentation
   and communication, CO4 teamwork and ethics.
2. Write a 2-3 sentence `summary` of technical growth, addressed to the intern in
   second person ("You set up…"). Never write in first person.
3. List `blockers` or signs of stagnation (same task repeated, vague logs).

## Output
`{"co_mapping": {"1": ["CO1", "CO2"]}, "summary": "...", "blockers": ["..."]}`

## Rules
- Do not change the rule-based status.
- Only map a CO when the log text gives evidence for it.
