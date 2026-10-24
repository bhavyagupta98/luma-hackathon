from __future__ import annotations

import base64

import pytest
from mcp import Client

from luma_datacenter.administration import UserAdministrationService, bootstrap_admin
from luma_datacenter.backend_mcp import build_backend_server
from luma_datacenter.database import Database
from luma_datacenter.models import UserRegistrationRequest
from luma_datacenter.voice_auth import VoiceAuthService
from luma_datacenter.voice_embeddings import VoiceEmbeddingError
from luma_datacenter.voice_tokens import VoiceTokenSigner


class FakeVoiceEmbedder:
    model_name = "fake-voice-model-v1"

    def embed(self, audio: bytes) -> list[float]:
        if audio in {b"admin-enrollment", b"admin-voice", b"new-user-voice"}:
            return [1.0, 0.0, 0.0]
        raise VoiceEmbeddingError("Audio could not be processed")


def authenticated_admin(tmp_path):
    database = Database(tmp_path / "admin.db")
    signer = VoiceTokenSigner(
        tmp_path / "key.pem", issuer="test", audience="datacenter", ttl_seconds=60
    )
    voice = VoiceAuthService(database, FakeVoiceEmbedder(), signer, default_threshold=0.75)
    voice.enroll("OP-100", [b"admin-enrollment"])
    authentication = voice.authenticate("DC-D-100", b"admin-voice", "user.add")
    assert authentication.authorization_signature
    claims = voice.verify_token(authentication.authorization_signature)
    return database, voice, UserAdministrationService(database), claims


def registration(claims, **overrides) -> UserRegistrationRequest:
    values = {
        "request_id": "add-user-1",
        "actor_operator_id": str(claims["sub"]),
        "actor_device_id": str(claims["device_id"]),
        "actor_organization_id": str(claims["organization_id"]),
        "actor_roles": tuple(claims["roles"]),
        "actor_permissions": tuple(claims["permissions"]),
        "actor_authorized_tasks": tuple(claims["tasks"]),
        "token_jti": str(claims["jti"]),
        "organization_id": "ORG-DEMO",
        "user_id": "OP-NEW",
        "display_name": "New Operator",
        "role": "operator",
        "device_id": "DC-D-NEW",
        "server_ids": ("SRV-100",),
    }
    values.update(overrides)
    return UserRegistrationRequest(**values)


def test_admin_can_add_operator_with_device_and_server_assignment(tmp_path) -> None:
    database, voice, service, claims = authenticated_admin(tmp_path)

    result = service.add_user(registration(claims))

    assert result.approved is True
    assert result.code == "USER_ADDED_VOICE_ENROLLMENT_REQUIRED"
    assert result.spoken_message
    with database.connect() as connection:
        membership = connection.execute(
            """
            SELECT role FROM organization_memberships
            WHERE organization_id = 'ORG-DEMO' AND operator_id = 'OP-NEW'
            """
        ).fetchone()
    assert membership["role"] == "operator"

    enrollment = voice.enroll("OP-NEW", [b"new-user-voice"])
    authenticated = voice.authenticate("DC-D-NEW", b"new-user-voice", "server.restart")
    assert enrollment.enrolled is True
    assert authenticated.authenticated is True
    assert authenticated.roles == ("operator",)


def test_admin_can_add_another_admin(tmp_path) -> None:
    _, _, service, claims = authenticated_admin(tmp_path)

    result = service.add_user(
        registration(
            claims,
            user_id="ADMIN-NEW",
            display_name="New Admin",
            role="org_admin",
            device_id="DC-ADMIN-NEW",
            server_ids=(),
        )
    )

    assert result.approved is True
    assert result.role == "org_admin"


def test_user_add_token_is_single_use_and_request_is_idempotent(tmp_path) -> None:
    _, _, service, claims = authenticated_admin(tmp_path)
    first_request = registration(claims)
    first = service.add_user(first_request)
    replay = service.add_user(first_request)
    second_user = service.add_user(
        registration(
            claims,
            request_id="add-user-2",
            user_id="OP-SECOND",
            display_name="Second Operator",
            device_id="DC-D-SECOND",
        )
    )

    assert replay == first
    assert second_user.code == "AUTHENTICATION_ALREADY_USED"


def test_operator_role_cannot_add_users(tmp_path) -> None:
    database, voice, admin_service, admin_claims = authenticated_admin(tmp_path)
    added = admin_service.add_user(registration(admin_claims))
    assert added.approved
    voice.enroll("OP-NEW", [b"new-user-voice"])
    operator_auth = voice.authenticate("DC-D-NEW", b"new-user-voice", "user.add")

    assert operator_auth.authenticated is False
    assert operator_auth.code == "TASK_NOT_AUTHORIZED"
    assert len(admin_service.list_events()) == 1


def test_local_bootstrap_creates_first_admin_identity(tmp_path) -> None:
    database = Database(tmp_path / "bootstrap.db")

    bootstrap_admin(
        database,
        organization_id="ORG-NEW",
        organization_name="New Datacenter",
        user_id="ADMIN-1",
        display_name="First Admin",
        device_id="DEV-ADMIN-1",
    )

    with database.connect() as connection:
        membership = connection.execute(
            """
            SELECT role FROM organization_memberships
            WHERE organization_id = 'ORG-NEW' AND operator_id = 'ADMIN-1'
            """
        ).fetchone()
    assert membership["role"] == "org_admin"


@pytest.mark.anyio
async def test_mcp_admin_voice_can_add_user_with_all_required_details(tmp_path) -> None:
    database_path = tmp_path / "mcp-admin.db"
    database = Database(database_path)
    signer = VoiceTokenSigner(
        tmp_path / "mcp-key.pem", issuer="test", audience="datacenter", ttl_seconds=60
    )
    voice = VoiceAuthService(database, FakeVoiceEmbedder(), signer, default_threshold=0.75)
    voice.enroll("OP-100", [b"admin-enrollment"])
    server = build_backend_server(
        database_path, voice_embedder=FakeVoiceEmbedder(), voice_signer=signer
    )

    async with Client(server) as client:
        auth_response = await client.call_tool(
            "execute_task",
            {
                "task": "authenticate",
                "device_id": "DC-D-100",
                "voice_audio_base64": base64.b64encode(b"admin-voice").decode("ascii"),
                "requested_task": "user.add",
            },
        )
        authentication = dict(auth_response.structured_content or {})
        add_response = await client.call_tool(
            "execute_task",
            {
                "task": "user.add",
                "authorization_signature": authentication["authorization"]["signature"],
                "request_id": "mcp-add-user",
                "organization_id": "ORG-DEMO",
                "user_id": "OP-MCP",
                "display_name": "MCP Operator",
                "role": "operator",
                "user_device_id": "DC-D-MCP",
                "server_ids": ["SRV-100"],
            },
        )

    result = dict(add_response.structured_content or {})
    assert result["authorized"] is True
    assert result["code"] == "USER_ADDED_VOICE_ENROLLMENT_REQUIRED"
    assert result["spoken_message"]
