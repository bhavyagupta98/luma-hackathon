# Decision Log

## 2026-10-24 — Use a 60-second authenticated session for two maintenance tasks

- **Status:** Accepted; supersedes the one-task signature decision below.
- **Context:** The worker authenticates first, then may say either “restart
  server X” or “fix server X” without authenticating again for one minute.
- **Decision:** Browser WavLM embeddings are verified against a matching
  SQLite profile. The backend issues an Ed25519 session carrying roles,
  permissions, allowed tasks, organization, device, identity, and expiry.
  Restart and fix calls derive authority exclusively from those signed claims.
- **Consequences:** One session can perform multiple assigned-server tasks for
  60 seconds. The frontend clears its copy at expiry and the backend rejects it
  cryptographically even if a client fails to clear local state.

## 2026-10-24 — Keep language and authorization responsibilities separate

- **Status:** Accepted.
- **Decision:** The browser owns STT/TTS, the gateway performs deterministic
  parsing for the two pilot commands, and the MCP backend owns identity,
  authorization, simulated mutation, and audit. Backend `spoken_message`
  values pass through unchanged.

## 2026-10-24 — Bind voice authorization to one explicit task

- **Status:** Accepted
- **Context:** Authentication and functional work need one MCP task contract,
  with authorization expressed as roles, permissions, and tasks.
- **Decision:** Use `execute_task` for both phases. Voice authentication names
  one intended functional task and returns a short-lived Ed25519 signature over
  `roles`, task-scoped `permissions`, and exactly one allowed `tasks` value.
  Execution verifies all three claims and atomically consumes the signature.
- **Consequences:** A signature for `server.start` cannot be reused for
  `server.stop` or `user.add`. The frontend still performs audio capture,
  transcription, and intent extraction; the backend owns voice matching,
  authorization, mutation, and audit.

## 2026-10-24 — Add organization-scoped voice administration

- **Status:** Accepted
- **Context:** A voice-authenticated administrator must be able to register
  another administrator or non-admin operator.
- **Decision:** Bootstrap the first admin locally. Give `org_admin` tokens
  organization member/admin creation scopes, require all identity, role,
  device, and assignment fields in `add_organization_user`, consume one fresh
  voice token per attempt, and require the new person to enroll their own voice.
- **Consequences:** Role changes are explicit, organization-scoped,
  transactional, idempotent, and audited. Speech interpretation remains a
  frontend responsibility and voice alone is still not production-grade proof.

## 2026-10-24 — Pivot from warehouse handoffs to datacenter control

- **Status:** Accepted
- **Context:** The pilot should demonstrate one simple datacenter task rather
  than warehouse pallet workflows.
- **Decision:** Remove the warehouse/frontend APIs and support one backend
  capability: starting or stopping seeded simulated servers.
- **Consequences:** The database, tools, tests, docs, and skills now use
  operators, devices, servers, assignments, and server action events. No real
  infrastructure is affected.

## 2026-10-24 — Require a signed voice token for every server action

- **Status:** Accepted
- **Context:** Speaker verification must become an authorization boundary, not
  just an informational response.
- **Decision:** Derive the operator from the device, issue a 60-second Ed25519
  JWT after a voice match, and atomically consume it on one start/stop attempt.
- **Consequences:** Callers cannot choose their operator ID, replaying a token
  for a second action is refused, and each action is auditable and idempotent.

## 2026-10-24 — Keep speaker verification and enrollment local

- **Status:** Accepted
- **Context:** The hackathon needs a reproducible demo without a hosted biometric
  provider, and enrollment is a privileged operation.
- **Decision:** Pin SpeechBrain ECAPA-TDNN under `models/`, store only normalized
  embeddings in SQLite, and expose enrollment through a local CLI rather than
  MCP.
- **Consequences:** Runtime inference is offline and raw enrollment audio is not
  persisted by the backend. Replay and synthetic-voice protection remain future
  work.

## 2026-10-24 — Use persistent transactional SQLite simulation

- **Status:** Accepted
- **Context:** No real datacenter database or control plane is available.
- **Decision:** Automatically seed local operators, devices, server assignments,
  and server states. Mutate state and audit in one transaction.
- **Consequences:** The pilot is deterministic and survives restarts, but SQLite
  and the simulated controls are not a production deployment design.
