# Project Context

## Purpose

Voice-authenticated control of simulated datacenter maintenance through a
browser earpiece and MCP backend.

## Current State

The Python backend exposes one task-oriented MCP contract for local speaker
verification, signed server control, and organization-scoped user administration. It uses a pinned
local ECAPA-TDNN model and a seeded, persistent SQLite database.

## Goals

- Authenticate an enrolled operator without accepting a claimed operator ID.
- Issue a signed 60-second session containing backend-derived `roles`,
  task-scoped `permissions`, and allowed tasks.
- Restart or fix only an assigned simulated server.
- Bootstrap the first organization admin locally.
- Let a voice-authenticated admin add another admin or operator with complete
  identity, device, and server-assignment details.
- Return a natural `spoken_message` and audit every attempt.

## Constraints

- No real server-management integration in the pilot.
- No operator-facing screen or manual approval in the core flow.
- Never commit signing keys, recordings, voice databases, or other biometric
  artifacts.
- Do not present speaker similarity as production-grade authentication.

## Current Frontend

- `auth.html` captures voice and computes a local WavLM speaker embedding.
- `ear.html` performs local/browser speech-to-text and text-to-speech.
- The gateway parses only `restart server X` and `fix server X` and forwards
  the signed session to MCP. It never makes authorization decisions.

## Next Phase

- Add structured spoken user-administration commands to the gateway.
- Add challenge-response and replay/synthetic-speech defenses.
- Protect MCP Streamable HTTP with OAuth and production key management.
