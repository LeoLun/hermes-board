---
name: workflow-worktree
description: Use when implementation is about to start and the work should run in an isolated git worktree with a verified clean baseline.
---

# workflow-worktree

Use this workflow to prepare an isolated implementation environment before code changes begin.

## Required Outcomes

- Create or reuse a safe worktree location.
- Keep worktrees outside normal tracked source flow, or ensure the chosen directory is ignored.
- Install or verify project dependencies when needed.
- Run a baseline verification command before implementation starts.
- Record the chosen branch/worktree path in the running conversation.

## Standard Flow

1. Check whether a worktree already exists for the current change.
2. Prefer `.worktrees/` inside the repo when available and ignored; otherwise use the project's established location.
3. Create a branch name that matches the OpenSpec change or task scope.
4. Run the minimal setup needed for this repository.
5. Verify a clean starting point with the relevant command set.
6. Hand off to `workflow-plan` or `workflow-implement`.

## Guardrails

- Do not start implementation on the main working tree unless the user explicitly asks for it.
- Do not skip baseline verification.
- If the baseline is already failing, stop and report that before proceeding.
