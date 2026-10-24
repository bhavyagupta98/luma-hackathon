# Claude Code Instructions

Follow [`AGENTS.md`](AGENTS.md) as the canonical repository guide.

Before making changes:

1. Read `AGENTS.md` and `docs/agent/CONTEXT.md`.
2. Inspect the working tree and the files related to the request.
3. State assumptions when the repository does not yet establish an answer.

While working, keep changes focused, preserve uncommitted user work, and verify
the result with the repository's documented checks. Update the agent documents
when you learn information that will help future sessions.

Useful project commands:

- `/bootstrap` — orient to the repository before starting work.
- `/check` — run the appropriate verification and review the diff.
- `/handoff` — summarize unfinished work for the next session.

Project-specific skills live in `.claude/skills/` and cover datacenter control,
voice authentication, testing, and No App validation. Use the relevant skill
whenever changing or validating the authorization flow.
