---
name: internship-evaluation
description: Rate the technical depth of an intern's work and the quality of the final report on a 0-10 scale with a justification and CO attainment. Use when drafting the final internship evaluation for the coordinator's grade sign-off.
version: 1.0.0
owner: Evaluation Agent
---

# Internship evaluation

Rubric (100 marks):

| Criterion | Marks | Who scores it |
|-----------|-------|---------------|
| Weekly progress & consistency | 25 | Python (logs, hours) |
| Technical depth & deliverables | 30 | You: `technical` 0-10, x3 |
| Industry mentor evaluation | 25 | Mentor score 0-10, x2.5 |
| Final report & presentation | 20 | You: `report` 0-10, x2 |

Grade: S >= 90, A >= 80, B >= 70, C >= 60, D >= 50, else F (Python).

**Inputs:** rubric, course outcomes, weekly evidence (tasks, artifact
links, mapped COs), final report summary, mentor feedback, faculty remarks.

**Tools:** `read_document` (internship policy).

## Procedure
1. `technical`: depth and difficulty of the work and whether artifacts
   (repos, demos, documents) back it up. 8+ needs real artifacts.
2. `report`: clarity, structure, reflection on learning, CO coverage.
3. `justification`: 3-4 sentences citing specific weeks.
4. `co_attainment`: Met / Partially met / Not met for CO1-CO4.
5. If faculty remarks are given, re-assess with them in mind.

## Output
`{"technical": 0-10, "report": 0-10, "justification": "...", "co_attainment": {"CO1": "Met"}}`

## Rules
- Do not compute marks, totals or the letter grade.
- The grade is a draft until the coordinator signs off the grade.
- Rate only on evidence. Missing evidence lowers the rating.
