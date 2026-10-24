---
name: test-datacenter
description: Test Luma speaker verification, signed tokens, simulated server control, SQLite state, audit behavior, and MCP tools.
---

# Test Datacenter Voice Control

Run:

```bash
ruff check .
pytest -q
```

Cover matching and non-matching voices, signature tampering, 60-second session
expiry, idempotent requests, assigned and unassigned servers, restart/fix
state transitions, local first-admin bootstrap, admin/operator role boundaries,
complete user registration, independent new-user enrollment, speakable
refusals, audit rows, and offline local-model loading. Confirm every signature
has backend-derived `roles`, task-scoped `permissions`, and allowed tasks. Use
an isolated SQLite database and signing key per test.
