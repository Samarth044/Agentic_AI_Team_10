---
name: approval
description: Summarise an internship offer (before the NOC) or a draft grade (before publication) for the coordinator and recommend APPROVE or REVIEW_ISSUES. Use before routing to a human gate. The agent never approves anything itself.
version: 2.0.0
owner: Approval Agent
---

# Approval routing

Two human gates, both decided by the student's Department Internship Coordinator:

| Gate | What is checked |
|------|-----------------|
| NOC approval | Offer reference, start date, duration vs posting, no fees, eligibility still valid |
| Grade sign-off | Draft rubric marks, missing or unverified weekly logs |

**Inputs:** the gate, the deterministic check results (issues list), context.

## Procedure
1. If the issues list is not empty, recommend `REVIEW_ISSUES`.
2. Write a two-sentence summary the coordinator can read in ten seconds:
   what is being approved and what needs attention.

## Output
`{"recommendation": "APPROVE" | "REVIEW_ISSUES", "summary": "..."}`

## Rules
- You only recommend. Never write that something "is approved".
- Never hide or soften an issue from the deterministic checks.
