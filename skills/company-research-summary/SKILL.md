---
name: company-research-summary
description: Reusable research-summary skill. Turn an evidence table about a company into a short, cited briefing for a student deciding whether to apply. Use for any "tell me about this company" research request.
version: 1.0.0
owner: Company Research Agent
---

# Research summary

**Inputs:** the research questions, an evidence table (`E1`, `E2`, ... with
claim, source, confidence), a comparison line and unanswered questions.

## Procedure
1. Answer each question in order using only evidence rows.
2. Put the evidence id in brackets after every claim, e.g. `[E2]`.
3. Say plainly which questions could not be answered.
4. End with one practical recommendation for the student.

## Output
`{"briefing": "max 120 words with [E#] citations", "recommendation": "one sentence"}`

## Rules
- No claim without an evidence id. Do not use outside knowledge.
- Prefer High-confidence rows when rows disagree, and mention the conflict.
- If a row says a posting is flagged (scam or injection), the
  recommendation must warn the student.
