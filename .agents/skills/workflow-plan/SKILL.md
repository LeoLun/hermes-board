---
name: workflow-plan
description: Use when OpenSpec tasks exist and they need to be expanded into a concrete execution plan before implementation.
---

# workflow-plan

Use this workflow to convert OpenSpec tasks into a decision-complete implementation plan.

## Required Outcomes

- Read the current OpenSpec artifacts from `docs/ai-workflows/openspec/` before planning.
- Produce an execution plan that maps directly to the approved change.
- Save the plan to `docs/ai-workflows/plans/YYYY-MM-DD-<change>.md`.
- Keep the plan implementation-oriented: task order, verification, files or subsystems, and stop conditions.
- Point execution to `workflow-implement`.

## Standard Flow

1. Read `proposal.md`, relevant `specs/*/spec.md`, `design.md`, and `tasks.md`.
2. Identify the smallest safe execution slices.
3. Expand each slice into concrete implementation and verification steps.
4. Call out dependencies, blockers, and assumptions explicitly.
5. Save the final plan under `docs/ai-workflows/plans/`.

## Guardrails

- Do not invent behavior that is missing from OpenSpec; surface the gap and send it back to `workflow-spec`.
- Do not write vague steps like "implement feature" or "test it".
- Do not let the plan become a second source of product truth; it is an execution view over OpenSpec.
