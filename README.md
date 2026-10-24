# Luma Datacenter Voice Control

A screen-independent hackathon pilot that authenticates a datacenter operator's
voice and starts or stops a simulated server through an MCP backend.

The application never controls real infrastructure. Server state, assignments,
voice profiles, tokens, and audit events live in local SQLite.

## Install

Requires Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest -q
```

The backend automatically creates and seeds `data/luma_datacenter.db`. The
local ECAPA-TDNN model is stored under
`models/speechbrain-spkrec-ecapa-voxceleb/`. Restore or verify it with:

```bash
python scripts/download_voice_model.py
```

## Run a Local Voice Pilot

macOS may ask for Terminal microphone access on the first recording. Record
three different enrollment phrases:

```bash
luma-record-voice --output samples/op100-1.wav --seconds 5
luma-record-voice --output samples/op100-2.wav --seconds 5
luma-record-voice --output samples/op100-3.wav --seconds 5
```

If the default microphone is unavailable, inspect devices and select one:

```bash
luma-record-voice --list-devices
luma-record-voice --device 1 --output samples/op100-1.wav
```

Enroll the seeded operator:

```bash
luma-enroll-voice \
  --operator OP-100 \
  --audio samples/op100-1.wav \
  --audio samples/op100-2.wav \
  --audio samples/op100-3.wav
```

`OP-100` is the seeded `org_admin` for `ORG-DEMO`. To create a completely new
organization and its first voice administrator instead, record that person's
samples and run the local-only bootstrap command:

```bash
luma-bootstrap-admin \
  --organization-id ORG-ACME \
  --organization-name "Acme Datacenter" \
  --user-id ADMIN-ACME-1 \
  --name "Bhavya Gupta" \
  --device-id DEV-ACME-1 \
  --audio samples/admin-1.wav \
  --audio samples/admin-2.wav \
  --audio samples/admin-3.wav
```

Bootstrap is not exposed over MCP. It creates the organization, first
`org_admin`, trusted device, audit event, and voice profile locally.

Record a new authentication phrase—not one of the enrollment files—and run one
simulated server action:

```bash
luma-record-voice --output samples/op100-pilot.wav --seconds 5
luma-voice-pilot --audio samples/op100-pilot.wav --action start --server SRV-100
```

To test stopping a server, record another fresh clip because each signed voice
token is valid for only one action:

```bash
luma-record-voice --output samples/op100-stop.wav --seconds 5
luma-voice-pilot --audio samples/op100-stop.wav --action stop --server SRV-200
```

## Run the MCP Backend

```bash
luma-backend-mcp --transport streamable-http --port 8000
```

Connect an MCP client to `http://127.0.0.1:8000/mcp`. The operator flow is:

1. Call `execute_task` with `task=authenticate`, `DC-D-100`, a base64 PCM WAV,
   and one `requested_task` such as `server.start`.
2. Speak its `spoken_message`.
3. Pass `authorization.signature` to `execute_task` with that exact requested
   task and its target fields.
4. Speak the action result's `spoken_message`.

Successful authentication returns the signed authorization shape:

```json
{
  "signature": "<short-lived Ed25519 JWT>",
  "roles": ["org_admin"],
  "permissions": ["server:control"],
  "tasks": ["server.start"]
}
```

The signature is task-bound and single-use. A `server.start` signature cannot
authorize `server.stop` or `user.add`.

Developer tools `describe_pilot`, `list_voice_auth_events`, and
`list_server_action_events` expose the seeded setup and audit logs.

## Add Users and Roles

Supported organization roles:

- `org_admin` — can add admins/operators and control assigned servers.
- `operator` — can only control assigned servers.

First call `execute_task` with `task=authenticate` and
`requested_task=user.add`. Then call `execute_task` again with every user field:

```json
{
  "task": "user.add",
  "authorization_signature": "<signed admin voice authorization>",
  "request_id": "add-alice-001",
  "organization_id": "ORG-DEMO",
  "user_id": "OP-ALICE",
  "display_name": "Alice Smith",
  "role": "operator",
  "user_device_id": "DEV-ALICE-1",
  "server_ids": ["SRV-100"]
}
```

Use `"role": "org_admin"` and an empty or populated `server_ids` list to add
another administrator. The admin signature is consumed by the attempt, whether it
succeeds or is refused.

The newly added person must capture and enroll their own voice:

```bash
luma-record-voice --output samples/alice-1.wav --seconds 5
luma-record-voice --output samples/alice-2.wav --seconds 5
luma-record-voice --output samples/alice-3.wav --seconds 5

luma-enroll-voice \
  --operator OP-ALICE \
  --audio samples/alice-1.wav \
  --audio samples/alice-2.wav \
  --audio samples/alice-3.wav
```

The eventual frontend may interpret a spoken command such as “Add Alice as an
operator,” but transcription and intent parsing are not part of this backend
phase. The MCP call must still provide the complete structured details.

## Seeded Pilot

| Organization | Operator | Role | Device | Assigned servers |
| --- | --- | --- | --- | --- |
| `ORG-DEMO` | `OP-100` | `org_admin` | `DC-D-100` | `SRV-100`, `SRV-200` |
| `ORG-DEMO` | `OP-200` | `operator` | `DC-D-200` | `SRV-300` |

Speaker similarity alone is not production-grade authentication. This pilot
does not detect replayed recordings, synthetic voices, or coercion.

## Agent Workflow

Repository guidance lives in [`AGENTS.md`](AGENTS.md). Architecture and durable
decisions live in [`docs/agent/`](docs/agent/), and project skills live in
[`.claude/skills/`](.claude/skills/).
