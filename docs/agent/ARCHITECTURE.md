# Architecture

## Product Boundary

Luma targets the hackathon's **No App** track. A datacenter operator authenticates
by voice and requests one capability: simulated server power control. The only
supported actions are `start` and `stop`. There is no dashboard, visual
confirmation, or manual approval in the core flow, and no real infrastructure
integration.

## Backend Flow

```text
PCM WAV + trusted device ID
   |
   v
local ECAPA-TDNN speaker verification
   |
   v
60-second Ed25519 JWT with organization, roles, permissions, and one task
   |
   v
execute_task(task, authorization_signature, task-specific fields)
   |
   +-- verify signature, issuer, audience, expiry, issuance, and exact task
   +-- consume token once
   +-- verify operator/server assignment
   +-- update simulated SQLite server state
   `-- audit and return spoken_message
```

The backend exposes both stages over MCP. Capture, transcription, and intent
parsing are intentionally outside this phase. The local pilot CLI supplies an
already-recorded WAV and an explicit action.

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

- `execute_task` — authenticates voice for one requested task or consumes the
  resulting signature to perform `server.start`, `server.stop`, or `user.add`.
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
