# Luma Voice Ops — 3-Hour Roadmap

Four people work in two pairs, each building against
[`CONTRACT.md`](CONTRACT.md):

- **Backend:** B1 (Gateway), B2 (MCP backend and integration)
- **Frontend:** F1 (Earpiece), F2 (Control room)

The voice-authenticated MCP backend already exists. This plan wraps it in a
live voice experience and adds the use cases around it. Each person runs their
own Claude Code session and pastes their prompts in order. Only edit the files
you own. Commit small changes and pull often.

## Features in scope

| Use case | Backend | Frontend |
|---|---|---|
| Start a server with one spoken command (voice check + action) | exists, B1 dialogue | F1 records WAV + transcript |
| Stop a server, with a spoken read-back and "confirm" | B1 | F1 |
| Imposter refused / operator not authorized for a server | exists | F2 shows similarity score |
| Server status by voice | B2 `get_server_status`, B1 | F1 |
| Pushed overheat alert, then a spoken runbook, then a stop | B1 alerts and runbooks | F1 priority queue, F2 sim buttons |
| Messages between operators | B1 | F1 |
| Admin adds a user by voice | exists, B1 dialogue | F1 |
| Fire evacuation broadcast | B1 | F1 alarm, F2 button |
| Live audit trail for judges | B2 list tools, B1 `/api/state` | F2 |

**Cut:** challenge phrases, liveness and replay defenses (they are already
listed as next steps), phone calls, wake word, multilingual.

## Timeline

| Time | What | Gate |
|---|---|---|
| 0:00–0:20 | **Setup:** B2 runs B2-0 (dependencies, `.env`, fake backend client) and pushes. The **demo laptop** installs everything (`pip install -e '.[dev]'`). The others only need the gateway extras. Presenters 1 and 2 enroll their voices. | Fake backend pushed; voices enrolled |
| 0:20–1:20 | **Sprint 1:** core pieces against the fake backend and mocks | Each piece runs alone |
| 1:20–1:40 | **Integration 1:** on the demo laptop, the earpiece talks to the gateway, which talks to the real MCP backend, and "Start server one hundred" works | Demo steps 1–4 |
| 1:40–2:15 | **Sprint 2:** alerts, runbook, messages, add user, fire, dashboard live | Every demo step works once |
| 2:15 | **Feature freeze** | — |
| 2:15–2:45 | Three full rehearsals with the real voices and earbuds; fix only blockers | 3 clean runs |
| 2:45–3:00 | Pitch practice and buffer | — |

**Top risks: check them in the first 30 minutes**

1. **F1: recording and speech recognition at once.** Chrome must capture a WAV
   and run `webkitSpeechRecognition` at the same time. If it can't, fall back
   to recognition first, then a separate 2 s WAV recording ("Say your
   passphrase").
2. **B2: the MCP client API.** Check the client API of the installed `mcp`
   (2.x) package. If the Streamable HTTP client fights you for more than 20
   minutes, add `LocalBackendClient`, which calls `build_runtime()` services
   in-process.
3. **B2: voice match on the demo mic.** If presenters fail to match on the
   demo microphone, re-enroll with that mic. Change
   `LUMA_VOICE_MATCH_THRESHOLD` only as a last resort, and tell the team.

---

## B2: MCP backend and integration

### B2-0: Gateway dependencies and fake backend (push by 0:20)

> Read `AGENTS.md`, `docs/agent/ARCHITECTURE.md`, `docs/CONTRACT.md` and the
> `implement-datacenter` skill. You own the existing backend files,
> `backend_client.py`, `pyproject.toml`, `.gitignore`, `README.md` and
> `docs/agent/*`.
>
> 1. In `pyproject.toml`, add a `gateway` optional extra (fastapi,
>    uvicorn[standard], anthropic, python-dotenv) and a script
>    `luma-gateway = "luma_datacenter.gateway.app:main"`. Add `.env` to
>    `.gitignore`, and create `.env.example` with the variables listed in the
>    contract.
> 2. Create `src/luma_datacenter/backend_client.py` exactly as the contract
>    describes. `FakeBackendClient` must not import torch, speechbrain or mcp.
>    It mirrors the seed data, codes and `spoken_message` texts of
>    `service.py`, `voice_auth.py` and `administration.py`, and covers the new
>    tools.
> 3. Add `McpBackendClient` (with the `mcp` import inside the class). Check the
>    installed `mcp` package's client API for Streamable HTTP, open a session
>    for each call (keep it simple), call the tool and return the structured
>    or JSON content as a dict.
> 4. Create the empty package `src/luma_datacenter/gateway/__init__.py` so B1
>    can start.
>
> Add `tests/test_backend_client_fake.py`, covering: one use per token; an
> unassigned server is refused; the imposter path fails. Run `ruff check .`
> and `pytest -q`. Commit and push.

### B2-1: New read-only MCP tools

> Add `describe_device`, `list_servers`, `list_operators` and
> `get_server_status` to `backend_mcp.py`, exactly as specified in
> `docs/CONTRACT.md`. Put the SQL in a small read-only service (for example
> `inventory.py`) instead of inline in the tool. These tools must never return
> embeddings, tokens or keys. `get_server_status` derives the operator from
> the device and only includes servers assigned to that operator. Its
> `spoken_message` lists each one, for example "SRV-100 is stopped. SRV-200
> is running."
>
> Mirror the tools in `FakeBackendClient`. Add tests to
> `tests/test_server_control.py` or a new file, then run `ruff check .` and
> `pytest -q`. Record a decision in `docs/agent/DECISIONS.md`: "Add voice
> gateway; LLM parses intent only, backend remains the authorization
> boundary". Commit and push.

### B2-2: Demo laptop setup and real MCP integration (1:20)

> We're integrating on this laptop. Do these:
>
> 1. Start `luma-backend-mcp --transport streamable-http --port 8000`.
> 2. Verify that `McpBackendClient` can call `describe_pilot`,
>    `get_server_status` and `authenticate_voice` (using a file in `samples/`)
>    from a small script, `scripts/smoke_gateway_backend.py`.
> 3. Warm up the voice model with one authentication, so the first one during
>    the demo isn't slow.
> 4. If the MCP client is blocked, implement `LocalBackendClient` in
>    `backend_client.py`. It calls `build_runtime()` services the same way
>    `backend_mcp.py` does, selected with `LUMA_GATEWAY_BACKEND=local`.
>
> Then update the `README.md` "Run" section with the 2-process demo startup.

### B2-3: Hardening (after 1:40)

> Run the demo script in `docs/CONTRACT.md` against the real backend and look
> at the audit tables via the `list_*_events` tools. Check these:
>
> - Every refusal has a speakable message.
> - The imposter attempt is audited with its score.
> - `add_organization_user` works with the ids the gateway generates.
> - The voice token's 60 s lifetime is long enough for the "confirm" step.
>
> Then run the `validate-no-app` skill and fix anything it flags in your
> files. Finally, run `/check`.

---

## B1: Voice gateway (`src/luma_datacenter/gateway/`)

### B1-1: Gateway server and intent parser (against the fake backend)

> Read `AGENTS.md`, `docs/agent/ARCHITECTURE.md`, `docs/CONTRACT.md` and the
> `implement-datacenter` skill, then load the claude-api skill for correct
> SDK usage. You own `src/luma_datacenter/gateway/` and
> `tests/test_gateway_*.py`.
>
> Build the gateway:
>
> - **`app.py`:** a FastAPI app, with `main()` running uvicorn on
>   `0.0.0.0:8080`. Load `.env`. Serve `frontend/` from `project_root()` as
>   static files with `html=True`.
>   - WebSocket `/ws/{device_id}`: on connect, call `describe_device` and send
>     `hello`. Keep a registry from device to socket. On `utterance`, log a
>     `heard` event and handle it in `asyncio.create_task`.
>   - `GET /api/health` and `GET /api/state`, merging the backend's `list_*`
>     tools with the gateway's own event log (shapes as in the contract).
>   - `POST /api/sim/{scenario}`.
>   - Get the backend from `backend_client.make_backend_client()`.
> - **`intents.py`:** an `anthropic.AsyncAnthropic` client, model from
>   `LUMA_GATEWAY_MODEL` (default `claude-haiku-5-5`), `max_tokens` 300, a
>   single forced `route` tool whose schema is a union of the intents in the
>   contract.
>   - The system prompt includes the operator's name and role, the servers
>     they can control (id plus name), any pending confirmation, the active
>     alert and the runbook step.
>   - Normalize spoken server names: "server one hundred", "one hundred",
>     "SRV 100" all become SRV-100. "It" and "that server" mean the alerting
>     server.
>   - On any API error, use a regex fallback that covers start, stop, status,
>     confirm, cancel and repeat.
> - **`dialogue.py`:** the deterministic handlers, exactly as in the
>   contract's "Gateway dialogue" table. Use `asyncio` per device state
>   (pending confirmation with its token and expiry, last `say`, runbook
>   progress). Speak backend results using their `spoken_message`, verbatim.
>   Use the `verified` earcon after a voice match, `success` / `error` after
>   actions.
>
> Write `tests/test_gateway_dialogue.py` against `FakeBackendClient`, with a
> stubbed intent parser covering: start, stop (confirm required), imposter
> refused, token expired before confirm, and status. Run `ruff check .` and
> `pytest -q`. Commit and push.

### B1-2: Alerts, runbook, messages, add user, fire

> Implement the rest of the gateway dialogue in `docs/CONTRACT.md`:
>
> - **`alerts.py`:** in-memory `temp_c` and alert state per server. The
>   `overheat`, `cooldown`, `fire` and `reset` scenarios. Alerts go to online
>   devices whose operator is assigned the server, which you find from
>   `list_servers`. The overheat text: "Warning. SRV-200 is at 41 degrees and
>   rising. Say walk me through it, or stop it."
> - **`runbooks.py`:** the `overheat` runbook steps, plus `runbook_start` and
>   `runbook_next`. Record each note the operator gives, such as the serial
>   number, as an event.
> - **`send_message`:** delivery to an operator by name or to "everyone", with
>   the `message` earcon.
> - **`add_user`:** the voice check, the read-back, then on confirm
>   `add_organization_user` with the generated ids and a fresh `request_id`.
> - **`help` and `repeat`.**
>
> Add tests for each against the fake backend, then run `ruff check .` and
> `pytest -q`. Commit and push.

### B1-3: Harden the dialogue against real speech (after 1:40)

> Run the demo script through the gateway, using the real browser earpiece on
> the demo laptop. Fix these:
>
> - Misparsed transcripts, for example "start server 100", "start several
>   hundred" (a speech-recognition error), "stop it", "yes confirm", "go
>   ahead".
> - Replies that are wordy.
> - Pending confirmations that leak across intents. Any non-confirm intent
>   cancels the pending action and says so.
>
> Log the parse time and the backend time for each turn. If the first token
> back takes more than about 1.5 s, send a filler "Checking your voice." with
> earcon `none` before calling `authenticate_voice`. Commit after each fix.

---

## F1: Earpiece (`frontend/ear.html`, `ear.js`, `earcons.js`, `wav.js`)

**Already built:**

- **Voice sign-in** (`auth.html`, `auth.js`, `recorder.js`,
  `voice-embedding.js`): WavLM speaker embeddings computed in the browser.
  See the "Voice authentication" section of the contract.
- **Speech to text** (`stt.js`, `speech-models.js`): on-device Whisper
  `base.en`, with `?stt_model=tiny` for a faster model. It falls back to the
  Web Speech API.
- **Text to speech** (`tts.js`, `speech-models.js`): the on-device MMS-TTS
  model, with numbers and ids spelled out for it. It falls back to
  speechSynthesis. The contract's priority queue sits on top of either voice.
- **Earpiece** (`ear.html` / `ear.js`): the wiring. `?stt=` / `?tts=` choose
  `model` or `browser`, plus `?mock=1` / `?debug=1` and basic tones. The
  models load in the background, and the browser engines are used until they
  are ready.
- **Model loading** (`model-runtime.js`): the shared Transformers.js 3.8.1
  loader.
- **Dev server** (`serve.py`): serves `.js` with the correct type on Windows.

What's left for F1: `earcons.js`, earbud media keys, and moving model
inference into a Web Worker if it stalls the page. Skip the parts of F1-1 and
F1-2 that are already done.

### F1-1: Push-to-talk capture (spike the top risk first)

> Read `docs/CONTRACT.md`. You own `frontend/ear.html`, `frontend/ear.js`,
> `frontend/earcons.js` and `frontend/wav.js`. No frameworks and no build
> step.
>
> Start with the risk: prove that Chrome can capture a WAV and run
> `webkitSpeechRecognition` at the same time during one push-to-talk hold.
>
> - **`wav.js`:** `getUserMedia` (mono, echoCancellation off,
>   noiseSuppression on) and AudioContext capture through an AudioWorklet (or
>   a ScriptProcessor fallback). Downsample to 16 kHz, encode a 16-bit PCM
>   WAV, pad it with silence to at least 1.2 s, cap it at 14 s, and base64 it.
> - **`ear.html` / `ear.js`:** a black full-screen page with the operator name
>   from `hello`, a dim status dot and a "tap to start" overlay to unlock
>   audio.
>   - Hold the Space bar, or touch and hold the screen, to talk. Play a
>     `chime` on press; on release, send
>     `{type: "utterance", text, audio_wav_base64, lang}`.
>   - If the transcript is empty, play the `error` earcon and don't send.
>   - Connect to `ws://<host>/ws/<device>` from `?device=`, reconnecting
>     automatically with backoff.
> - **`?mock=1`:** no socket. Echo canned replies, and add a "download last
>   WAV" link, shown only with `?debug=1`, so we can check the audio with
>   `luma-voice-pilot`.
>
> If simultaneous capture fails, implement the fallback described under
> "Top risks" in `docs/ROADMAP.md`. Commit and push.

### F1-2: Speech output, earcons and the priority queue

> Implement playback following `docs/CONTRACT.md`:
>
> - `speechSynthesis` with the best local voice for the message's `lang`, at
>   rate 1.05.
> - The exact priority rules, including never speaking while push-to-talk is
>   held, except for an emergency.
> - Send `ack` after each message is spoken.
> - Handle "repeat" locally if the server is unreachable.
>
> In `earcons.js`, synthesize each earcon with WebAudio so they are clearly
> distinct:
>
> - `chime`: a soft rising pair of notes
> - `task`: a single blip
> - `message`: a double blip
> - `warn`: 3 fast beeps
> - `alarm`: a 1.2 s siren
> - `success`: a rising arpeggio
> - `error`: a low buzz
> - `verified`: a warm two-tone "unlock" sound, the signature sound of the
>   demo
>
> Mock mode keys: W triggers a warning, E an emergency, M a message. Test
> with `?mock=1`. Commit and push.

### F1-3: Real gateway and earbuds (1:20)

> Switch to the real gateway, `ear.html?device=DC-D-100`. Do these:
>
> - Run demo steps 1–4 by voice with a teammate.
> - Add `navigator.mediaSession` play/pause handlers so a Bluetooth earbud tap
>   toggles talking (tap to start, tap to send), keeping a silent looping
>   audio element alive so they fire. Keep Space as a fallback.
> - Add a `?debug=1` overlay with the last 5 messages in and out.
>
> Test on 2 browsers at once (DC-D-100 and DC-D-200). Commit and push.

---

## F2: Control room (`frontend/dashboard.html`, `dashboard.js`, `index.html`, `docs/DEMO.md`)

### F2-1: Dashboard with mock data

> Read `docs/CONTRACT.md`. You own `frontend/dashboard.html`,
> `frontend/dashboard.js`, `frontend/index.html` and `docs/DEMO.md`. No
> frameworks and no build step.
>
> Build a read-only Control Room for judges and supervisors, with a dark,
> high-contrast, projector-friendly design. Add a banner: "Operators never see
> this screen."
>
> - **Hall map:** a rack row with SRV-100, SRV-200 and SRV-300 as tall cards.
>   Running shows green with a subtle animation; stopped shows grey; an alert
>   pulses red with a large `temp_c`. Show the names of assigned operators.
> - **Operator cards:** name, role badge, online dot, device, "voice
>   enrolled", and the last heard utterance as a quote.
> - **Live audit feed:**
>   - `voice_auth` events show a similarity-score bar against the threshold:
>     green tick when matched, red cross when rejected.
>   - `server_action` / `user_admin` events show the result code and the
>     `spoken_message`.
>   - `heard` / `say` / `message` / `alert` events appear as speech bubbles.
>   - Newest first, sliding in.
> - **Demo buttons** for `POST /api/sim/overheat?server=SRV-200`, `cooldown`,
>   `fire` (red, needs a confirm click) and `reset`, with keys 1–4.
>
> Poll `GET /api/state` every 1 s. `?mock=1` uses a built-in fake state that
> plays through the demo script over time. Also build `index.html`: the
> product name, a one-paragraph pitch, and links to `ear.html?device=DC-D-100`,
> `ear.html?device=DC-D-200` and the dashboard. Commit and push.

### F2-2: Real gateway and the demo runbook (1:20)

> Switch to the real `/api/state` and fix any shape mismatches, following
> `docs/CONTRACT.md`. Report differences in the backend to B1 or B2 rather
> than working around them.
>
> Then write `docs/DEMO.md`:
>
> - Hardware and roles: which laptop runs both servers, who wears which
>   earbud, who plays the imposter.
> - The startup checklist: both processes, a warm-up authentication, both
>   earpieces showing as online.
> - The exact line to speak at each demo step, with the expected sound and
>   reply.
> - Which button to press when.
> - The narration for the judges.
> - A recovery line for each likely failure (no voice match, misheard
>   command, token expired).
>
> Commit and push.

### F2-3: Pitch (after 2:00)

> Add `?pitch=1` to the dashboard: a large title, the problem statement
> ("Build for people who will never open an app"), and three points:
>
> - Hands and eyes stay on the rack.
> - Your voice is your badge.
> - Every action is authorized and audited.
>
> Then show the live view. Write a 90-second pitch at the top of
> `docs/DEMO.md`, covering the problem, the live demo, why voice-only is safe
> here (a voice check per action, one-use tokens, assignment checks, an audit
> trail), and honest limits plus next steps (liveness and replay defenses,
> phone calls, smart glasses, connecting to a real server-management
> system). Commit and push.

---

## Everyone

**Integration bug:**

> Follow the demo script in `docs/CONTRACT.md`. Tell me exactly which step
> fails and why. Check gateway logs, MCP backend logs, the browser console
> and `/api/state`. Fix it only if it's in a file I own (see the contract).
> If it isn't, write a short bug report: owner, file, payload, expected
> versus actual.

**Contract mismatch:**

> Component A sends `<X>` but B expects `<Y>`. Check `docs/CONTRACT.md`;
> whichever side differs is wrong. Fix it if it's mine. If the contract is
> ambiguous, propose the smallest clarification and tell the team.

**Final (2:15):** `/check`. Then confirm that no `.env`, `samples/`, database
or `.pem` files are tracked.
