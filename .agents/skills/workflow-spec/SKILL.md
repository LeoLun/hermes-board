---
name: workflow-spec
description: Use when starting a new change, refining requirements, comparing approaches, or creating/updating OpenSpec artifacts before implementation.
---

# workflow-spec

Use this workflow when the goal is to turn an idea into implementable OpenSpec artifacts.

## Required Outcomes

- Treat `docs/ai-workflows/openspec/*.md` and `docs/ai-workflows/openspec/changes/*/*.md` as the authoritative source.
- Clarify intent, scope, constraints, and success criteria before implementation.
- Present 2-3 viable approaches with a recommendation when the solution shape is still open.
- Create or update the relevant `docs/ai-workflows/openspec/changes/<change>/` artifacts: `proposal.md`, `specs/*/spec.md`, `design.md`, `tasks.md`.
- The repository root `openspec/` path may still be used by tools, but it is only a compatibility symlink.
- 用中文输出相关内容

## Standard Flow

1. Explore the current repository and existing OpenSpec changes before asking questions.
2. If the request is still ambiguous, ask only the minimum clarifying questions needed to define the change.
3. Decide whether to create a new change or continue an existing one.
4. Capture the final, implementation-facing decisions in OpenSpec artifacts.
5. End by pointing the next step to `workflow-worktree` or `workflow-plan`.

## Guardrails

- Do not implement code in this workflow.
- Do not create parallel requirement notes outside OpenSpec for the same change.
- Do not leave partially updated artifacts with conflicting scope or terminology.
- Prefer continuing an existing change when the request is clearly part of it.
