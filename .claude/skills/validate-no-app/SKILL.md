---
name: validate-no-app
description: Validate that Luma's datacenter pilot completes authentication and simulated server control through spoken MCP responses without a worker-facing app.
---

# Validate No App

Trace `authenticate_voice` through `execute_server_action`. Fail validation if
the core flow requires a screen, click, visual confirmation, or manual approval.

Confirm that authentication, approval, and refusal results have non-empty
`spoken_message` values; successful actions change SQLite state; all attempts
are audited; and documentation clearly states that the servers and biometric
authentication are simulations.

For user administration, confirm that a signed admin voice token is required,
the structured call supplies every registration field, and the new person—not
the existing admin—enrolls the new voice profile.
