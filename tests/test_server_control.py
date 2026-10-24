from __future__ import annotations

from luma_datacenter.database import Database
from luma_datacenter.models import ServerActionRequest
from luma_datacenter.service import ServerControlService
from luma_datacenter.voice_auth import VoiceAuthService
from luma_datacenter.voice_embeddings import VoiceEmbeddingError
from luma_datacenter.voice_tokens import VoiceTokenSigner


class FakeVoiceEmbedder:
    model_name = "fake-voice-model-v1"

    def embed(self, audio: bytes) -> list[float]:
        if audio == b"enrollment-one":
            return [1.0, 0.0, 0.0]
        if audio == b"matching-voice":
            return [0.99, 0.01, 0.0]
        raise VoiceEmbeddingError("Audio could not be processed")


def build_authenticated_services(tmp_path):
    database = Database(tmp_path / "datacenter.db")
    signer = VoiceTokenSigner(
        tmp_path / "key.pem", issuer="test", audience="datacenter", ttl_seconds=60
    )
    voice = VoiceAuthService(
        database, FakeVoiceEmbedder(), signer, default_threshold=0.75
    )
    voice.enroll("OP-100", [b"enrollment-one"])
    authentication = voice.authenticate("DC-D-100", b"matching-voice")
    assert authentication.authentication_token
    claims = voice.verify_token(authentication.authentication_token)
    return database, ServerControlService(database), claims


def request(claims, *, request_id: str, server_id: str, action: str) -> ServerActionRequest:
    return ServerActionRequest(
        request_id=request_id,
        operator_id=str(claims["sub"]),
        device_id=str(claims["device_id"]),
        organization_id=str(claims["organization_id"]),
        scope=str(claims["scope"]),
        server_id=server_id,
        action=action,
        token_jti=str(claims["jti"]),
    )


def test_authenticated_operator_can_start_assigned_server(tmp_path) -> None:
    database, service, claims = build_authenticated_services(tmp_path)

    result = service.execute(
        request(claims, request_id="start-1", server_id="SRV-100", action="start")
    )

    assert result.authorized is True
    assert result.server_status == "running"
    assert result.spoken_message
    with database.connect() as connection:
        status = connection.execute("SELECT status FROM servers WHERE id = 'SRV-100'").fetchone()
    assert status["status"] == "running"


def test_voice_token_is_single_use(tmp_path) -> None:
    _, service, claims = build_authenticated_services(tmp_path)
    service.execute(request(claims, request_id="first", server_id="SRV-100", action="start"))

    replay = service.execute(
        request(claims, request_id="second", server_id="SRV-200", action="stop")
    )

    assert replay.authorized is False
    assert replay.code == "AUTHENTICATION_ALREADY_USED"


def test_same_request_is_idempotent_even_after_token_consumption(tmp_path) -> None:
    _, service, claims = build_authenticated_services(tmp_path)
    action = request(claims, request_id="same", server_id="SRV-100", action="start")

    first = service.execute(action)
    second = service.execute(action)

    assert second == first
    assert len(service.list_events()) == 1


def test_operator_cannot_control_unassigned_server(tmp_path) -> None:
    _, service, claims = build_authenticated_services(tmp_path)

    result = service.execute(
        request(claims, request_id="restricted", server_id="SRV-300", action="stop")
    )

    assert result.authorized is False
    assert result.code == "SERVER_NOT_ASSIGNED"
    assert result.spoken_message


def test_unsupported_action_is_refused_and_audited(tmp_path) -> None:
    _, service, claims = build_authenticated_services(tmp_path)

    result = service.execute(
        request(claims, request_id="repair", server_id="SRV-100", action="repair")
    )

    assert result.authorized is False
    assert result.code == "ACTION_NOT_SUPPORTED"
    assert len(service.list_events()) == 1
