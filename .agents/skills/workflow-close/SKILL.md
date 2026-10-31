---
name: workflow-close
description: Use when implementation is finishing and the change needs review, final verification, branch wrap-up, and OpenSpec archive handling.
---

# workflow-close

Use this workflow to finish a change cleanly after implementation.

## Required Outcomes

- Run final verification before any completion claim.
- Review the delivered change against the OpenSpec scope and acceptance criteria in `docs/ai-workflows/openspec/`.
- Summarize remaining risks, follow-ups, or intentionally deferred work.
- Archive the completed OpenSpec change when the work is ready.
- Leave the branch or worktree in a clear handoff state.

## Standard Flow

1. Re-read the relevant OpenSpec artifacts and the final implementation diff.
2. Run final verification commands.
3. Review for requirement coverage, regressions, and documentation drift.
4. Prepare merge or handoff guidance.
5. Archive the OpenSpec change when appropriate.

## Guardrails

- Do not archive a change whose implementation obviously diverges from its OpenSpec artifacts.
- Do not skip final verification because intermediate checks passed.
- Do not describe work as complete if review uncovered unresolved issues.
