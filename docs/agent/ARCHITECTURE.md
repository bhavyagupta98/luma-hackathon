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
60-second Ed25519 JWT with organization, role, and scopes
   |
   v
execute_server_action(token, server_id, start|stop)
   |
   +-- verify signature, issuer, audience, expiry, and issuance record
   +-- consume token once
   +-- verify operator/server assignment
   +-- update simulated SQLite server state
   `-- audit and return spoken_message
```

The backend exposes both stages over MCP. Capture, transcription, and intent
parsing are intentionally outside this phase. The local pilot CLI supplies an
already-recorded WAV and an explicit action.

An `org_admin` token may instead be consumed by `add_organization_user`. That
transaction validates organization scope, creates the identity and device,
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

- `authenticate_voice` — derives the operator from the device, verifies the
  voice, audits the attempt, and returns a signed one-action token.
- `execute_server_action` — consumes a token and starts or stops an assigned
  simulated server.
- `add_organization_user` — consumes a fresh admin token and requires the
  organization, new user ID/name/role/device, and server assignments.
- `describe_user_registration` — exact required fields and supported roles.
- `verify_voice_authentication` — developer diagnostic for issued tokens.
- `describe_pilot` — seeded IDs, allowed actions, and limitations.
- `list_voice_auth_events` and `list_server_action_events` — developer audit
  inspection.
- `list_user_admin_events` — developer user-administration audit inspection.

## Role Model

- `org_admin` receives `server:control`, `organization:members:create`, and
  `organization:admins:create` scopes.
- `operator` receives only `server:control`.

The first admin is created with the local-only `luma-bootstrap-admin` command.
Subsequent users are added by a voice-authenticated admin over MCP. User and
device IDs are globally unique in this pilot, so one user belongs to one
organization.

## Security Boundary

The token prevents caller-supplied operator IDs from becoming identity and
binds the verified operator to a trusted device. Enrollment is local-only so an
unauthenticated MCP caller cannot replace voice profiles.

This is still demo authentication. It lacks challenge-response, anti-replay,
synthetic-speech detection, production key management, and OAuth protection on
the MCP transport. Every refusal remains a structured, speakable result.
