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

```bash
ruff check .
pytest -q
git diff --check
```

`tests/test_local_voice_model.py` is the offline model smoke test. Restore the
pinned files with `python scripts/download_voice_model.py` if it reports a
missing checkpoint.

The repository-local skills in `.claude/skills/` contain implementation,
testing, and No App validation invariants.

## Repository Map

- `README.md` — project overview and human-facing setup.
- `CLAUDE.md` — Claude-specific entry point.
- `.claude/commands/` — reusable Claude workflows.
- `.claude/skills/` — project-specific implementation and validation skills.
- `src/luma_datacenter/` — voice identity, signed authorization, simulated
  server policy, SQLite storage, local pilot commands, and the MCP backend.
- `models/` — pinned local speaker-verification model and provenance.
- `scripts/` — deterministic model download and integrity verification.
- `tests/` — domain, voice-model, signed-token, and MCP acceptance tests.
- `docs/agent/CONTEXT.md` — current goals, constraints, and project state.
- `docs/agent/ARCHITECTURE.md` — component and policy design.
- `docs/agent/DECISIONS.md` — lightweight architecture decision log.
- `docs/agent/HANDOFF.md` — optional work-in-progress handoff notes.

## Keeping This Useful

Prefer concrete commands and repository-specific facts over generic advice.
Remove placeholders as soon as the application stack is established.
