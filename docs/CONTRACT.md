# Luma Voice Ops — Shared Contract

Every component builds against this file. If you need to change it, tell the
whole team first, then edit it in a single small commit.

**Product:** A datacenter operator wears only an earpiece. One spoken command
both proves who the operator is (by their voice) and states what they want.
Replies come back as speech and tones. The operator never looks at a screen.
The dashboard is a read-only view for judges and supervisors.

The existing MCP backend in `src/luma_datacenter/` stays the single source of
truth for identity, authorization, server state and audit. The new **voice
gateway** sits between the earpiece and the backend. Its language model only
works out what the operator asked for. It never decides who someone is or
whether they are allowed to do something, and it never keeps a token longer
than the pending confirmation that needs it.

## Processes and URLs

```text
Earpiece (browser) ──WS──► Voice Gateway :8080 ──MCP Streamable HTTP──► MCP Backend :8000
Dashboard (browser) ─HTTP─┘   (FastAPI, Claude intent parser)               (existing, SQLite, ECAPA)
```

| Process | Command | Owner |
|---|---|---|
| MCP backend | `luma-backend-mcp --transport streamable-http --port 8000` | B2 |
| Gateway | `luma-gateway` (runs uvicorn on `0.0.0.0:8080`) | B1 |
| Gateway without PyTorch or the backend | `LUMA_GATEWAY_BACKEND=fake luma-gateway` | B1/B2 |

- **Earpiece:** `http://<host>:8080/ear.html?device=DC-D-100`
- **Dashboard:** `http://<host>:8080/dashboard.html`
- **Landing page:** `http://<host>:8080/`

**Environment variables:**

- `ANTHROPIC_API_KEY`
- `LUMA_BACKEND_MCP_URL` (already defined in `config.py`)
- `LUMA_GATEWAY_BACKEND=mcp|fake` (default `mcp`)
- `LUMA_GATEWAY_MODEL` (default `claude-haiku-5-5`)

Keep them in `.env`, which must be in `.gitignore`.

**Second laptop on the LAN:** Chrome only grants the microphone on localhost
or HTTPS. Set `chrome://flags/#unsafely-treat-insecure-origin-as-secure` to
`http://<host-ip>:8080`, or use `cloudflared tunnel --url http://localhost:8080`.

## File ownership (only edit files you own)

| Owner | Role | Files |
|---|---|---|
| **B1** | Gateway (dialogue) | `src/luma_datacenter/gateway/` (`app.py`, `intents.py`, `dialogue.py`, `runbooks.py`, `alerts.py`), `tests/test_gateway_*.py` |
| **B2** | Backend and integration | `backend_mcp.py`, `backend_client.py`, other existing `src/luma_datacenter/*.py`, existing tests, `pyproject.toml`, `.gitignore`, `README.md`, `docs/agent/*` |
| **F1** | Earpiece | `frontend/ear.html`, `frontend/ear.js`, `frontend/earcons.js`, `frontend/wav.js` |
| **F2** | Control room | `frontend/dashboard.html`, `frontend/dashboard.js`, `frontend/index.html`, `docs/DEMO.md` |

## Earpiece ↔ gateway WebSocket: `ws://<host>:8080/ws/{device_id}`

**Client → gateway:**

```json
{"type": "utterance", "text": "start server one hundred",
 "audio_wav_base64": "<16-bit PCM mono 16 kHz WAV, 1.2–14 s>", "lang": "en-US"}
{"type": "ack", "id": "evt_12"}
```

- `text` comes from the browser's `webkitSpeechRecognition`.
- `audio_wav_base64` is the same push-to-talk clip, recorded at the same time.
  The client pads clips shorter than 1.2 s with silence, because the backend
  rejects clips under 1 s.
- `audio_wav_base64` may be empty when the clip failed to record. The gateway
  then refuses any action that needs the operator's voice verified.

> **Superseded by "Voice authentication" below:** the earpiece no longer
> sends audio. It signs in once with a browser-computed voice embedding, then
> sends text only.

**Gateway → client:**

```json
{"type": "hello", "device_id": "DC-D-100", "operator": {"id": "OP-100", "name": "Avery Chen", "role": "org_admin"}}
{"type": "say", "id": "evt_12", "text": "Approved. Server SRV-100 has been started.",
 "priority": "task", "earcon": "success", "lang": "en-US", "from": "system"}
```

- `priority` is one of `info | task | warning | emergency`.
- `earcon` is one of `none | chime | task | message | warn | alarm | success | error | verified`.
- `from` is `"system"`, `"assistant"`, or the sending operator's id.
- If the device is unknown, the `operator` in `hello` is `null`.

**How the earpiece handles priority:**

| Priority | Behavior |
|---|---|
| `emergency` | Stop current speech and listening, play `alarm` twice, speak the text twice. |
| `warning` | Stop current speech, play `warn`, speak. Cut in front of the queue. |
| `task` / `info` | Queue, play the earcon, speak in order. Never speak while push-to-talk is held. |

## Voice authentication (frontend-computed embeddings)

The project has two phases:

1. **Sign in:** `frontend/auth.html` records a phrase, computes a speaker
   embedding **in the browser**, and sends only the embedding.
2. **Commands:** `frontend/ear.html` then sends text only, as `utterance`
   messages.

**Embedding model:** `Xenova/wavlm-base-plus-sv` (WavLM x-vector), run with
Transformers.js 3.8.1, ONNX `q8`. Each embedding has 512 dimensions and is
L2-normalized, so cosine similarity is a plain dot product.

- The model card reports about 0.96 for the same speaker and about 0.62 for
  different speakers. The suggested threshold is **0.86**; tune it on the
  demo mic.
- **These embeddings are not comparable with the backend's SpeechBrain ECAPA
  embeddings.** Enrollment and verification must both use WavLM vectors from
  the frontend, and the ECAPA threshold of 0.25 doesn't apply.

**Client → gateway** (same socket, `ws://<host>:8080/ws/{device_id}`):

```json
{"type": "voice_auth", "device_id": "DC-D-100",
 "embedding": [0.0123, -0.0456, "… 512 floats"],
 "embedding_model": "Xenova/wavlm-base-plus-sv", "embedding_dtype": "q8",
 "dimensions": 512, "normalized": true, "duration_s": 2.4, "sample_rate": 16000}
```

**Gateway → client:**

```json
{"type": "auth_result", "authenticated": true, "code": "VOICE_AUTHENTICATED",
 "spoken_message": "Voice verified. Welcome, Avery.",
 "operator": {"id": "OP-100", "name": "Avery Chen", "role": "org_admin"},
 "similarity_score": 0.93, "authentication_token": "<jwt>", "expires_at": 1767225600}
```

- On refusal, `authenticated` is `false`, `authentication_token` is `null`,
  and `code` is one of `VOICE_NOT_MATCHED`, `VOICE_NOT_ENROLLED` or
  `DEVICE_NOT_TRUSTED`, with a speakable `spoken_message`.
- The frontend speaks `spoken_message` exactly as sent.
- On success, the frontend stores
  `{device_id, operator, authentication_token, expires_at}` in
  `sessionStorage["luma.voiceSession"]` and opens `ear.html?device=…`.

**Enrollment:** the existing design keeps enrollment local-only, so it never
goes over the socket.

1. Open `auth.html?enroll=1&device=DC-D-100&operator=OP-100&name=Avery%20Chen`.
2. The operator records 3 phrases.
3. The browser downloads `voice-enrollment-OP-100.json`:
   `{operator_id, name, device_id, embedding_model, embedding_dtype,
   dimensions, created_at, embeddings: [[512], [512], [512]], centroid: [512]}`.
4. The backend team imports that file with a local command, storing
   `centroid` as the operator's profile.

**Frontend-only testing:** `auth.html?mock=1` verifies against the enrollment
saved in that browser, with no backend.

**Security caveat (say it in the pitch):** a client-computed embedding is a
replayable credential. Anyone who captures the vector can resend it. The
backend should accept only embeddings over TLS from trusted devices, rate-limit
attempts, and treat this as demo-grade.

## Gateway HTTP (for the dashboard)

- `GET /api/health` returns `{"ok": true, "backend": "mcp|fake"}`.
- `GET /api/state` (the dashboard polls this every 1 s) returns:

  ```json
  {"servers":   [{"id","name","status","temp_c","alert","assigned_operator_ids":[...]}],
   "operators": [{"id","name","role","device_id","online","last_heard","voice_enrolled"}],
   "alerts":    [{"id","server_id","kind","text","ts","active"}],
   "events":    [{"id","ts","kind","device_id","operator_id","text","code","ok","similarity_score"}]}
  ```

  `events` holds the last 60 entries, newest first. They merge the gateway's
  own log (`heard`, `say`, `message`, `alert`) with the backend's audit tables
  (`voice_auth`, `server_action`, `user_admin`). The gateway handles `temp_c`
  and `alert` in memory.

- `POST /api/sim/{scenario}?server=SRV-200` returns `{"ok": true}`. Scenarios:
  - `overheat`: sets `temp_c` to 41 and an active alert, then sends a warning
    to every online device whose operator is assigned that server.
  - `fire`: an emergency to every device: "Fire alarm in hall one. Leave by
    the east exit now."
  - `cooldown`: clears alerts and sets `temp_c` back to 24.
  - `reset`: clears the gateway's in-memory state (not the backend database).

## New MCP tools (B2 adds them to `backend_mcp.py`)

These are read-only developer tools in the style of the existing `list_*`
tools. They never return embeddings, tokens or keys.

```text
describe_device(device_id) -> {"known": bool, "operator_id", "name", "role", "organization_id", "trusted"}
list_servers() -> {"servers": [{"id","name","status","organization_id","assigned_operator_ids":[...]}]}
list_operators() -> {"operators": [{"id","name","active","role","organization_id","device_ids":[...],"voice_enrolled": bool}]}
get_server_status(device_id, server_id="") -> {"spoken_message", "servers": [{"id","name","status"}]}
    # Only covers servers assigned to the device's operator. With server_id="", lists all of them.
```

The existing tools stay as they are: `authenticate_voice`,
`execute_server_action`, `add_organization_user` and the `list_*_events`
tools.

## `backend_client.py` (B2), the only way the gateway reaches the backend

```python
class BackendClient(Protocol):
    async def call(self, tool: str, **arguments) -> dict: ...   # returns the tool's dict result

def make_backend_client() -> BackendClient   # "mcp" → McpBackendClient(backend_mcp_url()), "fake" → FakeBackendClient
```

`FakeBackendClient` serves every tool above from the same seed data as
`database.py`, kept in memory:

- `authenticate_voice` succeeds when the audio is non-empty. When the
  transcript contained the word "imposter" (for testing), it returns
  `VOICE_NOT_MATCHED`.
- The fake keeps the real codes, `spoken_message` texts and token semantics:
  one use per token, a 60 s lifetime, and the same assignment checks.

## Gateway dialogue (B1)

**Intent parsing:** one Claude call per utterance with
`tool_choice={"type": "tool", "name": "route"}`. The prompt contains the
operator's name, role, the servers they can control, any pending
confirmation, the active alert and the runbook state. `route` returns
exactly one of:

```text
server_action {action: start|stop, server_id}     # "server one hundred" / "it" (the alerting server) → SRV-100
server_status {server_id?}
confirm | cancel | repeat | help
add_user {display_name, role: operator|org_admin, server_ids[]}
runbook_start {server_id?} | runbook_next {note?}
send_message {to (operator name or "everyone"), text}
unknown {reason}
```

Handlers are deterministic Python. The language model never sees or handles
a token.

| Intent | Handling |
|---|---|
| `server_action` | 1. `authenticate_voice(device_id, audio)` using **this** clip. If that fails, speak its `spoken_message` with the `error` earcon. 2. Play the `verified` earcon. 3. **start:** call `execute_server_action` at once. **stop:** hold the token as pending and say "Voice verified, <first name>. Stop <id>, <name>? Say confirm." 4. On `confirm` while the token is still valid, call `execute_server_action`. If the token has expired, ask the operator to repeat the command. |
| `add_user` | Authenticate with this clip. Read back "Add <name> as <role> on <servers>? Say confirm." On confirm, call `add_organization_user` with `user_id=OP-<UPPERNAME>`, `device_id=DEV-<UPPERNAME>-1` and a fresh `request_id`. Speak the result plus "They need to enroll their voice before signing in." |
| `server_status` | `get_server_status`. No voice check needed, because it is read-only and scoped to the device. |
| `runbook_*` | Spoken steps from `runbooks.py`. The `overheat` runbook: 1. Confirm the amber LED on the front panel. 2. Check that the cold-aisle intake is clear. 3. Reseat fan module two. 4. Read me the fan serial number. 5. If it is still hot, say "stop it". Each response from the operator is logged as an event. |
| `send_message` | Deliver "Message from <first name>: <text>" with the `message` earcon to the recipient's online device. If the recipient isn't online, log it and say so. |
| `repeat` | Resend the last `say`. |
| `help` | Speak 3 example commands for this operator's role. |

Every backend result is spoken using **its own `spoken_message`**. Never
rephrase an authorization result. Gateway-authored lines are 1–2 sentences
with no markdown.

## Seed and demo cast (from `database.py`)

| Device | Operator | Role | Can control | Played by |
|---|---|---|---|---|
| `DC-D-100` | OP-100 Avery Chen | org_admin | SRV-100 (stopped), SRV-200 (running) | presenter 1: enroll their voice |
| `DC-D-200` | OP-200 Jordan Patel | operator | SRV-300 (running) | presenter 2: enroll their voice |
| — | imposter | — | — | presenter 3 speaks into DC-D-100 |

**Enrollment:** enroll on the demo laptop, using **the same microphone or
earbuds you will demo with** (`luma-record-voice --list-devices`), with three
clips each.

## Demo script (everyone builds toward this)

1. **Avery:** "What's the status of my servers?" → SRV-100 is stopped and
   SRV-200 is running.
2. **Avery:** "Start server one hundred." → `verified` tone, then "Approved.
   Server SRV-100 has been started." The dashboard shows the similarity score.
3. **Imposter** on Avery's earpiece: "Stop server two hundred." → refused. The
   dashboard shows the failed check and the low score.
4. **Jordan:** "Stop server one hundred." → the voice is verified but the
   request is refused: "You are not authorized to control that server."
5. Press **overheat SRV-200**. Avery hears the warning and says "Walk me
   through it." Avery steps through the runbook, then says "Stop it." The
   system reads it back, Avery says "Confirm", and the server is stopped.
6. **Avery:** "Tell Jordan SRV-300 needs a reboot after lunch." Jordan hears
   it.
7. **Avery:** "Add Alice as an operator on server one hundred." → read-back,
   then "Confirm", then the user is added and Avery is told Alice must enroll.
8. Press **fire**. Both earpieces get the alarm.
9. Close: "Nobody touched a screen, and every action was voice-verified and
   audited."
