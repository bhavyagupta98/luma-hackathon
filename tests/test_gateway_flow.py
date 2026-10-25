"""Gateway flow tests: voice sign-in, permissions, tasks, session expiry, onboarding.

The speaker model is replaced by a fake embedder (each speaker has a fixed vector);
the database, services, sessions and websocket protocol are the real ones.
"""

from __future__ import annotations

import base64
import time
from contextlib import ExitStack, contextmanager

import pytest
from fastapi.testclient import TestClient

from luma_datacenter.administration import UserAdministrationService
from luma_datacenter.database import Database
from luma_datacenter.gateway.app import create_app
from luma_datacenter.models import UserRegistrationRequest
from luma_datacenter.runtime import RuntimeServices
from luma_datacenter.service import ServerControlService
from luma_datacenter.voice_auth import VoiceAuthService
from luma_datacenter.voice_embeddings import VoiceEmbeddingError
from luma_datacenter.voice_tokens import VoiceTokenSigner

SPEAKERS = {
    b"avery": [1.0, 0.0, 0.0, 0.0],
    b"jordan": [0.0, 1.0, 0.0, 0.0],
    b"newhire": [0.0, 0.0, 1.0, 0.0],
    b"stranger": [0.0, 0.0, 0.0, 1.0],
}
DENIED = "You are not allowed to do this task."


class SpeakerEmbedder:
    """Audio is `<speaker>:<anything>`; the speaker picks a fixed unit vector."""

    model_name = "fake-speakers-v1"

    def embed(self, audio: bytes) -> list[float]:
        speaker = audio.split(b":")[0]
        if speaker not in SPEAKERS:
            raise VoiceEmbeddingError("Audio could not be processed")
        return SPEAKERS[speaker]


def clip(speaker: str, name: str = "auth") -> str:
    return base64.b64encode(f"{speaker}:{name}".encode()).decode()


def build_runtime(tmp_path) -> RuntimeServices:
    database = Database(tmp_path / "gateway.db")
    signer = VoiceTokenSigner(
        tmp_path / "key.pem", issuer="test", audience="datacenter", ttl_seconds=60
    )
    voice = VoiceAuthService(database, SpeakerEmbedder(), signer, default_threshold=0.75)
    voice.enroll("OP-100", [b"avery:enroll-1", b"avery:enroll-2"])
    voice.enroll("OP-200", [b"jordan:enroll-1", b"jordan:enroll-2"])
    return RuntimeServices(
        database,
        ServerControlService(database),
        UserAdministrationService(database),
        voice,
        signer,
    )


@pytest.fixture
def runtime(tmp_path) -> RuntimeServices:
    return build_runtime(tmp_path)


@contextmanager
def running_gateway(runtime, session_ttl_seconds: float, **app_options):
    # Entering the client keeps one event loop alive across websocket connections;
    # the stack closes every earpiece opened during the test.
    app = create_app(runtime, session_ttl_seconds=session_ttl_seconds, **app_options)
    with TestClient(app) as test_client, ExitStack() as stack:
        test_client.stack = stack
        yield test_client


@pytest.fixture
def client(runtime):
    with running_gateway(runtime, 60) as test_client:
        yield test_client


def open_earpiece(client, device: str):
    earpiece = client.stack.enter_context(client.websocket_connect(f"/ws/{device}"))
    assert earpiece.receive_json()["type"] == "hello"
    return earpiece


def sign_in(earpiece, speaker: str, name: str = "auth") -> dict:
    earpiece.send_json({"type": "voice_auth", "audio_wav_base64": clip(speaker, name)})
    result = earpiece.receive_json()
    assert result["type"] == "auth_result"
    return result


def say(earpiece, text: str, session_id: str | None) -> dict:
    earpiece.send_json({"type": "utterance", "text": text, "session_id": session_id})
    reply = earpiece.receive_json()
    assert reply["type"] == "say"
    return reply


def server_status(runtime, server_id: str) -> str:
    with runtime.database.connect() as connection:
        return connection.execute(
            "SELECT status FROM servers WHERE id = ?", (server_id,)
        ).fetchone()["status"]


def task_events(runtime) -> list[dict]:
    with runtime.database.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM server_action_events WHERE request_id LIKE 'task-%' ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


# ---- 1) Authentication ----


def test_voice_sign_in_returns_name_role_and_permissions(client) -> None:
    earpiece = open_earpiece(client, "DC-D-100")
    result = sign_in(earpiece, "avery")

    assert result["authenticated"] is True
    assert result["spoken_message"] == "Avery Chen is authenticated."
    assert result["role"] == "org_admin"
    assert result["operator"] == {"id": "OP-100", "name": "Avery Chen", "role": "org_admin"}
    assert result["permissions"]["servers"] == ["SRV-100", "SRV-200"]
    assert "server:control" in result["permissions"]["scopes"]
    assert result["expires_in"] == 60
    assert result["session_id"]
    assert "authentication_token" not in result  # the backend's signed token stays server-side


def test_operator_gets_only_their_own_servers(client) -> None:
    result = sign_in(open_earpiece(client, "DC-D-200"), "jordan")

    assert result["role"] == "operator"
    assert result["permissions"]["servers"] == ["SRV-300"]
    assert result["permissions"]["scopes"] == ["server:control"]


def test_a_different_voice_on_the_device_is_refused(client) -> None:
    earpiece = open_earpiece(client, "DC-D-100")
    result = sign_in(earpiece, "stranger")

    assert result["authenticated"] is False
    assert result["code"] == "VOICE_NOT_MATCHED"
    assert "session_id" not in result
    assert result["spoken_message"] == "You are not registered."
    assert say(earpiece, "restart server one hundred", None)["text"] == (
        "Please authenticate with your voice first."
    )


def test_another_enrolled_workers_voice_cannot_use_my_device(client) -> None:
    result = sign_in(open_earpiece(client, "DC-D-100"), "jordan")  # Jordan on Avery's device

    assert result["authenticated"] is False
    assert result["code"] == "VOICE_NOT_MATCHED"
    assert result["spoken_message"] == "You are not registered."


def test_unknown_device_and_unusable_audio_are_refused(client) -> None:
    assert sign_in(open_earpiece(client, "DC-D-NOPE"), "avery")["code"] == "DEVICE_NOT_AUTHORIZED"

    earpiece = open_earpiece(client, "DC-D-100")
    for audio in ("", "%%% not base64 %%%"):
        earpiece.send_json({"type": "voice_auth", "audio_wav_base64": audio})
        result = earpiece.receive_json()
        assert result["authenticated"] is False
        assert result["code"] == "INVALID_AUDIO"
        assert result["spoken_message"] == "I couldn't hear you clearly. Please try again."


# ---- 2) Tasks ----


def test_restart_an_assigned_server_succeeds(client, runtime) -> None:
    earpiece = open_earpiece(client, "DC-D-100")
    session = sign_in(earpiece, "avery")["session_id"]
    assert server_status(runtime, "SRV-100") == "stopped"

    reply = say(earpiece, "Restart server one hundred.", session)

    assert reply["text"] == "Task successful."
    assert reply["earcon"] == "success"
    assert server_status(runtime, "SRV-100") == "running"
    (event,) = task_events(runtime)
    assert (event["operator_id"], event["server_id"], event["action"]) == (
        "OP-100",
        "SRV-100",
        "restart",
    )
    assert event["authorized"] == 1
    assert client.get("/api/servers").json()["servers"][0]["status"] == "running"


def test_fix_an_assigned_server_succeeds(client, runtime) -> None:
    earpiece = open_earpiece(client, "DC-D-100")
    session = sign_in(earpiece, "avery")["session_id"]

    assert say(earpiece, "fix server 200", session)["text"] == "Task successful."
    assert task_events(runtime)[0]["action"] == "fix"


def test_a_server_the_worker_is_not_assigned_to_is_refused(client, runtime) -> None:
    earpiece = open_earpiece(client, "DC-D-200")
    session = sign_in(earpiece, "jordan")["session_id"]  # Jordan only has SRV-300

    reply = say(earpiece, "restart server one hundred", session)

    assert reply["text"] == DENIED
    assert reply["earcon"] == "error"
    assert server_status(runtime, "SRV-100") == "stopped"  # nothing changed
    (event,) = task_events(runtime)
    assert event["authorized"] == 0
    assert event["code"] == "SERVER_NOT_ASSIGNED"

    assert say(earpiece, "fix server three hundred", session)["text"] == "Task successful."


def test_unknown_server_and_unrecognized_requests(client, runtime) -> None:
    earpiece = open_earpiece(client, "DC-D-100")
    session = sign_in(earpiece, "avery")["session_id"]

    assert say(earpiece, "restart server nine hundred", session)["text"] == (
        "I couldn't find that server."
    )
    assert "Which server" in say(earpiece, "restart the server", session)["text"]
    help_text = say(earpiece, "what's the weather", session)["text"]
    assert "restart a server or fix a server" in help_text
    assert len(task_events(runtime)) == 2  # only real task attempts are audited


def test_tasks_need_a_live_session_from_the_same_device(client, runtime) -> None:
    avery = open_earpiece(client, "DC-D-100")
    session = sign_in(avery, "avery")["session_id"]
    jordan = open_earpiece(client, "DC-D-200")
    sign_in(jordan, "jordan")

    not_signed_in = "Please authenticate with your voice first."
    assert say(avery, "restart server one hundred", None)["text"] == not_signed_in
    assert say(avery, "restart server one hundred", "forged-session")["text"] == not_signed_in
    # Avery's session id presented from Jordan's device is rejected.
    assert say(jordan, "restart server one hundred", session)["text"] == not_signed_in
    assert task_events(runtime) == []
    assert server_status(runtime, "SRV-100") == "stopped"


def test_signing_in_again_replaces_the_previous_session(client) -> None:
    earpiece = open_earpiece(client, "DC-D-100")
    first = sign_in(earpiece, "avery", "auth-1")["session_id"]
    second = sign_in(earpiece, "avery", "auth-2")["session_id"]

    assert say(earpiece, "fix server one hundred", first)["text"].startswith("Please authenticate")
    assert say(earpiece, "fix server one hundred", second)["text"] == "Task successful."


def test_servers_can_be_named_a_b_c(client, runtime) -> None:
    avery = open_earpiece(client, "DC-D-100")
    session = sign_in(avery, "avery")["session_id"]
    assert say(avery, "Fix server A.", session)["text"] == "Task successful."
    assert say(avery, "restart server bee", session)["text"] == "Task successful."
    # C is SRV-300, which belongs to Jordan, not Avery.
    assert say(avery, "restart server C", session)["text"] == DENIED
    assert [(e["action"], e["server_id"], e["authorized"]) for e in task_events(runtime)] == [
        ("fix", "SRV-100", 1),
        ("restart", "SRV-200", 1),
        ("restart", "SRV-300", 0),
    ]

    jordan = open_earpiece(client, "DC-D-200")
    jordan_session = sign_in(jordan, "jordan")["session_id"]
    assert say(jordan, "fix server C", jordan_session)["text"] == "Task successful."
    assert say(jordan, "fix server A", jordan_session)["text"] == DENIED


# ---- 3) Session expiry ----


def test_session_is_cleared_after_the_time_limit(runtime) -> None:
    with running_gateway(runtime, 1.0) as client:
        avery = open_earpiece(client, "DC-D-100")
        session = sign_in(avery, "avery")["session_id"]
        assert say(avery, "fix server one hundred", session)["text"] == "Task successful."
        time.sleep(0.5)
        jordan = open_earpiece(client, "DC-D-200")
        jordan_session = sign_in(jordan, "jordan")["session_id"]

        assert avery.receive_json() == {"type": "session_expired", "session_id": session}
        notice = avery.receive_json()
        assert notice["text"] == "Your session has expired. Please authenticate again."
        assert notice["priority"] == "warning"

        # Only Avery's session was cleared; Jordan's is still inside its minute.
        expired_reply = say(avery, "fix server one hundred", session)
        assert expired_reply["text"].startswith("Please authenticate")
        still_ok = say(jordan, "fix server three hundred", jordan_session)
        assert still_ok["text"] == "Task successful."
        assert client.app.state.sessions.active_count() == 1


# ---- 4) Onboarding a new worker by voice ----


def test_admin_onboards_a_new_worker_who_then_signs_in_by_voice(client, runtime) -> None:
    # The admin proves their identity by voice; that signed token authorizes adding the user.
    admin_auth = runtime.voice.authenticate("DC-D-100", b"avery:onboarding")
    assert admin_auth.authenticated
    claims = runtime.voice.verify_token(admin_auth.authentication_token)
    added = runtime.administration.add_user(
        UserRegistrationRequest(
            request_id="onboard-newhire",
            actor_operator_id=claims["sub"],
            actor_device_id=claims["device_id"],
            actor_organization_id=claims["organization_id"],
            actor_scope=claims["scope"],
            token_jti=claims["jti"],
            organization_id="ORG-DEMO",
            user_id="OP-NEWHIRE",
            display_name="Casey Nguyen",
            role="operator",
            device_id="DC-D-NEWHIRE",
            server_ids=("SRV-100",),
        )
    )
    assert added.approved, added.spoken_message

    # Until they enroll their own voice they cannot sign in.
    earpiece = open_earpiece(client, "DC-D-NEWHIRE")
    assert sign_in(earpiece, "newhire")["code"] == "VOICE_NOT_ENROLLED"

    enrolled = runtime.voice.enroll("OP-NEWHIRE", [b"newhire:enroll-1", b"newhire:enroll-2"])
    assert enrolled.enrolled

    signed_in = sign_in(earpiece, "newhire")
    assert signed_in["spoken_message"] == "Casey Nguyen is authenticated."
    assert signed_in["role"] == "operator"
    assert signed_in["permissions"]["servers"] == ["SRV-100"]
    session = signed_in["session_id"]
    assert say(earpiece, "restart server one hundred", session)["text"] == "Task successful."
    assert say(earpiece, "restart server two hundred", session)["text"] == DENIED

    # The new worker's voice does not open anyone else's device.
    assert sign_in(open_earpiece(client, "DC-D-100"), "newhire")["authenticated"] is False


def test_an_operator_cannot_onboard_anyone(client, runtime) -> None:
    auth = runtime.voice.authenticate("DC-D-200", b"jordan:onboarding")
    claims = runtime.voice.verify_token(auth.authentication_token)
    refused = runtime.administration.add_user(
        UserRegistrationRequest(
            request_id="onboard-denied",
            actor_operator_id=claims["sub"],
            actor_device_id=claims["device_id"],
            actor_organization_id=claims["organization_id"],
            actor_scope=claims["scope"],
            token_jti=claims["jti"],
            organization_id="ORG-DEMO",
            user_id="OP-SNEAKY",
            display_name="Sneaky",
            role="operator",
            device_id="DC-D-SNEAKY",
            server_ids=("SRV-300",),
        )
    )
    assert refused.approved is False


# ---- 5) Browser enrollment (demo-only, opt-in, this computer only) ----


def enroll(earpiece, *speakers: str, name: str | None = None) -> dict:
    message = {"type": "voice_enroll", "clips": [clip(s, "enroll") for s in speakers]}
    if name is not None:
        message["name"] = name
    earpiece.send_json(message)
    result = earpiece.receive_json()
    assert result["type"] == "enroll_result"
    return result


def test_browser_enrollment_is_off_unless_the_server_enables_it(client) -> None:
    result = enroll(open_earpiece(client, "DC-D-200"), "stranger", "stranger")

    assert result["enrolled"] is False
    assert result["code"] == "ENROLLMENT_DISABLED"
    # Jordan's existing voice profile is untouched.
    assert sign_in(open_earpiece(client, "DC-D-200"), "jordan")["authenticated"] is True


def test_browser_enrollment_is_refused_from_other_computers(runtime) -> None:
    # The test client reports its host as "testclient", which is not this computer.
    with running_gateway(runtime, 60, allow_enrollment=True) as other:
        result = enroll(open_earpiece(other, "DC-D-200"), "stranger", "stranger")

    assert result["code"] == "ENROLLMENT_NOT_ALLOWED"
    assert result["enrolled"] is False


def test_browser_enrollment_replaces_the_voice_profile(runtime) -> None:
    with running_gateway(runtime, 60, allow_enrollment=True, enrollment_hosts=("testclient",)) as c:
        earpiece = open_earpiece(c, "DC-D-200")
        result = enroll(earpiece, "stranger", "stranger", "stranger")

        assert result["enrolled"] is True
        assert result["operator"] == {"id": "OP-200", "name": "Jordan Patel"}
        assert result["spoken_message"] == "Jordan Patel, you are enrolled."
        # The new voice signs in; the old one no longer does.
        signed_in = sign_in(earpiece, "stranger")
        assert signed_in["authenticated"] is True
        assert signed_in["spoken_message"] == "Jordan Patel is authenticated."
        assert sign_in(earpiece, "jordan")["code"] == "VOICE_NOT_MATCHED"


def test_browser_enrollment_rejects_bad_input(runtime) -> None:
    with running_gateway(runtime, 60, allow_enrollment=True, enrollment_hosts=("testclient",)) as c:
        earpiece = open_earpiece(c, "DC-D-200")
        for clips in (None, [], ["%%% not base64 %%%"], ["x"] * 6):
            earpiece.send_json({"type": "voice_enroll", "clips": clips})
            result = earpiece.receive_json()
            assert (result["enrolled"], result["code"]) == (False, "INVALID_AUDIO")

        # A clip the speaker model cannot process is reported, not crashed on.
        assert enroll(earpiece, "nobody")["enrolled"] is False
        # Unknown devices cannot enroll anyone.
        assert enroll(open_earpiece(c, "DC-D-NOPE"), "stranger")["code"] == "DEVICE_NOT_AUTHORIZED"
        # Neither failure disturbed Jordan's real profile.
        assert sign_in(earpiece, "jordan")["authenticated"] is True


def operator_name(runtime, operator_id: str) -> str:
    with runtime.database.connect() as connection:
        return connection.execute(
            "SELECT name FROM operators WHERE id = ?", (operator_id,)
        ).fetchone()["name"]


def test_enrolling_with_a_spoken_name_renames_the_operator(runtime) -> None:
    with running_gateway(runtime, 60, allow_enrollment=True, enrollment_hosts=("testclient",)) as c:
        earpiece = open_earpiece(c, "DC-D-200")
        result = enroll(earpiece, "stranger", "stranger", name="  Sam   Rivera ")

        assert result["enrolled"] is True
        assert result["spoken_message"] == "Sam Rivera, you are enrolled."
        assert result["operator"] == {"id": "OP-200", "name": "Sam Rivera"}
        assert operator_name(runtime, "OP-200") == "Sam Rivera"
        # Sign-in now greets the person by the name they spoke.
        signed_in = sign_in(earpiece, "stranger")
        assert signed_in["spoken_message"] == "Sam Rivera is authenticated."
        assert signed_in["operator"]["name"] == "Sam Rivera"


@pytest.mark.parametrize("bad_name", ["", "   ", "Bob123", "x" * 61, "<script>", "7 of 9"])
def test_an_implausible_name_is_refused_and_nothing_changes(runtime, bad_name) -> None:
    with running_gateway(runtime, 60, allow_enrollment=True, enrollment_hosts=("testclient",)) as c:
        earpiece = open_earpiece(c, "DC-D-200")
        result = enroll(earpiece, "stranger", "stranger", name=bad_name)

        assert (result["enrolled"], result["code"]) == (False, "INVALID_NAME")
        assert operator_name(runtime, "OP-200") == "Jordan Patel"
        # The voice profile was not replaced either: Jordan still signs in, the stranger does not.
        assert sign_in(earpiece, "jordan")["authenticated"] is True
        assert sign_in(earpiece, "stranger")["authenticated"] is False


def test_a_failed_voice_enrollment_does_not_rename_anyone(runtime) -> None:
    with running_gateway(runtime, 60, allow_enrollment=True, enrollment_hosts=("testclient",)) as c:
        earpiece = open_earpiece(c, "DC-D-200")
        # The speaker model rejects the "nobody" clip.
        result = enroll(earpiece, "nobody", name="Sam Rivera")

        assert result["enrolled"] is False
        assert operator_name(runtime, "OP-200") == "Jordan Patel"


def test_enrolling_without_a_name_keeps_the_existing_name(runtime) -> None:
    with running_gateway(runtime, 60, allow_enrollment=True, enrollment_hosts=("testclient",)) as c:
        result = enroll(open_earpiece(c, "DC-D-200"), "stranger", "stranger")

        assert result["spoken_message"] == "Jordan Patel, you are enrolled."
        assert operator_name(runtime, "OP-200") == "Jordan Patel"
