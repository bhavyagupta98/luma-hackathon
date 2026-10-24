# Agent Guide

This file is the shared entry point for coding agents working in this repository.
Keep it current as the project and its toolchain evolve.

## Start Here

1. Read `README.md` and `docs/agent/CONTEXT.md`.
2. Check `git status --short` before editing.
3. Inspect the relevant code and tests before proposing a change.
4. Preserve user changes and avoid unrelated rewrites.
5. Record durable architectural decisions in `docs/agent/DECISIONS.md`.

## Working Agreement

- Prefer small, focused changes that are easy to review.
- Follow existing project conventions; do not introduce a new dependency or
  framework without a clear need.
- Never commit credentials, tokens, private keys, or local environment files.
- Do not run destructive commands or rewrite git history unless explicitly
  requested.
- Update documentation when behavior, setup, or architecture changes.
- Add or update tests for behavior changes when a test suite exists.

## Verification

The project toolchain has not been selected yet. Once it is, replace this
section with the exact install, lint, type-check, test, and build commands.

Until then:

- Review `git diff --check` for whitespace errors.
- Review `git diff` for unintended changes.
- Run every relevant check introduced with the chosen stack.

## Repository Map

- `README.md` — project overview and human-facing setup.
- `CLAUDE.md` — Claude-specific entry point.
- `.claude/commands/` — reusable Claude workflows.
- `docs/agent/CONTEXT.md` — current goals, constraints, and project state.
- `docs/agent/DECISIONS.md` — lightweight architecture decision log.
- `docs/agent/HANDOFF.md` — optional work-in-progress handoff notes.

## Keeping This Useful

Prefer concrete commands and repository-specific facts over generic advice.
Remove placeholders as soon as the application stack is established.
