from __future__ import annotations

import base64
from typing import ClassVar

import pytest
from mcp import Client

from luma_datacenter.backend_mcp import build_backend_server
from luma_datacenter.database import Database
from luma_datacenter.voice_auth import VoiceAuthService
from luma_datacenter.voice_embeddings import VoiceEmbeddingError
from luma_datacenter.voice_tokens import VoiceTokenError, VoiceTokenSigner


class FakeVoiceEmbedder:
    model_name = "fake-voice-model-v1"
    embeddings: ClassVar[dict[bytes, list[float]]] = {
        b"enrollment-one": [1.0, 0.0, 0.0],
        b"enrollment-two": [0.98, 0.02, 0.0],
        b"matching-voice": [0.99, 0.01, 0.0],
        b"different-voice": [0.0, 1.0, 0.0],
    }

    def embed(self, audio: bytes) -> list[float]:
        try:
            return self.embeddings[audio]
        except KeyError as exc:
            raise VoiceEmbeddingError("Audio could not be processed") from exc


def build_service(tmp_path) -> VoiceAuthService:
    return VoiceAuthService(
        Database(tmp_path / "voice.db"),
        FakeVoiceEmbedder(),
        VoiceTokenSigner(
            tmp_path / "voice-key.pem",
            issuer="test-voice-auth",
            audience="test-backend",
            ttl_seconds=60,
        ),
        default_threshold=0.75,
    )


def test_enrollment_and_matching_voice_issue_a_verifiable_token(tmp_path) -> None:
    service = build_service(tmp_path)
    enrollment = service.enroll("OP-100", [b"enrollment-one", b"enrollment-two"])

    result = service.authenticate("DC-D-100", b"matching-voice", "server.restart")

    assert enrollment.enrolled is True
    assert result.authenticated is True
    assert result.code == "VOICE_AUTHENTICATED"
    assert result.authorization_signature
    assert result.spoken_message
    claims = service.verify_token(result.authorization_signature)
    assert claims["sub"] == "OP-100"
    assert claims["device_id"] == "DC-D-100"
    assert claims["permissions"] == ["server:restart"]
    assert claims["tasks"] == ["server.restart"]
    assert claims["organization_id"] == "ORG-DEMO"
    assert claims["roles"] == ["org_admin"]
    assert len(service.list_events()) == 1


def test_different_voice_is_refused_and_audited(tmp_path) -> None:
    service = build_service(tmp_path)
    service.enroll("OP-100", [b"enrollment-one"])

    result = service.authenticate("DC-D-100", b"different-voice", "server.restart")

    assert result.authenticated is False
    assert result.code == "VOICE_NOT_MATCHED"
    assert result.authorization_signature is None
    assert result.spoken_message
    assert service.list_events()[0]["code"] == "VOICE_NOT_MATCHED"


def test_device_without_enrollment_is_refused_and_audited(tmp_path) -> None:
    service = build_service(tmp_path)

    result = service.authenticate("DC-D-100", b"matching-voice", "server.restart")

    assert result.authenticated is False
    assert result.code == "VOICE_NOT_ENROLLED"
    assert len(service.list_events()) == 1


def test_untrusted_device_is_refused_before_voice_processing(tmp_path) -> None:
    service = build_service(tmp_path)

    result = service.authenticate("DC-D-INACTIVE", b"matching-voice", "server.restart")

    assert result.authenticated is False
    assert result.code == "DEVICE_NOT_AUTHORIZED"


def test_invalid_audio_is_refused_and_audited(tmp_path) -> None:
    service = build_service(tmp_path)
    service.enroll("OP-100", [b"enrollment-one"])

    result = service.authenticate("DC-D-100", b"not-a-known-clip", "server.restart")

    assert result.code == "INVALID_AUDIO"
    assert result.spoken_message
    assert len(service.list_events()) == 1


def test_token_tampering_is_rejected(tmp_path) -> None:
    service = build_service(tmp_path)
    service.enroll("OP-100", [b"enrollment-one"])
    result = service.authenticate("DC-D-100", b"matching-voice", "server.restart")
    assert result.authorization_signature
    token = result.authorization_signature
    tampered = token[:-1] + ("a" if token[-1] != "a" else "b")

    with pytest.raises(VoiceTokenError):
        service.verify_token(tampered)


@pytest.mark.anyio
async def test_backend_mcp_authenticates_voice_and_verifies_signature(tmp_path) -> None:
    database_path = tmp_path / "mcp-voice.db"
    signer = VoiceTokenSigner(
        tmp_path / "mcp-key.pem",
        issuer="test-voice-auth",
        audience="test-backend",
        ttl_seconds=60,
    )
    service = VoiceAuthService(
        Database(database_path),
        FakeVoiceEmbedder(),
        signer,
        default_threshold=0.75,
    )
    service.enroll("OP-100", [b"enrollment-one"])
    server = build_backend_server(
        database_path, voice_embedder=FakeVoiceEmbedder(), voice_signer=signer
    )

    async with Client(server) as client:
        response = await client.call_tool(
            "execute_task",
            {
                "task": "authenticate",
                "device_id": "DC-D-100",
                "voice_audio_base64": base64.b64encode(b"matching-voice").decode("ascii"),
                "requested_task": "server.restart",
            },
        )
        authenticated = dict(response.structured_content or {})
        verify_response = await client.call_tool(
            "verify_authorization_signature",
            {"authorization_signature": authenticated["authorization"]["signature"]},
        )
        action_response = await client.call_tool(
            "execute_task",
            {
                "task": "server.restart",
                "authorization_signature": authenticated["authorization"]["signature"],
                "request_id": "mcp-start",
                "server_id": "SRV-100",
            },
        )

    verified = dict(verify_response.structured_content or {})
    action = dict(action_response.structured_content or {})
    assert authenticated["code"] == "VOICE_AUTHENTICATED"
    assert authenticated["authorization"]["roles"] == ["org_admin"]
    assert authenticated["authorization"]["permissions"] == ["server:restart"]
    assert authenticated["authorization"]["tasks"] == ["server.restart"]
    assert verified["authorized"] is True
    assert verified["operator_id"] == "OP-100"
    assert action["authorized"] is True
    assert action["data"]["server_status"] == "running"


@pytest.mark.anyio
async def test_backend_mcp_rejects_invalid_base64_with_spoken_result(tmp_path) -> None:
    database_path = tmp_path / "invalid-base64.db"
    signer = VoiceTokenSigner(
        tmp_path / "invalid-key.pem",
        issuer="test-voice-auth",
        audience="test-backend",
    )
    server = build_backend_server(
        database_path, voice_embedder=FakeVoiceEmbedder(), voice_signer=signer
    )

    async with Client(server) as client:
        response = await client.call_tool(
            "execute_task",
            {
                "task": "authenticate",
                "requested_task": "server.restart",
                "device_id": "DC-D-100",
                "voice_audio_base64": "%%%",
            },
        )

    result = dict(response.structured_content or {})
    assert result["code"] == "INVALID_AUDIO"
    assert result["spoken_message"]


@pytest.mark.anyio
async def test_mcp_signature_is_bound_to_the_requested_task_and_audited(tmp_path) -> None:
    database_path = tmp_path / "mcp-task-binding.db"
    database = Database(database_path)
    signer = VoiceTokenSigner(
        tmp_path / "task-key.pem", issuer="test", audience="datacenter", ttl_seconds=60
    )
    voice = VoiceAuthService(database, FakeVoiceEmbedder(), signer, default_threshold=0.75)
    voice.enroll("OP-100", [b"enrollment-one"])
    server = build_backend_server(
        database_path, voice_embedder=FakeVoiceEmbedder(), voice_signer=signer
    )

    async with Client(server) as client:
        auth_response = await client.call_tool(
            "execute_task",
            {
                "task": "authenticate",
                "device_id": "DC-D-100",
                "voice_audio_base64": base64.b64encode(b"matching-voice").decode("ascii"),
                "requested_task": "server.restart",
            },
        )
        authentication = dict(auth_response.structured_content or {})
        refusal_response = await client.call_tool(
            "execute_task",
            {
                "task": "server.fix",
                "request_id": "wrong-signed-task",
                "authorization_signature": authentication["authorization"]["signature"],
                "server_id": "SRV-200",
            },
        )

    refusal = dict(refusal_response.structured_content or {})
    assert refusal["authorized"] is False
    assert refusal["code"] == "TASK_NOT_AUTHORIZED"
    assert refusal["spoken_message"]
    with database.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM server_action_events WHERE request_id = 'wrong-signed-task'"
        ).fetchone()[0]
    assert count == 1
