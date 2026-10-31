---
name: workflow-implement
description: Use when an approved OpenSpec change and execution plan are ready, and the work should be implemented with disciplined verification.
---

# workflow-implement

Use this workflow to execute planned work against the approved OpenSpec artifacts.

## Required Outcomes

- Treat `docs/ai-workflows/openspec/` as the single source of truth for scope and behavior.
- Follow the current plan from `docs/ai-workflows/plans/` when one exists.
- Use test-first or verification-first discipline for behavior changes whenever the repository supports it.
- Keep changes small, focused, and reversible.
- Update task progress in the relevant planning artifact when a task is truly complete.

## Standard Flow

1. Read the current OpenSpec artifacts and the execution plan.
2. Choose the next smallest unfinished task.
3. Add or run the verification that proves the task is incomplete.
4. Implement the minimum code change required.
5. Re-run verification, then move to the next task.
6. When implementation reveals a spec gap, stop and send the change back to `workflow-spec`.

## Guardrails

- Do not freehand new product behavior outside OpenSpec.
- Do not claim completion without fresh verification evidence.
- Do not batch unrelated changes into one implementation step.
- If the repo cannot support automated tests for a step, state the manual verification path explicitly.
