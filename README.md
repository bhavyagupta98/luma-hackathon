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

1. Call `authenticate_voice` with `DC-D-100` and a base64 PCM WAV.
2. Speak its `spoken_message`.
3. Pass the returned token to `execute_server_action` with `SRV-100` and
   `start`, or `SRV-200` and `stop`.
4. Speak the action result's `spoken_message`.

Developer tools `describe_pilot`, `list_voice_auth_events`, and
`list_server_action_events` expose the seeded setup and audit logs.

## Run the Voice Gateway Demo

The gateway (`luma-gateway`) puts a browser earpiece in front of the backend: a worker
signs in by voice, hears "<name> is authenticated.", then says
`restart server X` or `fix server X`. The gateway checks the worker's server assignments and
answers "Task successful." or "You are not allowed to do this task." Each session is cleared
60 seconds after sign-in. Protocol details are in [`docs/CONTRACT.md`](docs/CONTRACT.md).

```bash
python -m pip install -e '.[dev,gateway]'
python scripts/make_demo_voices.py       # Windows: writes 15 local voice files to samples/
python scripts/demo_setup.py --onboard   # enroll Avery + Jordan; add Alice by voice and enroll her
luma-gateway                             # http://localhost:8080 (stop it before re-running setup)
```

| Worker | Device | Role | Servers | Voice files |
| --- | --- | --- | --- | --- |
| Avery Chen | `DC-D-100` | `org_admin` | `SRV-100`, `SRV-200` | `samples/avery/` |
| Jordan Patel | `DC-D-200` | `operator` | `SRV-300` | `samples/jordan/` |
| Alice Smith (onboarded) | `DC-D-ALICE` | `operator` | `SRV-100` | `samples/alice/` |

Without a microphone, play a voice file through the running gateway:

```bash
python scripts/simulate_worker.py --device DC-D-100 --audio samples/avery/auth-1.wav   "restart server one hundred" "restart server three hundred"
python scripts/simulate_worker.py --device DC-D-200 --audio samples/jordan/auth-1.wav   "restart server one hundred" --wait 60     # refused, then watch the session expire
```

**One-command hands-free demo:** `python scripts/run_demo.py --fresh` starts the gateway, opens Chrome
in a clean window and taps the page for you, so the presenter registers, signs in and gives commands
purely by voice ([run sheet](docs/DEMO.md)).

**Overheat scenario (port 8090, audio only):** `python scripts/run_demo.py --scenario --fresh` runs a
second server where, shortly after a worker is inside, the earpiece alerts them to an overheating server,
offers directions from where they checked in, and walks them to the rack with short spoken steps
(repeat, back, "where am I", fix). Dialogue and a 2-minute video script: [docs/SCENARIO.md](docs/SCENARIO.md).

The pages are hands-free: after one tap to start (browsers require it), the page speaks a prompt,
plays a soft tone, listens until you stop talking, answers, and listens again; nothing to press.
Add `&manual=1` to any link to hold Space (or the button) to talk instead.

With a microphone you can enroll in the browser (demo only): start the gateway with
`LUMA_ALLOW_BROWSER_ENROLL=1 luma-gateway` and open
`http://localhost:8080/auth.html?device=DC-D-100&enroll=1`; it asks you to say your name ("My name
is ..."), records three phrases, saves your voice profile and name, says "<name>, you are
enrolled.", and continues to sign-in, where you are greeted by that name. It only accepts requests from the same computer.
Or enroll with the command-line recorder above, then open
`http://localhost:8080/auth.html?device=DC-D-100` in Chrome, tap once, and speak after the tone.
All pages use Chrome's built-in speech by default (fast and reliable). Add `&stt=model&tts=model`
to the earpiece link to use the on-device models instead (Whisper and MMS-TTS, about 115 MB,
downloaded on first use; slower, and they share the page's main thread). The microphone only works
on `localhost` or HTTPS.

Tests: `pytest -q` runs the whole suite. `tests/test_gateway_flow.py` uses a fake speaker model;
`tests/test_gateway_real_voice.py` uses the generated Windows voices with the real ECAPA model
and is skipped when torch or Windows speech is unavailable.

## Add Users and Roles

Supported organization roles:

- `org_admin` — can add admins/operators and control assigned servers.
- `operator` — can only control assigned servers.

After an admin calls `authenticate_voice`, pass that fresh token to
`add_organization_user`. Every field is required:

```json
{
  "authentication_token": "<signed admin voice token>",
  "request_id": "add-alice-001",
  "organization_id": "ORG-DEMO",
  "user_id": "OP-ALICE",
  "display_name": "Alice Smith",
  "role": "operator",
  "device_id": "DEV-ALICE-1",
  "server_ids": ["SRV-100"]
}
```

Use `"role": "org_admin"` and an empty or populated `server_ids` list to add
another administrator. The admin token is consumed by the attempt, whether it
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
