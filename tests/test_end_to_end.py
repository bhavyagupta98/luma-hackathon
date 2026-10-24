from __future__ import annotations

import pytest
from mcp import Client

from luma_datacenter.backend_mcp import build_backend_server
from luma_datacenter.database import Database
from luma_datacenter.gateway.dialogue import respond
from luma_datacenter.voice_auth import VoiceAuthService
from luma_datacenter.voice_embeddings import VoiceEmbeddingError
from luma_datacenter.voice_tokens import VoiceTokenSigner


class UnusedAudioEmbedder:
    model_name = "audio-not-used"

    def embed(self, audio: bytes) -> list[float]:
        raise VoiceEmbeddingError("This test uses browser embeddings")


class CapturingBackend:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    async def call(self, tool: str, **arguments):
        self.calls.append((tool, arguments))
        return self.response


def build_browser_voice_backend(tmp_path):
    database_path = tmp_path / "e2e.db"
    signer = VoiceTokenSigner(
        tmp_path / "e2e-key.pem", issuer="test", audience="datacenter", ttl_seconds=60
    )
    database = Database(database_path)
    voice = VoiceAuthService(database, UnusedAudioEmbedder(), signer)
    enrolled = voice.enroll_embedding(
        "OP-100", [1.0, 0.0, 0.0], "Xenova/wavlm-base-plus-sv", threshold=0.8
    )
    assert enrolled.enrolled
    server = build_backend_server(
        database.path, voice_embedder=UnusedAudioEmbedder(), voice_signer=signer
    )
    return database, voice, server


@pytest.mark.anyio
async def test_browser_voice_session_runs_both_tasks_and_blocks_unassigned_server(tmp_path) -> None:
    database, _, server = build_browser_voice_backend(tmp_path)
    async with Client(server) as client:
        auth = await client.call_tool(
            "execute_task",
            {
                "task": "authenticate",
                "device_id": "DC-D-100",
                "voice_embedding": [0.99, 0.01, 0.0],
                "embedding_model": "Xenova/wavlm-base-plus-sv",
            },
        )
        authenticated = dict(auth.structured_content or {})
        token = authenticated["authorization"]["signature"]
        restarted = await client.call_tool(
            "execute_task",
            {"task": "server.restart", "request_id": "e2e-restart",
             "authorization_signature": token, "server_id": "SRV-100"},
        )
        fixed = await client.call_tool(
            "execute_task",
            {"task": "server.fix", "request_id": "e2e-fix",
             "authorization_signature": token, "server_id": "SRV-200"},
        )
        blocked = await client.call_tool(
            "execute_task",
            {"task": "server.restart", "request_id": "e2e-blocked",
             "authorization_signature": token, "server_id": "SRV-300"},
        )

    assert authenticated["authorized"] is True
    assert authenticated["authorization"]["expires_at"] > 0
    assert authenticated["authorization"]["tasks"] == [
        "server.fix", "server.restart", "user.add"
    ]
    assert "Avery Chen" in authenticated["spoken_message"]
    assert dict(restarted.structured_content or {})["authorized"] is True
    assert dict(fixed.structured_content or {})["authorized"] is True
    refusal = dict(blocked.structured_content or {})
    assert refusal["code"] == "SERVER_NOT_ASSIGNED"
    assert refusal["spoken_message"] == "You are not authorized to control that server."
    with database.connect() as connection:
        health = connection.execute("SELECT health FROM servers WHERE id='SRV-200'").fetchone()
    assert health["health"] == "healthy"


@pytest.mark.anyio
async def test_gateway_intent_uses_backend_spoken_response_unchanged() -> None:
    backend = CapturingBackend(
        {"authorized": True, "code": "SERVER_ACTION_APPROVED",
         "spoken_message": "Task successful. Server SRV-100 has been restarted."}
    )
    reply = await respond(
        "DC-D-100", "restart server one hundred", authorization_signature="signed-session",
        backend=backend,
    )

    assert reply["text"] == "Task successful. Server SRV-100 has been restarted."
    assert backend.calls[0][1]["task"] == "server.restart"
    assert backend.calls[0][1]["server_id"] == "SRV-100"


def test_new_user_browser_voice_onboarding(tmp_path) -> None:
    database, voice, _ = build_browser_voice_backend(tmp_path)
    with database.transaction() as connection:
        connection.execute("INSERT INTO operators VALUES ('OP-NEW', 'New Worker', 1)")
        connection.execute(
            """INSERT INTO organization_memberships
               VALUES ('ORG-DEMO', 'OP-NEW', 'operator', CURRENT_TIMESTAMP)"""
        )
        connection.execute("INSERT INTO datacenter_devices VALUES ('DEV-NEW', 'OP-NEW', 1)")
        connection.execute("INSERT INTO device_contexts VALUES ('DEV-NEW', 'ORG-DEMO')")
        connection.execute("INSERT INTO server_assignments VALUES ('OP-NEW', 'SRV-100', 1)")
    enrolled = voice.enroll_embedding(
        "OP-NEW", [0.0, 1.0, 0.0], "Xenova/wavlm-base-plus-sv", threshold=0.8
    )
    authenticated = voice.authenticate_embedding(
        "DEV-NEW", [0.01, 0.99, 0.0], "Xenova/wavlm-base-plus-sv"
    )
    assert enrolled.enrolled is True
    assert authenticated.authenticated is True
    assert authenticated.roles == ("operator",)
    assert authenticated.tasks == ("server.fix", "server.restart")
