---
name: validate-no-app
description: Validate that Luma's datacenter pilot completes authentication and simulated server control through spoken MCP responses without a worker-facing app.
---

# Validate No App

Trace `execute_task(task=authenticate)` through the matching functional
`execute_task` call. Fail validation if
the core flow requires a screen, click, visual confirmation, or manual approval.

Confirm that authentication, approval, and refusal results have non-empty
`spoken_message` values; successful actions change SQLite state; all attempts
are audited; and documentation clearly states that the servers and biometric
authentication are simulations.

Confirm the 60-second authorization session contains backend-derived `roles`,
task-scoped `permissions`, and allowed `tasks`; browser-provided grants must
never override signed claims.

For user administration, confirm that a signed admin voice authorization is required,
the structured call supplies every registration field, and the new person—not
the existing admin—enrolls the new voice profile.
