# Architecture

## Product Boundary

Luma uses a voice-only browser earpiece. A datacenter worker authenticates once
and requests simulated server maintenance. The only supported actions are
`restart` and `fix`; no real infrastructure is controlled.

## Backend Flow

```text
browser WavLM embedding + trusted device ID
   |
   v
SQLite speaker-profile similarity check
   |
   v
60-second Ed25519 JWT with organization, roles, permissions, and allowed tasks
   |
   v
execute_task(task, authorization_signature, task-specific fields)
   |
   +-- verify signature, issuer, audience, expiry, issuance, and exact task
   +-- verify operator/server assignment
   +-- update simulated SQLite server state
   `-- audit and return spoken_message
```

The backend exposes both stages over MCP. The browser captures audio, computes
the WavLM embedding, transcribes task speech, and speaks results. The gateway
extracts one of the two supported intents and passes the session to MCP.

An `org_admin` may authenticate specifically for `user.add`. The signature is
consumed by a transaction that validates organization scope, creates the
identity and device,
assigns the requested role and servers, and audits the result. The new user
cannot authenticate until they independently enroll their own voice.

## State

SQLite is automatically created and seeded at `data/luma_datacenter.db`.

- `organizations`, `operators`, `organization_memberships`,
  `datacenter_devices`, and `device_contexts` provide scoped identities.
- `servers` and `server_assignments` provide simulated authorization state.
- `operator_voice_profiles` stores normalized embeddings, never raw audio.
- `operator_voice_auth_events` logs every speaker-verification attempt.
- `operator_voice_auth_tokens` records issued and consumed token IDs.
- `server_action_events` logs every action attempt and spoken result.
- `user_admin_events` logs local bootstrap and every user-add attempt.

Server-state mutation, token consumption, and action audit insertion occur in a
single SQLite transaction. `request_id` makes action retries idempotent.

## MCP Tools

- `execute_task` — authenticates voice for a 60-second session or performs
  `server.restart`, `server.fix`, or `user.add`.
- `describe_task_contract` — exact fields for every task and the signed
  `roles`, `permissions`, and `tasks` shape.
- `verify_authorization_signature` — developer diagnostic for issued signatures.
- `describe_pilot` — seeded IDs, allowed actions, and limitations.
- `list_voice_auth_events` and `list_server_action_events` — developer audit
  inspection.
- `list_user_admin_events` — developer user-administration audit inspection.

## Role Model

- `org_admin` may request server-control or user-add permissions.
- `operator` may request only server-control permission.
- Every issued signature contains only the permissions needed for its single
  requested task; adding another admin is rechecked against
  `organization:admins:create` during execution.

The first admin is created with the local-only `luma-bootstrap-admin` command.
Subsequent users are added by a voice-authenticated admin over MCP. User and
device IDs are globally unique in this pilot, so one user belongs to one
organization.

## Security Boundary

The signature prevents caller-supplied operator IDs from becoming identity and
binds the verified operator to a trusted device. Enrollment is local-only so an
unauthenticated MCP caller cannot replace voice profiles.

This is still demo authentication. It lacks challenge-response, anti-replay,
synthetic-speech detection, production key management, and OAuth protection on
the MCP transport. Every refusal remains a structured, speakable result.
