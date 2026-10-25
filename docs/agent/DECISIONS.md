# Decision Log

## 2026-10-24 — Optional browser enrollment for the demo

- **Status:** Accepted (demo only)
- **Context:** Enrollment was local-only (`luma-enroll-voice`) so no network caller can replace a
  voice profile, but a demo user wants to enroll by speaking into the browser on localhost.
- **Decision:** The gateway accepts `voice_enroll` (up to 5 clips) only when started with
  `LUMA_ALLOW_BROWSER_ENROLL=1` and only from loopback addresses. It enrolls the operator that
  owns the trusted device, using the existing `VoiceAuthService.enroll`. Open
  `auth.html?device=DC-D-100&enroll=1`. Off by default. The page first asks for the spoken name
  (browser speech recognition), and the gateway stores it as the operator's display name only
  after the voice enrollment succeeds, then says "<name>, you are enrolled."
- **Consequences:** Anyone at the gateway computer can overwrite that device's voice profile
  while the flag is on, and enrollment attempts are not written to an audit table. Do not enable
  it in a shared or production deployment.

## 2026-10-24 — Add a voice gateway with 60-second sessions

- **Status:** Accepted
- **Context:** Workers must sign in by voice, hear their name, and then say
  `restart server X` or `fix server X`, with permissions enforced by the backend.
- **Decision:** Add `src/luma_datacenter/gateway/` without changing existing backend
  modules. The earpiece sends recorded audio once; the backend's ECAPA verifier derives the
  operator from the trusted device and the gateway opens a 60-second session carrying the role
  and server permissions (from the database, never the client). Commands arrive as text with the
  session id and are authorized against `server_assignments`; every attempt is audited in
  `server_action_events`. The signed backend token stays server-side.
- **Consequences:** Browser-computed embeddings were dropped because the backend can only
  compare its own ECAPA embeddings. Speech-to-text and text-to-speech run in the browser
  (Whisper and MMS-TTS via Transformers.js, with Chrome's engines as fallback). Restart and fix
  are simulated by leaving the server `running`. Sessions are in memory, so a gateway restart
  signs everyone out. Voice similarity still gives no liveness or replay protection.

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
