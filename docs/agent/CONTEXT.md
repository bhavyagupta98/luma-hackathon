# Project Context

## Purpose

Voice-authenticated, screen-independent control of simulated datacenter server
power for the hackathon's No App track.

## Current State

The Python backend exposes MCP tools for local speaker verification, signed
server control, and organization-scoped user administration. It uses a pinned
local ECAPA-TDNN model and a seeded, persistent SQLite database.

## Goals

- Authenticate an enrolled operator without accepting a claimed operator ID.
- Issue a short-lived, one-action signed identity token.
- Start or stop only an assigned simulated server.
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

## Next Phase

- Add live audio capture to the eventual voice host.
- Add transcription and strict `start|stop + server ID` intent parsing.
- Add transcription and structured parsing for spoken user-administration
  commands.
- Add challenge-response and replay/synthetic-speech defenses.
- Protect MCP Streamable HTTP with OAuth and production key management.
