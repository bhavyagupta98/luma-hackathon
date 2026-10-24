---
name: implement-datacenter
description: Implement or change Luma voice authentication, signed authorization, SQLite state, or simulated datacenter MCP tools.
---

# Implement Datacenter Voice Control

Read `docs/agent/ARCHITECTURE.md` and `docs/agent/DECISIONS.md` first.

Preserve these invariants:

- The operator flow requires no dashboard, visual confirmation, or manual
  approval.
- Every expected result and refusal has a short natural `spoken_message`.
- Derive the operator from the verified token and device mapping; never accept
  a caller-supplied operator ID as identity.
- A voice authorization signature is short-lived, organization-scoped,
  consumable once, and bound to exactly one requested task. Its signed claims
  contain `roles`, task-scoped `permissions`, and `tasks` arrays.
- Only `org_admin` may add users. Creating another admin requires the dedicated
  `organization:admins:create` permission; an operator may never escalate roles.
- The first admin is local-bootstrap only, and every later user must enroll
  their own voice after their identity and device are created.
- Only `start` and `stop` are supported, and they affect seeded SQLite servers,
  never real infrastructure.
- State mutation, token consumption, and auditing stay transactional; retries
  with the same `request_id` are idempotent.
- Keep voice inference offline from pinned `models/` files and keep enrollment
  local-only.
- Never commit signing keys, recordings, voice embeddings, or local databases.
- Do not imply that speaker similarity supplies liveness, replay resistance, or
  production-grade authentication.

Update tests and the decision record when policy changes.
